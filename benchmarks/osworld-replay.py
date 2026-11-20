#!/usr/bin/env python3
"""Replay a public OSWorld trajectory in the official Ubuntu VM and sample the VM's resources.

No model is called. The task's own setup config initialises the VM; then each
recorded action is executed and the replay sleeps so that step starts keep the
recorded spacing (the recorded gap minus the time this replay spent executing
the action and taking the screenshot). The VM runs in OSWorld's QEMU container
(`happysixd/osworld-docker`), and sandweaver.sampler samples that container's
cgroup from the host, so QEMU's CPU, memory and I/O are attributed to waits
and actions separately. Each step's screenshot size is recorded, as an agent
would transfer it.

Runs with an environment that has OSWorld's lean host dependencies (requests,
websocket-client, playwright, requests-toolbelt, python-dotenv, psutil, docker,
filelock, pydrive, pyautogui, anthropic, pillow); heavy OSWorld modules that
the replay does not use are stubbed. Replay is blind: if the UI drifts from the
recording, later clicks land elsewhere; compare the final screenshot or run
OSWorld's evaluator separately.
"""
import argparse
import ast
import base64
import gzip
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
import types

REPO = Path(__file__).resolve().parents[1]


def stub_modules():
    """Provide the few names the OSWorld modules import but the replay never uses."""
    os.environ.setdefault("DISPLAY", ":0")
    if "pyautogui" not in sys.modules:
        # Host-side pyautogui needs an X display; OSWorld only patches one attribute.
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


def stamp(text):
    return datetime.strptime(text, "%Y%m%d@%H%M%S%f").timestamp()


def load_steps(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    rows.sort(key=lambda r: int(r["step_num"]))
    times = [stamp(r["action_timestamp"]) for r in rows]
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
    """Recorded action -> python command for the VM, or a special action name."""
    if isinstance(action, str):
        return action
    if not isinstance(action, dict):
        return None
    if action.get("action_type") in ("DONE", "FAIL", "WAIT"):
        return action["action_type"]
    # OSWorld's runner stores the pyautogui command it actually executed; prefer it
    # over re-deriving one with the current converter.
    if action.get("command"):
        return action["command"]
    if action.get("name") == "computer":
        return converter(action) or None
    return None


class GuestProcs:
    """Run sandweaver/procs.py inside the guest as root and fetch its samples.

    The guest's clocks differ from the host's, so `probe` reads the guest's
    CLOCK_REALTIME between two host monotonic readings; the midpoint maps guest
    wall time to host monotonic time with an error of at most half the round trip.
    """

    def __init__(self, host, port, password, interval):
        import requests
        self.requests, self.url = requests, f"http://{host}:{port}/execute"
        self.password, self.interval = password, interval

    def shell(self, command, timeout=120):
        reply = self.requests.post(self.url, timeout=timeout,
                                   json={"command": command, "shell": True}).json()
        return reply.get("output") or ""

    def probe(self):
        before = time.monotonic_ns()
        guest = int(self.shell("date +%s%N").strip())
        after = time.monotonic_ns()
        return {"host_before_ns": before, "host_after_ns": after, "guest_wall_ns": guest}

    def start(self):
        source = base64.b64encode((REPO / "sandweaver/procs.py").read_bytes()).decode()
        self.shell(f"echo {source} | base64 -d > /tmp/sw-procs.py")
        self.shell(f"echo {self.password} | sudo -S sh -c 'nohup python3 /tmp/sw-procs.py "
                   f"--interval {self.interval} --io --out /tmp/sw-procs.jsonl "
                   f">/tmp/sw-procs.err 2>&1 &'")

    def stop(self, path):
        self.shell(f"echo {self.password} | sudo -S pkill -TERM -f sw-procs.py; sleep 1")
        data = self.shell("gzip -c /tmp/sw-procs.jsonl | base64 -w0", timeout=600)
        raw = gzip.decompress(base64.b64decode(data)) if data.strip() else b""
        path.write_bytes(raw)
        return {"bytes": len(raw), "lines": raw.count(b"\n"),
                "stderr": self.shell("cat /tmp/sw-procs.err")[-2000:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("traj", type=Path, help="traj.jsonl; its directory name is the task id")
    parser.add_argument("--osworld", type=Path, default=Path.home() / "agent-experiments/OSWorld")
    parser.add_argument("--vm", type=Path, required=True, help="Ubuntu.qcow2")
    parser.add_argument("--output", type=Path, required=True, help="Run directory to create")
    parser.add_argument("--sample", type=float, default=0.1)
    parser.add_argument("--wait-scale", type=float, default=1.0)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--guest-procs", type=float, default=0.25, metavar="SECONDS",
                        help="Per-process sampling period inside the guest (0: off)")
    parser.add_argument("--idle-tail", type=float, default=0,
                        help="Seconds to keep the VM idle after the last step, sampled")
    args = parser.parse_args()

    sys.path[:0] = [str(args.osworld), str(REPO)]
    stub_modules()
    from desktop_env.controllers.python import PythonController
    from desktop_env.controllers.setup import SetupController
    from desktop_env.providers.docker.provider import DockerProvider
    from mm_agents.anthropic.main import AnthropicAgent
    from sandweaver import sampler

    task_id, domain = args.traj.parent.name, args.traj.parent.parent.name
    config = json.loads((args.osworld / "evaluation_examples/examples" / domain
                         / f"{task_id}.json").read_text())
    steps = load_steps(args.traj)[:args.max_steps]
    # OSWorld's Claude agent maps 1280x720 model coordinates to the 1920x1080 screen.
    fake = types.SimpleNamespace(resize_factor=(1920 / 1280, 1080 / 720))
    convert = lambda call: AnthropicAgent.parse_actions_from_tool_call(fake, call)

    args.output.mkdir(parents=True)
    result = {"task_id": task_id, "domain": domain, "traj": str(args.traj),
              "wait_scale": args.wait_scale, "recorded_steps": len(steps), "steps": []}
    provider = DockerProvider(None)
    begin = time.monotonic_ns()
    provider.start_emulator(str(args.vm), True, "Ubuntu")
    try:
        result["boot_ns"] = time.monotonic_ns() - begin
        host, server, chromium, vnc, vlc = provider.get_ip_address(str(args.vm)).rsplit(":", 4)
        container = provider.container.name
        result["container"] = container
        with sampler.Sampler(container, args.sample) as sampled:
            controller = PythonController(vm_ip=host, server_port=int(server))
            setup = SetupController(vm_ip=host, server_port=int(server),
                                    chromium_port=int(chromium), vlc_port=int(vlc),
                                    cache_dir=str(args.output / "cache"), client_password="password",
                                    screen_width=1920, screen_height=1080, os_type="Ubuntu")
            # DesktopEnv creates the per-task cache directory that downloads land in.
            cache = args.output / "cache" / task_id
            cache.mkdir(parents=True, exist_ok=True)
            setup.reset_cache_dir(str(cache))
            guest = None
            if args.guest_procs:
                guest = GuestProcs(host, server, "password", args.guest_procs)
                try:
                    guest.start()
                    result["guest_probe_start"] = guest.probe()
                except (ValueError, OSError, guest.requests.RequestException) as exc:
                    result["guest_procs_error"] = f"start: {exc}"
                    guest = None
            begin = time.monotonic_ns()
            result["setup_ok"] = bool(setup.setup(config.get("config", []), False))
            result["setup_ns"] = time.monotonic_ns() - begin
            if not result["setup_ok"]:
                raise RuntimeError("Task setup failed; not replaying")
            shot = controller.get_screenshot() or b""
            result["initial_screenshot_bytes"] = len(shot)
            for step in steps:
                record = {"step": step["step"], "recorded_gap_s": step["recorded_gap_s"]}
                command = to_command(step["action"], convert)
                record["kind"] = (command if command in ("DONE", "FAIL", "WAIT")
                                  else "none" if command is None else "command")
                record["action_begin_ns"] = time.monotonic_ns()
                if record["kind"] == "command":
                    controller.execute_python_command(command)
                shot = controller.get_screenshot() or b""
                record["action_ns"] = time.monotonic_ns() - record["action_begin_ns"]
                record["screenshot_bytes"] = len(shot)
                if step["recorded_gap_s"] is not None:
                    wait = max(0.0, step["recorded_gap_s"] * args.wait_scale
                               - record["action_ns"] / 1e9)
                    record["wait_begin_ns"] = time.monotonic_ns()
                    time.sleep(wait)
                    record["wait_ns"] = time.monotonic_ns() - record["wait_begin_ns"]
                result["steps"].append(record)
                print(f"step {step['step']}/{len(steps)} {record['kind']} "
                      f"action={record['action_ns'] / 1e9:.2f}s shot={len(shot)}", flush=True)
            (args.output / "final.png").write_bytes(shot)
            if args.idle_tail:
                result["idle_tail_begin_ns"] = time.monotonic_ns()
                time.sleep(args.idle_tail)
                result["idle_tail_ns"] = time.monotonic_ns() - result["idle_tail_begin_ns"]
                # What the guest is doing while the agent would be waiting: process
                # names and their CPU and memory shares only.
                import requests
                try:
                    reply = requests.post(f"http://{host}:{server}/execute", timeout=60, json={
                        "command": "top -b -n 1 -w 200 | head -25; free -m; uptime",
                        "shell": True}).json()
                    result["guest_top_after_idle"] = reply.get("output") or reply
                except (requests.RequestException, ValueError) as exc:
                    result["guest_top_after_idle"] = f"probe failed: {exc}"
            if guest:
                try:
                    result["guest_probe_end"] = guest.probe()
                    result["guest_procs"] = guest.stop(args.output / "guest-procs.jsonl")
                except (ValueError, OSError, guest.requests.RequestException) as exc:
                    result["guest_procs_error"] = f"stop: {exc}"
        samples = sampled.samples
        result["sampler"] = sampled.summary()
        for record in result["steps"]:
            record["action_usage"] = sampler.window(samples, record["action_begin_ns"],
                                                    record["action_begin_ns"] + record["action_ns"])
            if "wait_ns" in record:
                record["wait_usage"] = sampler.window(samples, record["wait_begin_ns"],
                                                      record["wait_begin_ns"] + record["wait_ns"])
        if args.idle_tail:
            result["idle_tail_usage"] = sampler.window(
                samples, result["idle_tail_begin_ns"],
                result["idle_tail_begin_ns"] + result["idle_tail_ns"])
        with (args.output / "samples.jsonl").open("w") as handle:
            for sample in samples:
                handle.write(json.dumps(sample) + "\n")
    finally:
        provider.stop_emulator(str(args.vm))
        (args.output / "result.json").write_text(json.dumps(result, indent=1))
    print(f"Result: {args.output / 'result.json'}")


if __name__ == "__main__":
    main()
