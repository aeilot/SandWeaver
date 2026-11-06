#!/usr/bin/env python3
"""Compare per-task OverlayFS views with fresh Docker containers on a warm image."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
import uuid

IMAGE = "openhands-pool-cache/python-data-humanize:demo"
PYTHON = "/project/.venv/bin/python"

FIXTURE = """
import json, os, socket, sys
from pathlib import Path
import humanize

paths = [Path('/workspace/previous'), Path('/tmp/previous'), Path('/root/previous')]
assert humanize.intcomma(1000) == '1,000'
if sys.argv[1] == 'A':
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('A')
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    port = server.getsockname()[1]
    if os.fork() == 0:
        for fd in (0, 1, 2):
            os.close(fd)
        while True:
            conn, _ = server.accept()
            with conn:
                conn.sendall(b'A')
    with socket.create_connection(('127.0.0.1', port), timeout=1) as conn:
        assert conn.recv(1) == b'A'
    print(json.dumps({'port': port}))
else:
    assert not any(path.exists() for path in paths), paths
    with socket.socket() as client:
        client.settimeout(1)
        assert client.connect_ex(('127.0.0.1', int(sys.argv[2]))) != 0
    print(json.dumps({'dependency': humanize.__version__, 'isolated': True}))
"""

NAMESPACE = """
d=$1
shift
mount -t overlay overlay -o "lowerdir=/basis,upperdir=$d/upper,workdir=$d/work" "$d/root"
exec chroot "$d/root" /project/.venv/bin/python -B /fixture.py "$@"
"""

WORKER = """
script=$1
shift
d=$(mktemp -d /state/task.XXXXXX)
trap 'rm -rf "$d"' EXIT
mkdir "$d/upper" "$d/work" "$d/root"
unshare --mount --pid --fork --kill-child --propagation private /bin/sh -ec "$script" task "$d" "$@"
"""


def docker(*args):
    result = subprocess.run(["docker", *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def remove(name):
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def elapsed(start):
    return round((time.perf_counter() - start) * 1000, 2)


def run(rounds):
    prefix = "oh-fs-" + uuid.uuid4().hex[:10]
    worker, seed = prefix + "-worker", prefix + "-seed"
    image_id = docker("image", "inspect", "--format", "{{.Id}}", IMAGE)
    samples = {"fresh_docker": [], "warm_worker": []}
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "fixture.py"
        fixture.write_text(FIXTURE)
        try:
            start = time.perf_counter()
            docker("run", "-d", "--name", worker, "--network", "none",
                   "--cap-add", "SYS_ADMIN", "--security-opt", "seccomp=unconfined",
                   "--tmpfs", "/state:exec", "--entrypoint", "/bin/sh", image_id,
                   "-ec", "mkdir /basis; exec sleep infinity")
            docker("create", "--name", seed, image_id)
            with subprocess.Popen(["docker", "export", seed], stdout=subprocess.PIPE) as export:
                result = subprocess.run(["docker", "exec", "-i", worker, "tar", "-xf", "-", "-C", "/basis"],
                                        stdin=export.stdout, capture_output=True, text=True)
                export.stdout.close()
                if result.returncode or export.wait():
                    raise RuntimeError(f"rootfs export failed: {result.stderr}")
            docker("cp", str(fixture), f"{worker}:/basis/fixture.py")
            remove(seed)
            setup_ms = elapsed(start)
            bind = f"type=bind,src={fixture},dst=/fixture.py,readonly"

            def warm(*args):
                return json.loads(docker("exec", worker, "/bin/sh", "-ec", WORKER,
                                         "worker", NAMESPACE, *args))

            def fresh(name, *args):
                return json.loads(docker("run", "--name", name, "--network", "none",
                                         "--mount", bind, "--entrypoint", PYTHON, image_id,
                                         "-B", "/fixture.py", *args))

            for index in range(rounds):
                order = list(samples)[::1 if index % 2 == 0 else -1]
                for arm in order:
                    a, b = prefix + "-a", prefix + "-b"
                    try:
                        if arm == "warm_worker":
                            start = time.perf_counter()
                            result = warm("A")
                            a_ms = elapsed(start)
                            start = time.perf_counter()
                            proof = warm("B", str(result["port"]))
                            ready_ms = elapsed(start)
                        else:
                            start = time.perf_counter()
                            result = fresh(a, "A")
                            a_ms = elapsed(start)
                            start = time.perf_counter()
                            docker("rm", a)
                            proof = fresh(b, "B", str(result["port"]))
                            ready_ms = elapsed(start)
                        assert proof["isolated"]
                        samples[arm].append({"a_ms": a_ms, "handoff_ms": ready_ms, **proof})
                    finally:
                        if arm == "fresh_docker":
                            remove(a)
                            remove(b)
        finally:
            remove(seed)
            remove(worker)
    return {"image": IMAGE, "image_id": image_id, "worker_setup_ms": setup_ms,
            "median_handoff_ms": {arm: statistics.median(row["handoff_ms"] for row in rows)
                                  for arm, rows in samples.items()},
            "samples": samples}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    if options.rounds < 1:
        parser.error("--rounds must be positive")
    data = json.dumps(run(options.rounds), indent=2) + "\n"
    if options.output:
        options.output.write_text(data)
    print(data, end="")
