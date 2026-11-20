#!/usr/bin/env python3
"""Run N container desktops on one host, replay OSWorld trajectories, and profile them.

An Android-style "swarm" on Linux: every desktop is a container from the same
image (the read-only layers and their page cache are shared by the kernel), and
a lifecycle manager moves each desktop between running and frozen as its agent
alternates between acting and waiting for the model. No model is called; each
instance replays a recorded trajectory with its recorded step gaps.

Policies:
  always          desktops keep running while their agent waits
  freeze          after an action, wait --settle seconds for the aftershock, then
                  freeze the container's cgroup (cgroup.freeze) until the next action
  freeze-reclaim  as freeze, then ask the kernel to reclaim the frozen cgroup's
                  memory (memory.reclaim); without swap only file pages can go

Measured: host memory, PSI, fault/refault/reclaim counters (/proc/vmstat) and
CPU every --host-interval seconds; each container's cgroup (CPU, anon, file,
shmem, faults, refaults, PSI); every container process's CPU, faults and RSS
every --process-interval seconds (procs.jsonl, see sandweaver/procs.py);
proportional set size per container every --pss-interval seconds; per step the
action and screenshot latency, freeze, reclaim and thaw latency, and the memory
a reclaim released. Step times in result.json are relative to `epoch_ns`, the
host monotonic clock that samples.jsonl and procs.jsonl use.

The desktop image must serve OSWorld's Flask API on port 5000 (CUA-Lite's
lite.osworld image does). Run as root on a cgroup v2 host:
  sudo python benchmarks/desktop-swarm.py --pilot pilot.json --n 4 --policy freeze --output runs/x
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import types

REPO = Path(__file__).resolve().parents[1]


def stub_modules():
    """Names the OSWorld controllers import but this runner never uses."""
    os.environ.setdefault("DISPLAY", ":0")
    if "pyautogui" not in sys.modules:
        fake = types.ModuleType("pyautogui")
        fake.isShiftCharacter = lambda c: False
        sys.modules["pyautogui"] = fake
    utils = types.ModuleType("desktop_env.evaluators.metrics.utils")
    utils.compare_urls = lambda a, b, **_: a.rstrip("/") == b.rstrip("/")
    proxy = types.ModuleType("desktop_env.providers.aws.proxy_pool")
    proxy.get_global_proxy_pool = lambda: None
    proxy.init_proxy_pool = lambda *_: None
    proxy.ProxyInfo = object
    for name in ("desktop_env.evaluators", "desktop_env.evaluators.metrics",
                 "desktop_env.providers.aws"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["desktop_env.evaluators.metrics.utils"] = utils
    sys.modules["desktop_env.providers.aws.proxy_pool"] = proxy


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def load_steps(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    rows.sort(key=lambda r: int(r["step_num"]))
    times = [datetime.strptime(r["action_timestamp"], "%Y%m%d@%H%M%S%f").timestamp()
             for r in rows]
    steps = []
    for i, row in enumerate(rows):
        action = row["action"]
        try:
            action = ast.literal_eval(action)
        except (ValueError, SyntaxError):
            pass
        gap = times[i + 1] - times[i] if i + 1 < len(times) else None
        steps.append({"step": int(row["step_num"]), "action": action, "recorded_gap_s": gap})
    return steps


def to_command(action, converter):
    if isinstance(action, str):
        return action
    if not isinstance(action, dict):
        return None
    if action.get("action_type") in ("DONE", "FAIL", "WAIT"):
        return action["action_type"]
    if action.get("command"):
        return action["command"]
    if action.get("name") == "computer":
        return converter(action) or None
    return None


# ── host-side measurement ────────────────────────────────────────────────────

def read_meminfo():
    wanted = ("MemTotal", "MemAvailable", "Cached", "AnonPages", "Shmem", "SwapTotal",
              "SwapFree", "AnonHugePages")
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        if key in wanted:
            info[key] = int(rest.split()[0]) * 1024
    return info


def read_pressure(kind):
    out = {}
    for line in Path(f"/proc/pressure/{kind}").read_text().splitlines():
        parts = line.split()
        fields = dict(p.split("=") for p in parts[1:])
        out[parts[0]] = {"avg10": float(fields["avg10"]), "total_us": int(fields["total"])}
    return out


VMSTAT_KEYS = ("pgmajfault", "pgfault", "workingset_refault_anon", "workingset_refault_file",
               "pgscan_kswapd", "pgscan_direct", "pgsteal_kswapd", "pgsteal_direct",
               "pswpin", "pswpout", "pgpgin", "pgpgout")


def read_vmstat():
    """Host-wide cumulative fault, refault, reclaim and swap counters."""
    out = {}
    for line in Path("/proc/vmstat").read_text().splitlines():
        key, _, value = line.partition(" ")
        if key in VMSTAT_KEYS:
            out[key] = int(value)
    return out


def read_host_cpu():
    fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    values = list(map(int, fields))
    idle = values[3] + values[4]
    return {"busy_ticks": sum(values) - idle, "total_ticks": sum(values)}


def cgroup_pss(directory):
    """Sum of proportional set size and private memory over a cgroup's processes."""
    pss = private = 0
    procs = (directory / "cgroup.procs").read_text().split()
    for pid in procs:
        try:
            text = Path(f"/proc/{pid}/smaps_rollup").read_text()
        except OSError:
            continue
        for line in text.splitlines():
            key, _, rest = line.partition(":")
            if key == "Pss":
                pss += int(rest.split()[0]) * 1024
            elif key in ("Private_Clean", "Private_Dirty"):
                private += int(rest.split()[0]) * 1024
    return {"pss": pss, "private": private, "procs": len(procs)}


class Profiler:
    """Background sampling of the host and every registered container cgroup."""

    def __init__(self, host_interval, pss_interval, out, process_interval=0.0, procs_out=None):
        from sandweaver import procs, sampler
        self.sampler, self.procs = sampler, procs
        self.host_interval, self.pss_interval = host_interval, pss_interval
        self.process_interval = process_interval
        self.cgroups = {}
        self.process_samplers = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.handle = out.open("w")
        self.procs_handle = procs_out.open("w") if process_interval and procs_out else None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.procs_thread = threading.Thread(target=self.run_procs, daemon=True)
        self.procs_cost_ns = 0
        self.procs_ticks = 0

    def register(self, name, directory):
        with self.lock:
            self.cgroups[name] = directory
            if self.procs_handle:
                self.process_samplers[name] = self.procs.ProcessSampler(str(directory))

    def run_procs(self):
        """Per-process CPU, faults and RSS of every registered container."""
        next_due = time.monotonic()
        while not self.stop.is_set():
            begin = time.monotonic_ns()
            with self.lock:
                samplers = dict(self.process_samplers)
            lines = []
            for name, sampler in samplers.items():
                try:
                    lines.append(json.dumps({"container": name, **sampler.tick()},
                                            separators=(",", ":")))
                except (OSError, ValueError):
                    pass  # the container is gone
            self.procs_handle.write("".join(line + "\n" for line in lines))
            self.procs_cost_ns += time.monotonic_ns() - begin
            self.procs_ticks += 1
            next_due += self.process_interval
            self.stop.wait(max(0.0, next_due - time.monotonic()))

    def write(self, record):
        with self.lock:
            self.handle.write(json.dumps(record) + "\n")

    def run(self):
        next_pss = 0.0
        while not self.stop.is_set():
            now = time.monotonic()
            record = {"t_ns": time.monotonic_ns(), "kind": "host", "mem": read_meminfo(),
                      "psi_memory": read_pressure("memory"), "psi_cpu": read_pressure("cpu"),
                      "psi_io": read_pressure("io"), "vmstat": read_vmstat(),
                      "cpu": read_host_cpu(), "containers": {}}
            with self.lock:
                cgroups = dict(self.cgroups)
            for name, directory in cgroups.items():
                try:
                    sample = self.sampler.read_sample(directory)
                    sample["frozen"] = "frozen 1" in (directory / "cgroup.events").read_text()
                    if now >= next_pss:
                        sample.update(cgroup_pss(directory))
                    record["containers"][name] = sample
                except (OSError, ValueError):
                    record["containers"][name] = None
            if now >= next_pss:
                next_pss = now + self.pss_interval
            self.write(record)
            self.stop.wait(self.host_interval)

    def __enter__(self):
        self.thread.start()
        if self.procs_handle:
            self.procs_thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.handle.close()
        if self.procs_handle:
            self.procs_thread.join()
            self.procs_handle.close()

    def summary(self):
        return {"process_interval_s": self.process_interval, "process_ticks": self.procs_ticks,
                "process_tick_cost_ms_mean": (self.procs_cost_ns / self.procs_ticks / 1e6
                                              if self.procs_ticks else None)}


# ── lifecycle ────────────────────────────────────────────────────────────────

def set_frozen(directory, frozen, timeout=10.0):
    """Write cgroup.freeze and wait until cgroup.events reports the new state."""
    begin = time.monotonic_ns()
    (directory / "cgroup.freeze").write_text("1" if frozen else "0")
    want = f"frozen {1 if frozen else 0}"
    deadline = time.monotonic() + timeout
    while want not in (directory / "cgroup.events").read_text():
        if time.monotonic() > deadline:
            raise TimeoutError(f"cgroup did not reach '{want}'")
        time.sleep(0.001)
    return time.monotonic_ns() - begin


def reclaim(directory):
    """Ask the kernel to reclaim as much of the cgroup's memory as it can."""
    before = int((directory / "memory.current").read_text())
    begin = time.monotonic_ns()
    try:
        (directory / "memory.reclaim").write_text(str(before))
        complete = True
    except OSError:
        # EAGAIN: the kernel reclaimed less than asked (expected without swap).
        complete = False
    elapsed = time.monotonic_ns() - begin
    after = int((directory / "memory.current").read_text())
    return {"reclaim_ns": elapsed, "before": before, "after": after, "complete": complete}


class Desktop:
    def __init__(self, index, args):
        self.index, self.args = index, args
        self.name = f"{args.prefix}-{index}"
        self.directory = None
        self.ip = None

    def start(self):
        docker("rm", "-f", self.name, check=False)
        run = ["run", "-d", "--name", self.name, "--shm-size", "2g",
               "-e", "VNC_RESOLUTION=1920x1080"]
        for item in self.args.docker_arg:
            run.append(item)
        docker(*run, self.args.image)
        self.ip = docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                         self.name).stdout.strip()
        from sandweaver import sampler
        self.directory = sampler.cgroup_dir(self.name)

    def screenshot(self):
        """PNG of display :1. CUA-Lite's server has no /screenshot route. Its
        exec-stdio server grabs with python-xlib, which took 6-10 s per 1080p frame
        on this host (2026-11-19), so use ffmpeg x11grab (about 0.3 s)."""
        out = subprocess.run(["docker", "exec", "-u", "user", "-e", "DISPLAY=:1", self.name,
                              "ffmpeg", "-loglevel", "error", "-f", "x11grab",
                              "-video_size", "1920x1080", "-i", ":1", "-frames:v", "1",
                              "-c:v", "png", "-compression_level", "1", "-f", "image2pipe", "-"],
                             capture_output=True, timeout=60)
        return out.stdout if out.returncode == 0 else b""

    def wait_ready(self, timeout):
        """CUA-Lite opens port 5000 only after GNOME Shell reports ready."""
        import requests
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if requests.get(f"http://{self.ip}:5000/platform", timeout=10).ok:
                    return len(self.screenshot()) > 10000
            except requests.RequestException:
                pass
            time.sleep(1)
        return False

    def remove(self):
        docker("rm", "-f", self.name, check=False)


def replay(desktop, traj, args, profiler, epoch_ns):
    """Boot, set up, and replay one trajectory on one desktop under the chosen policy."""
    from desktop_env.controllers.python import PythonController
    from desktop_env.controllers.setup import SetupController
    from mm_agents.anthropic.main import AnthropicAgent

    task_id, domain = Path(traj).parent.name, Path(traj).parent.parent.name
    record = {"instance": desktop.index, "name": desktop.name, "task_id": task_id,
              "domain": domain, "steps": []}
    time.sleep(desktop.index * args.stagger)
    begin = time.monotonic_ns()
    try:
        desktop.start()
        profiler.register(desktop.name, desktop.directory)
        record["ready"] = desktop.wait_ready(args.ready_timeout)
        record["boot_ns"] = time.monotonic_ns() - begin
        if not record["ready"]:
            raise RuntimeError("desktop never served a screenshot")
        config = json.loads((args.osworld / "evaluation_examples/examples" / domain
                             / f"{task_id}.json").read_text())
        controller = PythonController(vm_ip=desktop.ip, server_port=5000)
        setup = SetupController(vm_ip=desktop.ip, server_port=5000, chromium_port=9222,
                                vlc_port=8080, cache_dir=str(args.output / "cache"),
                                client_password="password", screen_width=1920,
                                screen_height=1080, os_type="Ubuntu")
        cache = args.output / "cache" / f"{task_id}-{desktop.index}"
        cache.mkdir(parents=True, exist_ok=True)
        setup.reset_cache_dir(str(cache))
        begin = time.monotonic_ns()
        record["setup_ok"] = bool(setup.setup(config.get("config", []), False))
        record["setup_ns"] = time.monotonic_ns() - begin
        if not record["setup_ok"]:
            raise RuntimeError("task setup failed")
        fake = types.SimpleNamespace(resize_factor=(1920 / 1280, 1080 / 720))
        convert = lambda call: AnthropicAgent.parse_actions_from_tool_call(fake, call)
        steps = load_steps(traj)[:args.max_steps]
        record["replay_begin_ns"] = time.monotonic_ns() - epoch_ns
        for step in steps:
            row = {"step": step["step"], "recorded_gap_s": step["recorded_gap_s"]}
            command = to_command(step["action"], convert)
            row["kind"] = (command if command in ("DONE", "FAIL", "WAIT")
                           else "none" if command is None else "command")
            start = time.monotonic_ns()
            row["action_begin_ns"] = start - epoch_ns
            if row["kind"] == "command":
                reply = controller.execute_python_command(command)
                row["exec_ok"] = bool(reply) and reply.get("status") != "error"
            shot_begin = time.monotonic_ns()
            shot = desktop.screenshot()
            now = time.monotonic_ns()
            row["exec_ns"], row["shot_ns"] = shot_begin - start, now - shot_begin
            row["screenshot_bytes"] = len(shot)
            if step["recorded_gap_s"] is None:
                record["steps"].append(row)
                break
            deadline = start + int(step["recorded_gap_s"] * args.wait_scale * 1e9)
            if args.policy != "always":
                settle_until = now + int(args.settle * 1e9)
                if settle_until < deadline - int(args.min_frozen * 1e9):
                    time.sleep((settle_until - time.monotonic_ns()) / 1e9)
                    row["freeze_ns"] = set_frozen(desktop.directory, True)
                    row["frozen_at_ns"] = time.monotonic_ns() - epoch_ns
                    if args.policy == "freeze-reclaim":
                        row["reclaim"] = reclaim(desktop.directory)
            remaining = (deadline - time.monotonic_ns()) / 1e9
            if remaining > 0:
                time.sleep(remaining)
            if "freeze_ns" in row:
                row["thaw_ns"] = set_frozen(desktop.directory, False)
                row["thawed_at_ns"] = time.monotonic_ns() - epoch_ns
            record["steps"].append(row)
        (args.output / f"final-{desktop.index}.png").write_bytes(shot)
    except Exception as exc:  # keep the other instances running
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if desktop.directory and "freeze" in args.policy:
            try:
                set_frozen(desktop.directory, False)
            except (OSError, TimeoutError):
                pass
        record["end_ns"] = time.monotonic_ns() - epoch_ns
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pilot", type=Path, required=True,
                        help="JSON {domain: {traj: path}} from the trajectory selection")
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--policy", choices=("always", "freeze", "freeze-reclaim"),
                        default="always")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="ghcr.io/cua-lite/lite.osworld:latest")
    parser.add_argument("--docker-arg", action="append", default=[],
                        help="Extra docker run argument (repeatable), e.g. --docker-arg=--runtime=runsc")
    parser.add_argument("--osworld", type=Path, default=Path.home() / "agent-experiments/OSWorld")
    parser.add_argument("--stagger", type=float, default=20.0, help="Seconds between instance starts")
    parser.add_argument("--settle", type=float, default=10.0,
                        help="Seconds after an action before freezing")
    parser.add_argument("--min-frozen", type=float, default=2.0,
                        help="Skip the freeze when it would last less than this")
    parser.add_argument("--wait-scale", type=float, default=1.0)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--ready-timeout", type=float, default=600)
    parser.add_argument("--host-interval", type=float, default=0.5)
    parser.add_argument("--process-interval", type=float, default=0.5,
                        help="Per-process sampling period for every container (0: off)")
    parser.add_argument("--pss-interval", type=float, default=30.0)
    parser.add_argument("--prefix", default="swarm")
    parser.add_argument("--keep", action="store_true", help="Leave containers running at the end")
    args = parser.parse_args()

    sys.path[:0] = [str(args.osworld), str(REPO)]
    stub_modules()
    pilot = json.loads(args.pilot.read_text())
    trajs = [v["traj"] for v in pilot.values()]
    args.output.mkdir(parents=True)
    desktops = [Desktop(i, args) for i in range(args.n)]
    epoch = time.monotonic_ns()
    result = {"config": {k: str(v) for k, v in vars(args).items()},
              "image_id": docker("image", "inspect", "-f", "{{.Id}}", args.image).stdout.strip(),
              "kernel": os.uname().release, "cpus": os.cpu_count(), "epoch_ns": epoch,
              "mem_before": read_meminfo()}
    try:
        with Profiler(args.host_interval, args.pss_interval, args.output / "samples.jsonl",
                      args.process_interval, args.output / "procs.jsonl") as prof:
            with ThreadPoolExecutor(max_workers=args.n) as pool:
                futures = [pool.submit(replay, d, trajs[d.index % len(trajs)], args, prof, epoch)
                           for d in desktops]
                result["instances"] = [f.result() for f in futures]
            result["wall_ns"] = time.monotonic_ns() - epoch
        result["profiler"] = prof.summary()
    finally:
        if not args.keep:
            for d in desktops:
                d.remove()
        result["mem_after"] = read_meminfo()
        (args.output / "result.json").write_text(json.dumps(result, indent=1))
    errors = [r for r in result.get("instances", []) if "error" in r]
    print(f"{args.n} desktops, policy {args.policy}: {len(errors)} errors -> {args.output}")


if __name__ == "__main__":
    main()
