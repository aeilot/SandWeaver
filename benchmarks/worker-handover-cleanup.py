#!/usr/bin/env python3
"""Measure synchronous versus deferred write-layer deletion on one warm worker."""
import argparse
import json
from pathlib import Path
import shlex
import statistics
import tempfile
import time
from unittest.mock import patch

from sandweaver import scheduler

CREATE_STATE = """
import os
from pathlib import Path
import socket
import sys

count, size = map(int, sys.argv[1:])
state = Path("/tmp/handover")
state.mkdir()
payload = b"x" * size
for index in range(count):
    (state / str(index)).write_bytes(payload)
Path("/workspace/previous").write_text("A")
server = socket.socket()
server.bind(("127.0.0.1", 0))
server.listen()
if os.fork() == 0:
    for fd in (0, 1, 2):
        os.close(fd)
    while True:
        connection, _ = server.accept()
        with connection:
            connection.sendall(b"A")
with socket.create_connection(server.getsockname(), timeout=1) as connection:
    assert connection.recv(1) == b"A"
print(server.getsockname()[1])
"""

VERIFY_STATE = """
from pathlib import Path
import socket
import sys
import humanize

assert humanize.intcomma(1000) == "1,000"
assert not Path("/tmp/handover").exists()
assert not Path("/workspace/previous").exists()
with socket.socket() as connection:
    connection.settimeout(1)
    assert connection.connect_ex(("127.0.0.1", int(sys.argv[1]))) != 0
"""

DELETE_TASK = """
        # Both arms detach the old generation before publishing worker availability.
        mv /state/task /state/reclaim
        collect() {
            started=$(date +%s%N)
            rm -rf /state/reclaim || return 1
            finished=$(date +%s%N)
            echo "$((finished - started))" > /state/reclaim-ns.tmp
            mv /state/reclaim-ns.tmp /state/reclaim-ns
        }
"""


def reset_script(deferred):
    cleanup = "collect </dev/null >/dev/null 2>&1 &" if deferred else "collect"
    return scheduler.RESET.replace("rm -rf /state/task", DELETE_TASK + "        " + cleanup)


def execute(worker, program, *args):
    command = shlex.join(["/project/.venv/bin/python", "-B", "-c", program, *map(str, args)])
    return scheduler.docker("exec", worker.name, "/bin/sh", "-ec", scheduler.EXEC,
                            "exec", command).stdout.strip()


def measure(pool, root, count, size, deferred):
    a = pool.acquire(root / "a")
    port = execute(a, CREATE_STATE, count, size)

    start = time.perf_counter_ns()
    with patch.object(scheduler, "RESET", reset_script(deferred)):
        pool.release(a)
    released = time.perf_counter_ns()
    if a not in pool.workers or a.retiring:
        raise RuntimeError("Reset failed; worker was retired")

    b = pool.acquire(root / "b")
    ready = time.perf_counter_ns()
    if a is not b:
        raise RuntimeError("Handover did not reuse the same worker")
    execute(b, VERIFY_STATE, port)
    verified = time.perf_counter_ns()

    # Drain after B's first command, so each trial starts without a cleanup backlog.
    cleanup = scheduler.docker(
        "exec", b.name, "/bin/sh", "-ec",
        'until test -f /state/reclaim-ns; do sleep .01; done; '
        'test ! -e /state/reclaim; cat /state/reclaim-ns; rm /state/reclaim-ns',
        timeout=10,
    )
    if (root / "a" / "previous").read_text() != "A":
        raise RuntimeError("A's persistent workspace was not preserved")
    pool.release(b)
    if b not in pool.workers or b.retiring:
        raise RuntimeError("B's reset failed; worker was retired")
    return {
        "release_ms": (released - start) / 1e6,
        "b_claim_ms": (ready - released) / 1e6,
        "handover_ms": (verified - start) / 1e6,
        "delete_ms": int(cleanup.stdout) / 1e6,
    }


def summarize(rows):
    summary = {}
    for key in rows[0]:
        values = sorted(row[key] for row in rows)
        summary[key] = {
            "p50": statistics.median(values),
            "p95": values[(95 * len(values) + 99) // 100 - 1],
        }
    return summary


def run(image, rounds):
    workloads = {"minimal": (0, 0), "small_files": (8192, 4096), "large_files": (4, 8 << 20)}
    result = {
        "docker": scheduler.docker(
            "info", "--format", "{{.OSType}}/{{.Architecture}} {{.OperatingSystem}}"
        ).stdout.strip(),
        "image": image,
        "rounds_per_arm": rounds,
        "warmup_per_arm_per_workload": 1,
        "workloads": {},
    }
    with tempfile.TemporaryDirectory(prefix="sandweaver-handover-") as directory:
        scratch = Path(directory).resolve()
        root = scratch / "workspaces"
        (root / "a").mkdir(parents=True)
        (root / "b").mkdir()
        started = time.perf_counter_ns()
        pool = scheduler.Pool(image, root, 1, 1, 60, scratch)
        result["worker_setup_ms"] = (time.perf_counter_ns() - started) / 1e6
        result["image_id"] = pool.image
        try:
            for name, (count, size) in workloads.items():
                samples = {"synchronous": [], "deferred": []}
                for index in range(rounds + 1):
                    order = tuple(samples) if index % 2 == 0 else tuple(reversed(samples))
                    for arm in order:
                        row = measure(pool, root, count, size, arm == "deferred")
                        if index:
                            samples[arm].append(row)
                result["workloads"][name] = {
                    "files": count,
                    "bytes_per_file": size,
                    "summary_ms": {arm: summarize(rows) for arm, rows in samples.items()},
                    "samples": samples,
                }
        finally:
            pool.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=scheduler.DEFAULT_IMAGE)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    if options.rounds < 1:
        parser.error("--rounds must be positive")
    data = json.dumps(run(options.image, options.rounds), indent=2) + "\n"
    if options.output:
        options.output.write_text(data)
    else:
        print(data, end="")
