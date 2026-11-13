#!/usr/bin/env python3
"""Exercise lease-scoped, read-only dependency mounts on trusted demo workers."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import statistics
import time
from unittest.mock import patch

from sandweaver import scheduler


def run(image):
    docker = scheduler.docker
    start = scheduler.START
    mount_point = '    mkdir -p "$d/root/workspace"'
    if start.count(mount_point) != 1:
        raise RuntimeError("Could not locate the lease mount setup")

    with tempfile.TemporaryDirectory(prefix="sw-components-", dir="/tmp") as directory:
        scratch = Path(directory).resolve()
        root = scratch / "workspaces"
        components = scratch / "components"
        components.mkdir()
        manifests = {}
        for session, version in (("a", "v1"), ("b", "v2")):
            workspace = root / session
            workspace.mkdir(parents=True)
            payload = f'VERSION = "{version}"\n'.encode()
            digest = hashlib.sha256(payload).hexdigest()
            component = components / digest
            component.mkdir()
            (component / "demo_dependency.py").write_bytes(payload)
            manifests[session] = {"component": digest, "version": version}

        def with_components(*args, **kwargs):
            if args[0] == "run":
                index = args.index("--entrypoint")
                args = (*args[:index], "--mount",
                        f"type=bind,src={components},dst=/components,readonly", *args[index:])
            elif args[:2] == ("exec", "-d") and args[5] == start:
                session = Path(args[-1]).name
                digest = manifests[session]["component"]
                component_mount = (
                    '    mkdir -p "$d/root/opt/dependency"\n'
                    f'    mount --bind /components/{digest} "$d/root/opt/dependency"\n'
                    '    mount -o remount,bind,ro "$d/root/opt/dependency"\n'
                )
                args = (*args[:5], start.replace(mount_point, component_mount + mount_point), *args[6:])
            return docker(*args, **kwargs)

        def verify(pool, session):
            started = time.monotonic_ns()
            worker = pool.acquire(root / session)
            claimed = time.monotonic_ns()
            version = manifests[session]["version"]
            command = (
                "test ! -e /components && test ! -e /tmp/prior-lease && "
                f"PYTHONPATH=/opt/dependency /project/.venv/bin/python -B -c "
                f"'import demo_dependency as dep; assert dep.VERSION == \"{version}\"' && "
                "test \"$(find /opt/dependency -name demo_dependency.py | wc -l)\" -eq 1 && "
                "if (echo invalid > /opt/dependency/demo_dependency.py) 2>/dev/null; "
                "then exit 1; fi; "
                "touch /tmp/prior-lease"
            )
            try:
                scheduler.docker("exec", worker.name, "/bin/sh", "-ec", scheduler.EXEC, "exec", command)
                verified = time.monotonic_ns()
            finally:
                pool.release(worker)
            if worker.retiring or worker not in pool.workers:
                raise RuntimeError("Worker reset failed")
            return worker, {"session": session, "version": version,
                            "claim_ms": (claimed - started) / 1e6,
                            "claim_to_verified_ms": (verified - started) / 1e6}

        with patch.object(scheduler, "docker", with_components):
            pool = scheduler.Pool(image, root, 2, 2, 60, scratch)
            try:
                original = pool.workers[0]
                handovers = []
                for session in ("a", "b", "a"):
                    worker, row = verify(pool, session)
                    if worker is not original:
                        raise RuntimeError("Expected the same worker for warm handovers")
                    handovers.append(row)

                with pool.lock:
                    started = time.monotonic_ns()
                    pool.retire(original)
                    if original in pool.workers:
                        raise RuntimeError("Could not confirm original worker removal")
                    replacement = pool.spawn()
                    pool.workers.insert(0, replacement)
                    replace_ms = (time.monotonic_ns() - started) / 1e6
                worker, restored = verify(pool, "a")
                if worker is not replacement:
                    raise RuntimeError("Expected the replacement worker")
                for manifest in manifests.values():
                    digest = manifest["component"]
                    source = components / digest / "demo_dependency.py"
                    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                        raise RuntimeError("Shared component was modified")
                return {"image": image, "image_id": pool.image, "manifests": manifests,
                        "same_worker_handoffs": handovers, "replacement_ms": replace_ms,
                        "restored_on_replacement": restored}
            finally:
                pool.close()


def compare(image, rounds):
    """Compare a baked-in package, a prepared mount, and offline reinstallation."""
    arms = ("baseline", "mounted", "rebuild")
    python = "/project/.venv/bin/python"
    start = scheduler.START
    marker = '    mkdir -p "$d/root/workspace"'
    if start.count(marker) != 1:
        raise RuntimeError("Could not locate the lease mount setup")

    with tempfile.TemporaryDirectory(prefix="sw-package-", dir="/tmp") as directory:
        scratch = Path(directory).resolve()
        store = scratch / "components"
        store.mkdir()
        root = scratch / "workspaces"
        for arm in arms:
            (root / arm).mkdir(parents=True)
        docker = scheduler.docker
        image_id = docker("image", "inspect", "--format", "{{.Id}}", image).stdout.strip()
        mount = f"type=bind,src={store},dst=/components"
        docker("run", "--rm", "--mount", mount, image_id, python, "-m", "pip", "download",
               "--disable-pip-version-check", "--only-binary=:all:", "--no-deps",
               "--dest", "/components", "humanize==4.12.3")
        wheel, = store.glob("humanize-*.whl")
        wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        install = (f"{python} -m pip install --disable-pip-version-check --no-index "
                   f"--no-deps --no-compile --target")
        docker("run", "--rm", "--network", "none", "--mount", mount, image_id,
               "/bin/sh", "-ec", f"{install} /components/prepared /components/{wheel.name}")

        def component_docker(*args, **kwargs):
            if args[0] == "run":
                index = args.index("--entrypoint")
                args = (*args[:index], "--mount", mount + ",readonly", *args[index:])
            elif args[:2] == ("exec", "-d") and args[5] == start:
                arm = Path(args[-1]).name
                if arm != "baseline":
                    source = "/components/prepared" if arm == "mounted" else f"/components/{wheel.name}"
                    target = "/opt/dependency" if arm == "mounted" else "/opt/dependency.whl"
                    setup = (f'    mkdir -p "$d/root{target}"\n' if arm == "mounted"
                             else f'    touch "$d/root{target}"\n')
                    setup += (f'    mount --bind {source} "$d/root{target}"\n'
                              f'    mount -o remount,bind,ro "$d/root{target}"\n')
                    args = (*args[:5], start.replace(marker, setup + marker), *args[6:])
            return docker(*args, **kwargs)

        # Keep the wheel filename intact inside the lease for pip validation.
        install_in_lease = (f"cp /opt/dependency.whl /tmp/{wheel.name} && "
                            f"{install} /opt/dependency /tmp/{wheel.name}")
        with patch.object(scheduler, "docker", component_docker):
            started = time.monotonic_ns()
            pool = scheduler.Pool(image_id, root, 1, 1, 60, scratch)
            setup_ms = (time.monotonic_ns() - started) / 1e6
            samples = {arm: [] for arm in arms}
            original, = pool.workers
            try:
                for index in range(rounds + 1):
                    offset = index % len(arms)
                    for arm in arms[offset:] + arms[:offset]:
                        started = time.monotonic_ns()
                        worker = pool.acquire(root / arm)
                        claimed = time.monotonic_ns()
                        try:
                            install_ms = 0.0
                            if arm == "rebuild":
                                docker("exec", worker.name, "/bin/sh", "-ec", scheduler.EXEC,
                                       "exec", install_in_lease)
                                install_ms = (time.monotonic_ns() - claimed) / 1e6
                            prefix = "/project/.venv/" if arm == "baseline" else "/opt/dependency/"
                            command = (f"PYTHONPATH=/opt/dependency {python} -B -c "
                                       f"'import humanize; assert humanize.__version__ == \"4.12.3\"; "
                                       f"assert humanize.__file__.startswith(\"{prefix}\"); "
                                       "assert humanize.intcomma(1000) == \"1,000\"'")
                            docker("exec", worker.name, "/bin/sh", "-ec", scheduler.EXEC,
                                   "exec", command)
                            finished = time.monotonic_ns()
                        finally:
                            pool.release(worker)
                        if worker is not original or worker.retiring or worker not in pool.workers:
                            raise RuntimeError("Expected one healthy worker across all arms")
                        if index:
                            samples[arm].append({"claim_ms": (claimed - started) / 1e6,
                                                 "install_ms": install_ms,
                                                 "claim_to_verified_ms": (finished - started) / 1e6})
            finally:
                pool.close()

        summary = {}
        for arm, rows in samples.items():
            summary[arm] = {}
            for metric in rows[0]:
                values = sorted(row[metric] for row in rows)
                summary[arm][metric] = {"p50": statistics.median(values),
                                        "p95": values[(95 * len(values) + 99) // 100 - 1]}
        return {"image_id": image_id, "wheel_sha256": wheel_digest, "rounds_per_arm": rounds,
                "warmup_per_arm": 1, "pool_setup_ms": setup_ms,
                "component_bytes": sum(path.stat().st_size for path in (store / "prepared").rglob("*")
                                       if path.is_file()),
                "samples": samples, "summary_ms": summary}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=scheduler.DEFAULT_IMAGE)
    parser.add_argument("--rounds", type=int, help="Compare offline installation and component mounts")
    args = parser.parse_args()
    if args.rounds is not None and args.rounds < 1:
        parser.error("--rounds must be positive")
    result = run(args.image) if args.rounds is None else compare(args.image, args.rounds)
    print(json.dumps(result, indent=2))
