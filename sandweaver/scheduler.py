#!/usr/bin/env python3
"""Local Docker worker pool. Use only trusted tasks and images in this prototype."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
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
    mkdir -p "$d/root$2"
    mount --bind "$1" "$d/root$2"
    for device in null zero random urandom; do
        touch "$d/root/dev/$device"
        mount --bind "/dev/$device" "$d/root/dev/$device"
    done
    exec unshare --pid /bin/sh -ec "$3" anchor "$4"
' lease "$1" "$2" '
    d=/state/task
    if test -n "$1"; then
        chroot "$d/root" /bin/sh -ec "$1" </dev/null >/dev/null 2>&1 &
    else
        chroot "$d/root" /bin/sleep infinity </dev/null >/dev/null 2>&1 &
    fi
    pid=$!
    echo "$pid" > "$d/pid"
    wait "$pid" || :
    : > "$d/done"
' "$3"
"""
# Optional lease anchor (pid 1 of the lease PID namespace) that mounts a procfs for
# that namespace. Like Docker, kernel tunables stay read-only and sensitive entries are
# masked: lease commands run as uid 0 and could otherwise write /proc/sys or
# /proc/sysrq-trigger, which act on the host kernel.
PROC_ANCHOR = r"""
mount -t proc -o nosuid,nodev,noexec proc /proc
for p in sys sysrq-trigger irq bus fs; do
    if test -e "/proc/$p"; then
        mount --bind "/proc/$p" "/proc/$p"
        mount -o remount,bind,ro "/proc/$p"
    fi
done
for p in kcore keys timer_list sched_debug; do
    if test -e "/proc/$p"; then mount --bind /dev/null "/proc/$p"; fi
done
for p in acpi scsi; do
    if test -d "/proc/$p"; then mount -t tmpfs -o ro tmpfs "/proc/$p"; fi
done
exec /bin/sleep infinity
"""
# Commands keep uid 0 and only the file-permission capabilities, so they can write
# host-owned workspaces and root-owned system paths like the official task images.
EXEC = r"""
read -r pid < /state/task/pid
# --wd without a value takes the anchor's cwd (/ after chroot); util-linux 2.37,
# as in Ubuntu 22.04 task images, has no --wdns.
exec nsenter --target "$pid" --mount --pid --root --wd -- /usr/bin/setpriv \
    --bounding-set=-all,+dac_override,+fowner,+chown \
    --inh-caps=-all --ambient-caps=-all --no-new-privs \
    /bin/sh -c 'cd "$2" && exec /bin/sh -c "$1"' command "$1" "${2:-/workspace}"
"""
DEFAULT_MOUNT = "/workspace"
# Read-only view of lease state that RESET would discard: live processes in the
# lease PID namespace (besides its init) and files in the OverlayFS write layer.
INSPECT = r"""
read -r pid < /state/task/pid
ns=$(readlink "/proc/$pid/ns/pid")
for p in /proc/[0-9]*; do
    test "${p#/proc/}" = "$pid" && continue
    test "$(readlink "$p/ns/pid" 2>/dev/null)" = "$ns" || continue
    printf 'P\t%s\n' "$(cat "$p/comm" 2>/dev/null)"
done
cd /state/task/upper
find . -mindepth 1 ! -type d -exec stat --printf 'F\t%F\t%s\t%n\n' {} +
"""
# Give files that lease commands created as root back to the workspace owner.
RESTORE_OWNER = r"""
find "$1" -xdev \( -uid 0 -o -gid 0 \) -exec chown -h "$2" {} +
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


def summarize_lease_state(listing, top=20):
    """Aggregate INSPECT output; keep process names and two-level path prefixes only."""
    processes, prefixes = [], {}
    files = whiteouts = total = 0
    for line in listing.splitlines():
        fields = line.split("\t")
        if fields[0] == "P" and len(fields) == 2:
            processes.append(fields[1])
        elif fields[0] == "F" and len(fields) == 4:
            kind, size, name = fields[1], int(fields[2]), fields[3]
            if kind == "character special file" and size == 0:
                whiteouts += 1
                continue
            files += 1
            total += size
            prefix = "/".join(name.removeprefix("./").split("/")[:2])
            prefixes[prefix] = prefixes.get(prefix, 0) + size
    largest = dict(sorted(prefixes.items(), key=lambda item: -item[1])[:top])
    return {"processes": sorted(processes), "upper_files": files, "upper_bytes": total,
            "upper_whiteouts": whiteouts, "upper_prefix_bytes": largest}


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
    def __init__(self, image, root, minimum, maximum, idle_seconds, directory,
                 mount=DEFAULT_MOUNT, network="none", state_size="512m", exec_timeout=60,
                 proc=False, *, resume_grace_ms=0):
        self.root, self.minimum, self.maximum = root, minimum, maximum
        self.anchor = PROC_ANCHOR if proc else ""
        self.idle_seconds = idle_seconds
        self.mount, self.network = mount, network
        self.state_size, self.exec_timeout = state_size, exec_timeout
        self.resume_grace_ms = resume_grace_ms
        self.image = docker("image", "inspect", "--format", "{{.Id}}", image).stdout.strip()
        self.archive = directory / "basis.tar"
        self.prefix = "sandweaver-" + uuid.uuid4().hex[:10]
        seed = self.prefix + "-seed"
        self.workers = []
        self.reservations = {}
        self.parked = {}
        self.reclaiming = set()
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
        # "disk" keeps the lease write layer on an anonymous volume instead of RAM.
        state = (["--mount", "type=volume,dst=/state"] if self.state_size == "disk"
                 else ["--tmpfs", f"/state:exec,size={self.state_size}"])
        try:
            docker("run", "-d", "--name", name, "--network", self.network,
                   "--cap-add", "SYS_ADMIN", "--security-opt", "seccomp=unconfined",
                   *state, "--mount",
                   f"type=bind,src={self.root},dst=/allowed", "--entrypoint", "/bin/sh",
                   self.image, "-ec", "mkdir /basis; exec sleep infinity")
            with self.archive.open("rb") as archive:
                docker("exec", "-i", name, "tar", "-xf", "-", "-C", "/basis", stdin=archive,
                       timeout=900)
            docker("exec", name, "/bin/sh", "-ec",
                   "test -x /basis/usr/bin/setpriv; command -v nsenter; command -v unshare")
        except BaseException:
            self.remove(worker)
            raise
        worker.idle_since = time.monotonic()
        return worker

    @staticmethod
    def remove(worker):
        return docker("rm", "-f", "-v", worker.name, check=False)

    def run(self, worker, command, timeout=60):
        """Run a shell command inside the worker's current lease."""
        return docker("exec", worker.name, "/bin/sh", "-ec", EXEC, "exec", command, self.mount,
                      check=False, timeout=timeout)

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

    def resolve_workspace(self, path):
        workspace = Path(path).resolve(strict=True)
        if not workspace.is_dir() or not workspace.is_relative_to(self.root):
            raise ValueError("Workspace must be a directory under the scheduler workspace root")
        return workspace

    def check_workspace(self, workspace, owner=None):
        # Call under the pool lock so reservations and active leases agree.
        for current in self.workers:
            other = current.workspace
            if other and (workspace.is_relative_to(other) or other.is_relative_to(workspace)):
                raise RuntimeError("Workspace overlaps an active lease")
        for other, holder in self.reservations.items():
            if holder is not owner and (workspace.is_relative_to(other) or other.is_relative_to(workspace)):
                raise RuntimeError("Workspace overlaps a session reservation")

    def reserve(self, path, owner):
        workspace = self.resolve_workspace(path)
        with self.lock:
            self.check_workspace(workspace)
            self.reservations[workspace] = owner
        return workspace

    def unreserve(self, workspace):
        with self.lock:
            del self.reservations[workspace]

    def park(self, owner, worker):
        with self.lock:
            self.parked[owner] = worker
            self.lock.notify_all()

    def release_parked(self, owner):
        with self.lock:
            worker = self.parked.pop(owner, None)
        if worker is not None:
            self.release(worker)

    def acquire(self, path, timing=None, owner=None, *, resuming=False):
        workspace = self.resolve_workspace(path)
        started = time.monotonic()
        deadline = started + 30
        grace_deadline = started + (self.resume_grace_ms / 1000 if resuming else 0)
        queue_wait_ns = 0
        reclaim_ns = 0
        while True:
            with self.lock:
                if self.stop.is_set():
                    raise RuntimeError("Pool is shutting down")
                if owner is not None and self.reservations.get(workspace) is not owner:
                    raise RuntimeError("Workspace no longer matches the session reservation")
                parked = self.parked.pop(owner, None)
                if parked is not None:
                    if timing is not None:
                        timing.update(pool_wait_ns=queue_wait_ns, reclaim_ns=reclaim_ns,
                                      resumed_parked=True, start_exec_ns=0, readiness_ns=0,
                                      readiness_exec_ns=0, readiness_attempts=0)
                    return parked
                if owner not in self.reclaiming:
                    self.check_workspace(workspace, owner)
                    worker = next((w for w in self.workers if w.workspace is None), None)
                    if worker is None and len(self.workers) < self.maximum:
                        worker = self.spawn()
                        self.workers.append(worker)
                    if worker is not None:
                        worker.workspace = workspace
                        break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Pool is full")
                grace_remaining = grace_deadline - time.monotonic()
                if owner in self.reclaiming or not self.parked or grace_remaining > 0:
                    wait_started = time.monotonic_ns()
                    self.lock.wait(min(remaining, grace_remaining) if grace_remaining > 0 else remaining)
                    queue_wait_ns += time.monotonic_ns() - wait_started
                    continue
                parked_owner = next(iter(self.parked))
                parked = self.parked.pop(parked_owner)
                self.reclaiming.add(parked_owner)
            reclaim_started = time.monotonic_ns()
            try:
                self.release(parked)
            finally:
                with self.lock:
                    self.reclaiming.remove(parked_owner)
                    self.lock.notify_all()
                reclaim_ns += time.monotonic_ns() - reclaim_started

        if timing is not None:
            timing.update(pool_wait_ns=queue_wait_ns, reclaim_ns=reclaim_ns, resumed_parked=False)

        try:
            relative = workspace.relative_to(self.root)
            launch_started = time.monotonic_ns() if timing is not None else None
            docker("exec", "-d", worker.name, "/bin/sh", "-ec", START, "start",
                   str(Path("/allowed") / relative), self.mount, self.anchor)
            if timing is not None:
                probe_started = time.monotonic_ns()
                timing["start_exec_ns"] = probe_started - launch_started
                timing["readiness_exec_ns"] = 0
                timing["readiness_attempts"] = 0
            until = time.monotonic() + 5
            while time.monotonic() < until:
                attempt_started = time.monotonic_ns() if timing is not None else None
                result = self.run(worker, "true")
                if timing is not None:
                    attempt_finished = time.monotonic_ns()
                    timing["readiness_exec_ns"] += attempt_finished - attempt_started
                    timing["readiness_attempts"] += 1
                if result.returncode == 0:
                    if timing is not None:
                        timing["readiness_ns"] = attempt_finished - probe_started
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
                # Large write layers on disk can take a while to delete.
                docker("exec", worker.name, "/bin/sh", "-ec", RESET, timeout=300)
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

    def restore_owner(self, workspace):
        """Chown root-created workspace files to the workspace directory's owner."""
        info = workspace.stat()
        if info.st_uid == 0:
            return
        target = str(Path("/allowed") / workspace.relative_to(self.root))
        owner = f"{info.st_uid}:{info.st_gid}"
        with self.lock:
            worker = next((w for w in self.workers if not w.retiring), None)
        # A worker's management layer already mounts /allowed; with none left, use a
        # short-lived container from the same image.
        if worker is not None:
            prefix = ["exec", worker.name, "/bin/sh"]
        else:
            prefix = ["run", "--rm", "--network", "none", "--mount",
                      f"type=bind,src={self.root},dst=/allowed", "--entrypoint", "/bin/sh",
                      self.image]
        docker(*prefix, "-ec", RESTORE_OWNER, "restore", target, owner, timeout=300)

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
        resuming = False
        reservation = None
        owner = object()
        discard = False
        touched = set()
        try:
            for line in self.rfile:
                request = json.loads(line)
                op = request["op"]
                if op == "status":
                    self.reply(self.server.pool.status())
                elif op == "reserve" and reservation is None and worker is None:
                    reservation = self.server.pool.reserve(request["workspace"], owner)
                    self.reply({"reserved": True})
                elif op == "claim" and worker is None:
                    timing = {} if request.get("observe") else None
                    started = time.monotonic_ns()
                    if reservation is None:
                        worker = self.server.pool.acquire(request["workspace"], timing)
                    else:
                        if "workspace" in request:
                            raise ValueError("A reserved session claims only its reserved workspace")
                        worker = self.server.pool.acquire(reservation, timing, owner, resuming=resuming)
                    resuming = False
                    touched.add(worker.workspace)
                    reply = {"worker": worker.name}
                    if timing is not None:
                        timing["claim_ns"] = time.monotonic_ns() - started
                        reply["timing"] = timing
                    self.reply(reply)
                elif op == "exec" and worker is not None:
                    started = time.monotonic_ns()
                    try:
                        result = self.server.pool.run(worker, request["command"],
                                                      self.server.pool.exec_timeout)
                    except subprocess.TimeoutExpired:
                        discard = True
                        raise RuntimeError("Command timed out; worker will be retired")
                    reply = {"stdout": result.stdout, "stderr": result.stderr,
                             "exit_code": result.returncode}
                    if request.get("observe"):
                        reply["timing"] = {"exec_ns": time.monotonic_ns() - started}
                    self.reply(reply)
                elif op == "inspect" and worker is not None:
                    # Observation only: a failed probe must not end the session or its lease.
                    try:
                        result = docker("exec", worker.name, "/bin/sh", "-ec", INSPECT,
                                        check=False, timeout=120)
                    except subprocess.TimeoutExpired:
                        self.reply({"inspect_failed": "timeout"})
                        continue
                    if result.returncode:
                        self.reply({"inspect_failed": result.stderr.strip()[-200:]})
                    else:
                        self.reply(summarize_lease_state(result.stdout))
                elif op == "park" and worker is not None and reservation is not None:
                    self.server.pool.park(owner, worker)
                    worker = None
                    resuming = True
                    self.reply({"parked": True})
                elif op == "release" and (worker is not None or reservation is not None):
                    resuming = False
                    if worker is not None:
                        self.server.pool.release(worker, discard)
                        worker = None
                    else:
                        self.server.pool.release_parked(owner)
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
            try:
                if worker is not None:
                    self.server.pool.release(worker, discard)
            finally:
                try:
                    if reservation is not None:
                        self.server.pool.release_parked(owner)
                finally:
                    # After every lease of this connection has been reset, so no lease
                    # process can still create root-owned files; a reservation stays
                    # held until ownership is restored.
                    try:
                        for workspace in touched:
                            try:
                                self.server.pool.restore_owner(workspace)
                            except Exception as exc:
                                print(f"Workspace ownership restore failed: {exc}", flush=True)
                    finally:
                        if reservation is not None:
                            self.server.pool.unreserve(reservation)


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
    if not re.fullmatch(r"(/[A-Za-z0-9._-]+)+", args.workspace_mount):
        raise ValueError("Workspace mount must be an absolute path of plain components")
    if args.state_size != "disk" and not re.fullmatch(r"[0-9]+[kmg]", args.state_size):
        raise ValueError("State size must look like 512m or 4g, or be 'disk'")
    if args.exec_timeout <= 0:
        raise ValueError("Exec timeout must be positive")
    with tempfile.TemporaryDirectory() as directory, Server(str(args.socket), Handler) as server:
        try:
            args.socket.chmod(0o600)
            server.pool = Pool(args.image, root, args.min, args.max, args.idle_seconds, Path(directory),
                               args.workspace_mount, args.network, args.state_size,
                               args.exec_timeout, args.proc)
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
    daemon.add_argument("--workspace-mount", default=DEFAULT_MOUNT,
                        help="Path where each lease sees its workspace, e.g. /testbed")
    daemon.add_argument("--network", choices=("none", "bridge"), default="none",
                        help="Worker network; bridge allows package downloads (wider boundary)")
    daemon.add_argument("--state-size", default="512m",
                        help="tmpfs size for lease write layers, or 'disk' for a Docker volume")
    daemon.add_argument("--exec-timeout", type=float, default=60,
                        help="Seconds before a command is treated as hung and its worker retired")
    daemon.add_argument("--proc", action="store_true",
                        help="Mount a masked procfs for each lease (needed by cargo, node, old setpriv)")
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
