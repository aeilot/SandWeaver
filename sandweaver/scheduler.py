#!/usr/bin/env python3
"""Local Docker worker pool. Use only trusted tasks and images in this prototype."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import uuid

DEFAULT_IMAGE = "sandweaver-demo:local"
START = r"""
exec >/state/start.log 2>&1
d=/state/task
mkdir "$d"
mkdir "$d/upper" "$d/work" "$d/root"
unshare --mount --propagation private /bin/sh -ec '
    d=/state/task
    mount -t overlay overlay -o lowerdir=/basis,upperdir=$d/upper,workdir=$d/work "$d/root"
    mkdir -p "$d/root/workspace"
    mount --bind "$1" "$d/root/workspace"
    for device in null zero random urandom; do
        touch "$d/root/dev/$device"
        mount --bind "/dev/$device" "$d/root/dev/$device"
    done
    exec unshare --pid /bin/sh -ec "$2"
' lease "$1" '
    d=/state/task
    chroot "$d/root" /bin/sleep infinity </dev/null >/dev/null 2>&1 &
    pid=$!
    echo "$pid" > "$d/pid"
    wait "$pid" || :
    : > "$d/done"
'
"""
EXEC = r"""
read -r pid < /state/task/pid
exec nsenter --target "$pid" --mount --pid --root --wdns=/ -- /usr/bin/setpriv \
    --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs \
    /bin/sh -c 'cd /workspace && exec /bin/sh -c "$1"' command "$1"
"""
RESET = r"""
read -r pid < /state/task/pid
test "$(cat "/proc/$pid/comm")" = sleep
kill -KILL "$pid"
for i in $(seq 1 100); do
    if test -e /state/task/done && ! test -e "/proc/$pid"; then
        rm -rf /state/task
        exit 0
    fi
    sleep .02
done
exit 1
"""


def docker(*args, check=True, stdin=None, timeout=60):
    result = subprocess.run(["docker", *args], stdin=stdin, capture_output=True,
                            text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"docker {args[0]}: {result.stderr.strip()}")
    return result


@dataclass
class Worker:
    name: str
    idle_since: float
    workspace: Path | None = None
    retiring: bool = False


class Pool:
    def __init__(self, image, root, minimum, maximum, idle_seconds, directory):
        self.root, self.minimum, self.maximum = root, minimum, maximum
        self.idle_seconds = idle_seconds
        self.image = docker("image", "inspect", "--format", "{{.Id}}", image).stdout.strip()
        self.archive = directory / "basis.tar"
        self.prefix = "sandweaver-" + uuid.uuid4().hex[:10]
        seed = self.prefix + "-seed"
        self.workers = []
        self.lock = threading.Condition()
        self.stop = threading.Event()
        docker("create", "--name", seed, self.image)
        try:
            with self.archive.open("wb") as archive:
                subprocess.run(["docker", "export", seed], stdout=archive,
                               check=True, timeout=120)
        finally:
            docker("rm", "-f", seed, check=False)
        try:
            for _ in range(minimum):
                self.workers.append(self.spawn())
        except BaseException:
            for worker in self.workers:
                self.remove(worker)
            raise
        self.maintainer = threading.Thread(target=self.maintain, daemon=True)
        self.maintainer.start()

    def spawn(self):
        name = self.prefix + "-" + uuid.uuid4().hex[:8]
        worker = Worker(name, time.monotonic())
        try:
            docker("run", "-d", "--name", name, "--network", "none",
                   "--cap-add", "SYS_ADMIN", "--security-opt", "seccomp=unconfined",
                   "--tmpfs", "/state:exec,size=512m", "--mount",
                   f"type=bind,src={self.root},dst=/allowed", "--entrypoint", "/bin/sh",
                   self.image, "-ec", "mkdir /basis; exec sleep infinity")
            with self.archive.open("rb") as archive:
                docker("exec", "-i", name, "tar", "-xf", "-", "-C", "/basis", stdin=archive)
            docker("exec", name, "/bin/sh", "-ec",
                   "test -x /basis/usr/bin/setpriv; command -v nsenter; command -v unshare")
        except BaseException:
            self.remove(worker)
            raise
        worker.idle_since = time.monotonic()
        return worker

    @staticmethod
    def remove(worker):
        return docker("rm", "-f", worker.name, check=False)

    def retire(self, worker):
        # Keep the workspace reserved until Docker confirms the container is gone.
        try:
            if self.remove(worker).returncode:
                remaining = docker("ps", "-aq", "--filter", f"name=^/{worker.name}$")
                if remaining.stdout.strip():
                    return
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            return
        self.workers.remove(worker)
        self.lock.notify_all()

    def maintain(self):
        while not self.stop.wait(.2):
            try:
                with self.lock:
                    for worker in list(self.workers):
                        if worker.retiring:
                            self.retire(worker)
                        elif (len(self.workers) > self.minimum and worker.workspace is None
                                and time.monotonic() - worker.idle_since >= self.idle_seconds):
                            self.remove(worker)
                            self.workers.remove(worker)
                    if len(self.workers) < self.minimum:
                        self.workers.append(self.spawn())
                    self.lock.notify_all()
            except Exception as exc:
                print(f"Pool maintenance: {exc}", flush=True)

    def acquire(self, path):
        workspace = Path(path).resolve(strict=True)
        if not workspace.is_dir() or not workspace.is_relative_to(self.root):
            raise ValueError("Workspace must be a directory under the scheduler workspace root")
        deadline = time.monotonic() + 30
        with self.lock:
            while not self.stop.is_set():
                for current in self.workers:
                    other = current.workspace
                    if other and (workspace.is_relative_to(other) or other.is_relative_to(workspace)):
                        raise RuntimeError("Workspace overlaps an active lease")
                worker = next((w for w in self.workers if w.workspace is None), None)
                if worker is not None:
                    break
                if len(self.workers) < self.maximum:
                    worker = self.spawn()
                    self.workers.append(worker)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Pool is full")
                self.lock.wait(remaining)
            else:
                raise RuntimeError("Pool is shutting down")
            worker.workspace = workspace

        try:
            relative = workspace.relative_to(self.root)
            docker("exec", "-d", worker.name, "/bin/sh", "-ec", START, "start",
                   str(Path("/allowed") / relative))
            until = time.monotonic() + 5
            while time.monotonic() < until:
                result = docker("exec", worker.name, "/bin/sh", "-ec", EXEC, "exec",
                                "true", check=False)
                if result.returncode == 0:
                    return worker
                time.sleep(.04)
            log = docker("exec", worker.name, "cat", "/state/start.log", check=False)
            raise RuntimeError(f"Worker did not start task: {log.stdout.strip()} {result.stderr.strip()}")
        except BaseException:
            self.release(worker, discard=True)
            raise

    def release(self, worker, discard=False):
        try:
            if not discard:
                docker("exec", worker.name, "/bin/sh", "-ec", RESET)
        except Exception:
            discard = True
        with self.lock:
            if worker not in self.workers:
                return
            if discard:
                worker.retiring = True
                self.retire(worker)
            else:
                worker.workspace = None
                worker.idle_since = time.monotonic()
            self.lock.notify_all()

    def status(self):
        with self.lock:
            leased = sum(w.workspace is not None for w in self.workers)
            return {"total": len(self.workers), "leased": leased,
                    "idle": len(self.workers) - leased}

    def close(self):
        self.stop.set()
        self.maintainer.join()
        with self.lock:
            self.lock.notify_all()
            for worker in self.workers:
                self.remove(worker)
            self.workers.clear()


class Handler(socketserver.StreamRequestHandler):
    def reply(self, data):
        self.wfile.write(json.dumps(data).encode() + b"\n")

    def handle(self):
        worker = None
        discard = False
        try:
            for line in self.rfile:
                request = json.loads(line)
                op = request["op"]
                if op == "status":
                    self.reply(self.server.pool.status())
                elif op == "claim" and worker is None:
                    worker = self.server.pool.acquire(request["workspace"])
                    self.reply({"worker": worker.name})
                elif op == "exec" and worker is not None:
                    try:
                        result = docker("exec", worker.name, "/bin/sh", "-ec", EXEC,
                                        "exec", request["command"], check=False)
                    except subprocess.TimeoutExpired:
                        discard = True
                        raise RuntimeError("Command timed out; worker will be retired")
                    self.reply({"stdout": result.stdout, "stderr": result.stderr,
                                "exit_code": result.returncode})
                elif op == "release" and worker is not None:
                    self.server.pool.release(worker, discard)
                    worker = None
                    self.reply({"released": True})
                else:
                    raise ValueError("Invalid request for this connection")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                self.reply({"error": str(exc)})
            except OSError:
                pass
        finally:
            if worker is not None:
                self.server.pool.release(worker, discard)


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class Client:
    def __init__(self, stream):
        self.stream = stream

    def request(self, op, **fields):
        self.stream.write(json.dumps({"op": op, **fields}).encode() + b"\n")
        self.stream.flush()
        response = self.stream.readline()
        if not response:
            raise RuntimeError("Scheduler disconnected")
        data = json.loads(response)
        if "error" in data:
            raise RuntimeError(data["error"])
        return data


@contextmanager
def connect(path):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(path))
        with connection.makefile("rwb") as stream:
            yield Client(stream)


def serve(args):
    root = args.workspace_root.resolve(strict=True)
    if not root.is_dir() or "," in str(root):
        raise ValueError("Workspace root must be a directory without commas")
    if not 0 <= args.min <= args.max or args.max < 1 or args.idle_seconds <= 0:
        raise ValueError("Require 0 <= min <= max, max >= 1, and positive idle time")
    with tempfile.TemporaryDirectory() as directory, Server(str(args.socket), Handler) as server:
        try:
            args.socket.chmod(0o600)
            server.pool = Pool(args.image, root, args.min, args.max, args.idle_seconds, Path(directory))
            try:
                print(f"Ready: {args.socket}", flush=True)
                server.serve_forever()
            finally:
                server.pool.close()
        finally:
            args.socket.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    subs = parser.add_subparsers(dest="mode", required=True)
    daemon = subs.add_parser("serve")
    daemon.add_argument("--workspace-root", type=Path, required=True)
    daemon.add_argument("--image", default=DEFAULT_IMAGE)
    daemon.add_argument("--min", type=int, default=1)
    daemon.add_argument("--max", type=int, default=4)
    daemon.add_argument("--idle-seconds", type=float, default=30)
    run = subs.add_parser("run")
    run.add_argument("workspace", type=Path)
    run.add_argument("command")
    subs.add_parser("status")
    args = parser.parse_args()
    if args.mode == "serve":
        def interrupt(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)
        try:
            serve(args)
        except KeyboardInterrupt:
            pass
    else:
        with connect(args.socket) as client:
            if args.mode == "status":
                print(json.dumps(client.request("status")))
                return
            client.request("claim", workspace=str(args.workspace.resolve()))
            result = client.request("exec", command=args.command)
            client.request("release")
            print(result["stdout"], end="")
            if result["stderr"]:
                import sys
                print(result["stderr"], end="", file=sys.stderr)
            raise SystemExit(result["exit_code"])


if __name__ == "__main__":
    main()
