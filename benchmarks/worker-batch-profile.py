#!/usr/bin/env python3
"""Profile deterministic tool batches over SandWeaver's local scheduler socket."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import shlex
import shutil
import statistics
import tempfile
import threading
import time
from unittest.mock import patch

from sandweaver import scheduler

PYTHON = "/project/.venv/bin/python"
START_SERVICE = """
import os
import socket

server = socket.socket()
server.bind(("127.0.0.1", 0))
server.listen()
if os.fork() == 0:
    for fd in (0, 1, 2):
        os.close(fd)
    while True:
        client, _ = server.accept()
        with client:
            client.sendall(b"ready")
print(server.getsockname()[1])
"""
CHECK_SERVICE = """
import socket
import sys

with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=1) as client:
    assert client.recv(5) == b"ready"
"""
CACHE_IMPORTS = """
import time

started = time.perf_counter_ns()
import asyncio
import http.client
import json
import logging.config
import urllib.request
import humanize

assert humanize.intcomma(1000) == "1,000"
print(time.perf_counter_ns() - started)
"""


def python_command(program, *args):
    return shlex.join([PYTHON, "-B", "-c", program, *args])


def ms(start, end):
    return (end - start) / 1e6


def timed_request(client, op, **fields):
    started = time.monotonic_ns()
    reply = client.request(op, **fields)
    return reply, ms(started, time.monotonic_ns())


def execute(client, command, expected_code=0):
    reply, elapsed = timed_request(client, "exec", command=command, observe=True)
    if reply["exit_code"] != expected_code:
        raise RuntimeError(f"Expected exit {expected_code}: {reply['stderr']}")
    return reply["stdout"].strip(), elapsed, reply["timing"]["exec_ns"] / 1e6


@contextmanager
def serve(socket_path, pool):
    with scheduler.Server(str(socket_path), scheduler.Handler) as server:
        server.pool = pool
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join()


def state_profile(socket_path, root):
    workspace = root / "state"
    blocker = root / "blocker"
    with scheduler.connect(socket_path) as session, scheduler.connect(socket_path) as other:
        first = session.request("claim", workspace=str(workspace))["worker"]
        execute(session, "mkdir -p .session/deps /tmp/profile-deps && "
                "printf 'VALUE = 42\\n' > .session/deps/profile_dep.py && "
                "cp .session/deps/profile_dep.py /tmp/profile-deps/ && "
                "printf 'ok\\n' > result")
        port, _, _ = execute(session, python_command(START_SERVICE))
        module = python_command("import profile_dep; assert profile_dep.VALUE == 42")
        execute(session, f"PYTHONPATH=/tmp/profile-deps {module}")
        execute(session, python_command(CHECK_SERVICE, port))
        session.request("release")

        # Occupy the original worker so the same session must resume elsewhere.
        claimed = other.request("claim", workspace=str(blocker))["worker"]
        resumed = session.request("claim", workspace=str(workspace))["worker"]
        if claimed != first or resumed == first:
            raise RuntimeError("State profile did not switch workers")
        execute(session, 'test "$(cat result)" = ok && test ! -e /tmp/profile-deps')
        execute(session, f"PYTHONPATH=/workspace/.session/deps {module}")
        no_listener = python_command(
            'import socket, sys; '
            's = socket.socket(); s.settimeout(1); '
            'assert s.connect_ex(("127.0.0.1", int(sys.argv[1]))) != 0', port)
        execute(session, no_listener)
        # Also check the original worker after its reset, where A's port lived.
        execute(other, "test ! -e /tmp/profile-deps")
        execute(other, no_listener)
        session.request("release")
        other.request("release")
    return {
        "switched_worker": True,
        "workspace_file_bytes": (workspace / "result").stat().st_size,
        "retained_dependency_bytes": (workspace / ".session/deps/profile_dep.py").stat().st_size,
        "private_dependency_lost": True,
        "original_listener_gone": True,
    }


def wait_until(deadline):
    time.sleep(max(0, (deadline - time.monotonic_ns()) / 1e9))


def claim(client, workspace):
    reply, elapsed = timed_request(client, "claim", workspace=str(workspace), observe=True)
    queue = reply["timing"]["pool_wait_ns"] / 1e6
    server = reply["timing"]["claim_ns"] / 1e6
    timing = reply["timing"]
    return reply["worker"], {
        "claim_ms": elapsed,
        "queue_ms": queue,
        "prepare_ms": server - queue,
        "start_exec_ms": timing["start_exec_ns"] / 1e6,
        "readiness_ms": timing["readiness_ns"] / 1e6,
        "readiness_exec_ms": timing["readiness_exec_ns"] / 1e6,
        "readiness_attempts": timing["readiness_attempts"],
    }


def trial(socket_path, root, policy, wait_ms, stagger_ms):
    # Finish both first batches before starting the simulated model waits.
    barrier = threading.Barrier(3, timeout=15)

    def agent(index):
        workspace = root / f"agent-{index}"
        with scheduler.connect(socket_path) as client:
            first, initial_claim = claim(client, workspace)
            _, first_exec, _ = execute(client, "printf 'ready\\n' > result")
            first_done = time.monotonic_ns()
            barrier.wait()
            deadline = first_done + (wait_ms + stagger_ms * index) * 1_000_000
            release_ms = 0.0
            if policy == "batch":
                _, release_ms = timed_request(client, "release")
            wait_until(deadline)
            began = time.monotonic_ns()
            worker = first
            resume_claim = dict.fromkeys(initial_claim, 0)
            if policy == "batch":
                worker, resume_claim = claim(client, workspace)
            _, exec_ms, exec_server_ms = execute(client, 'test "$(cat result)" = ready')
            finished = time.monotonic_ns()
            client.request("release")
            return deadline, {
                "first_exec_ms": first_exec,
                "configured_wait_ms": wait_ms + stagger_ms * index,
                "release_ms": release_ms,
                "ready_lateness_ms": ms(deadline, began),
                **resume_claim,
                "exec_ms": exec_ms,
                "exec_server_ms": exec_server_ms,
                "ready_to_completion_ms": ms(deadline, finished),
                "first_batch_to_completion_ms": ms(first_done, finished),
                "changed_worker": worker != first,
            }

    def probe():
        with scheduler.connect(socket_path) as client:
            barrier.wait()
            time.sleep(0.05)
            started = time.monotonic_ns()
            _, claim_timing = claim(client, root / "probe")
            _, exec_ms, _ = execute(client, "true")
            finished = time.monotonic_ns()
            client.request("release")
            return {**claim_timing,
                    "exec_ms": exec_ms, "completion_ms": ms(started, finished)}

    with ThreadPoolExecutor(max_workers=3) as executor:
        agents = [executor.submit(agent, index) for index in range(2)]
        short_task = executor.submit(probe)
        first, second = [future.result() for future in agents]
        return {"ready_gap_ms": abs(ms(first[0], second[0])),
                "agents": [first[1], second[1]], "probe": short_task.result()}


def summarize(rows):
    result = {}
    for key in rows[0]:
        values = sorted(row[key] for row in rows)
        if isinstance(values[0], bool):
            result[key] = sum(values)
        else:
            result[key] = {"p50": statistics.median(values),
                           "p95": values[(95 * len(values) + 99) // 100 - 1]}
    return result


def cache_files(path):
    files = {}
    for item in path.rglob("*.pyc"):
        info = item.stat()
        files[item.relative_to(path)] = (info.st_size, info.st_mtime_ns)
    return files


def cache_profile(socket_path, root, rounds):
    workspace = root / "cache"
    samples = {"retained": [], "rebuild": []}

    def imports(client, cache):
        command = shlex.join([PYTHON, "-c", CACHE_IMPORTS])
        out, elapsed, server = execute(client, f"PYTHONPYCACHEPREFIX=/workspace/{cache} {command}")
        return {"imports_ms": int(out) / 1e6, "exec_ms": elapsed, "exec_server_ms": server}

    with scheduler.connect(socket_path) as session, scheduler.connect(socket_path) as blocker:
        for index in range(rounds + 1):
            for cache in samples:
                path = workspace / cache
                if path.exists():
                    shutil.rmtree(path)
            first, _ = claim(session, workspace)
            imports(session, "retained")
            session.request("release")
            old, _ = claim(blocker, root / "blocker")
            second, _ = claim(session, workspace)
            if old != first or first == second:
                raise RuntimeError("Cache profile did not switch workers")
            seeded = cache_files(workspace / "retained")
            order = tuple(samples) if index % 2 == 0 else tuple(reversed(samples))
            for cache in order:
                row = imports(session, cache)
                files = cache_files(workspace / cache)
                if not files or files.keys() != seeded.keys():
                    raise RuntimeError("Cache file sets did not match the seeded cache")
                if cache == "retained" and files != seeded:
                    raise RuntimeError("Retained cache was rewritten")
                if index:
                    samples[cache].append({
                        **row, "files": len(files), "bytes": sum(size for size, _ in files.values())
                    })
            session.request("release")
            blocker.request("release")
    return {"rounds_per_arm": rounds, "warmup_per_arm": 1, "samples": samples,
            "summary": {arm: summarize(rows) for arm, rows in samples.items()}}


def rust_fixture(workspace):
    dependencies = [f"lib{index}" for index in range(6)]
    manifest = ('[package]\nname = "app"\nversion = "0.1.0"\nedition = "2021"\n'
                '\n[dependencies]\n')
    manifest += "".join(f'{name} = {{ path = "{name}" }}\n' for name in dependencies)
    (workspace / "Cargo.toml").write_text(manifest)
    for name in dependencies:
        crate = workspace / name
        (crate / "src").mkdir(parents=True)
        (crate / "Cargo.toml").write_text(
            f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n')
        functions = "\n".join(
            f"fn f{index}(n: u64) -> u64 {{ n.rotate_left({index % 64}) ^ {index} }}"
            for index in range(128)
        )
        calls = " ^ ".join(f"f{index}(n)" for index in range(128))
        (crate / "src/lib.rs").write_text(
            f"{functions}\npub fn checksum(n: u64) -> u64 {{ {calls} }}\n")
    (workspace / "src").mkdir()
    calls = " ^ ".join(f"{name}::checksum(42)" for name in dependencies)
    return f'fn main() {{ let checksum = {calls}; println!("{{}} {{}}", checksum, REVISION); }}\n'


def rust_cache_profile(socket_path, root, rounds):
    workspace = root / "cache"
    source = workspace / "src/main.rs"
    main = rust_fixture(workspace)
    samples = {"retained": [], "rebuild": []}
    cargo = "/usr/local/cargo/bin/cargo"

    def build(client, target, revision):
        command = (f"CARGO_TARGET_DIR=/workspace/{target} CARGO_INCREMENTAL=1 "
                   f"{cargo} build --offline --jobs 2 --verbose 2>&1")
        log, elapsed, server = execute(client, command)
        output, _, _ = execute(client, f"/workspace/{target}/debug/app")
        if output.split()[-1:] != [str(revision)]:
            raise RuntimeError("Build did not produce the requested revision")
        return {"build_ms": elapsed, "build_server_ms": server,
                "compiled_crates": sum(line.lstrip().startswith("Compiling ") for line in log.splitlines()),
                "fresh_crates": sum(line.lstrip().startswith("Fresh ") for line in log.splitlines())}

    with scheduler.connect(socket_path) as session, scheduler.connect(socket_path) as blocker:
        for index in range(rounds + 1):
            for target in samples:
                path = workspace / target
                if path.exists():
                    shutil.rmtree(path)
            source.write_text(main + "const REVISION: u64 = 0;\n")
            first, _ = claim(session, workspace)
            versions, _, _ = execute(session, f"{cargo} --version && /usr/local/cargo/bin/rustc --version")
            build(session, "retained", 0)
            session.request("release")
            cache_sizes = [item.stat().st_size for item in (workspace / "retained").rglob("*")
                           if item.is_file()]
            source.write_text(main + "const REVISION: u64 = 1;\n")
            old, _ = claim(blocker, root / "blocker")
            second, _ = claim(session, workspace)
            if old != first or first == second:
                raise RuntimeError("Rust cache profile did not switch workers")
            order = tuple(samples) if index % 2 == 0 else tuple(reversed(samples))
            for target in order:
                row = build(session, target, 1)
                expected = (1, 6) if target == "retained" else (7, 0)
                if (row["compiled_crates"], row["fresh_crates"]) != expected:
                    raise RuntimeError(f"Unexpected Cargo cache behavior in {target}: {row}")
                if index:
                    samples[target].append(row)
            session.request("release")
            blocker.request("release")
            if index:
                samples["retained"][-1].update(seed_files=len(cache_sizes), seed_bytes=sum(cache_sizes))
    return {"toolchain": versions.splitlines(), "jobs": 2, "crates": 7,
            "lease_procfs": "mounted in the Rust benchmark PID namespace",
            "rounds_per_arm": rounds, "warmup_per_arm": 1, "samples": samples,
            "summary": {arm: summarize(rows) for arm, rows in samples.items()}}


def run(image, rounds, rust_cache=False):
    host = scheduler.docker("info", "--format",
                            "{{.OSType}}/{{.Architecture}} {{.OperatingSystem}}").stdout.strip()
    result = {"docker": host, "image": image, "workers": 2, "rounds": rounds,
              "warmup_per_arm": 1}
    # A short directory keeps the Unix socket path within Darwin's limit.
    with tempfile.TemporaryDirectory(prefix="sw-profile-", dir="/tmp") as directory:
        scratch = Path(directory)
        root = scratch.resolve() / "workspaces"
        root.mkdir()
        for name in ("state", "blocker", "agent-0", "agent-1", "probe", "cache"):
            (root / name).mkdir()
        start = time.monotonic_ns()
        pool = scheduler.Pool(image, root, 2, 2, 60, scratch)
        result.update(image_id=pool.image, pool_setup_ms=ms(start, time.monotonic_ns()))
        socket_path = scratch / "scheduler.sock"
        try:
            with serve(socket_path, pool):
                if rust_cache:
                    # The Rust toolchain uses /proc/self/exe. Mount proc from the
                    # new PID namespace's init, before it becomes the sleep anchor.
                    anchor = '/bin/sleep infinity </dev/null'
                    proc_anchor = ('/bin/sh -ec "mount -t proc -o nosuid,nodev,noexec '
                                   'proc /proc; exec /bin/sleep infinity" </dev/null')
                    start_script = scheduler.START.replace(anchor, proc_anchor)
                    if start_script == scheduler.START:
                        raise RuntimeError("Could not configure procfs for the Rust benchmark")
                    with patch.object(scheduler, "START", start_script):
                        result["rust_cache_profile"] = rust_cache_profile(socket_path, root, rounds)
                    return result
                result.update(probe_delay_after_barrier_ms=50, scenarios=[])
                result["state_profile"] = state_profile(socket_path, root)
                result["cache_profile"] = cache_profile(socket_path, root, rounds)
                for wait_ms, stagger_ms in ((150, 0), (830, 0), (830, 250)):
                    samples = {"session": [], "batch": []}
                    for index in range(rounds + 1):
                        arms = tuple(samples) if index % 2 == 0 else tuple(reversed(samples))
                        for policy in arms:
                            row = trial(socket_path, root, policy, wait_ms, stagger_ms)
                            if index:
                                samples[policy].append(row)
                    result["scenarios"].append({
                        "wait_ms": wait_ms, "stagger_ms": stagger_ms, "samples": samples,
                        "summary": {
                            policy: {
                                "agents": summarize([agent for row in rows for agent in row["agents"]]),
                                "probe": summarize([row["probe"] for row in rows]),
                            } for policy, rows in samples.items()
                        },
                    })
        finally:
            pool.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=scheduler.DEFAULT_IMAGE)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--rust-cache", action="store_true",
                        help="Run only the Cargo target-directory experiment with a Rust image")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    args.output.write_text(json.dumps(run(args.image, args.rounds, args.rust_cache), indent=2) + "\n")
