#!/usr/bin/env python3
"""Measure worker occupancy while an external client downloads a task artifact."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
from pathlib import Path
import statistics
import tempfile
import threading
import time

from sandweaver import scheduler

ARTIFACT = b"downloaded artifact\n"


class SlowSource(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.request_started.set()
        time.sleep(self.server.delay)
        self.send_response(200)
        self.send_header("Content-Length", str(len(ARTIFACT)))
        self.end_headers()
        self.wfile.write(ARTIFACT)

    def log_message(self, *_):
        pass


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        thread.join()


def execute(client, command):
    result = client.request("exec", command=command)
    if result["exit_code"] != 0:
        raise RuntimeError(f"Command failed: {command!r}: {result}")
    return result["stdout"].strip()


def download(connection, destination):
    connection.request("GET", "/artifact")
    with connection.getresponse() as response:
        if response.status != 200:
            raise RuntimeError(f"Artifact download returned HTTP {response.status}")
        destination.write_bytes(response.read())
    return time.perf_counter()


def measure(socket, source, root, mode, probe_offset, estimated_io, threshold):
    source.request_started.clear()
    probe_ready = threading.Event()
    connection = HTTPConnection("127.0.0.1", source.server_port, timeout=source.delay + 5)
    with (
        tempfile.TemporaryDirectory(dir=root) as directory,
        tempfile.TemporaryDirectory(prefix="download-", dir=root.parent) as staging,
        closing(connection),
        ThreadPoolExecutor(max_workers=1) as tasks,
        ThreadPoolExecutor(max_workers=1) as io_pool,
    ):
        workspace = Path(directory) / "download"
        probe_workspace = Path(directory) / "probe"
        workspace.mkdir()
        probe_workspace.mkdir()

        def probe():
            if probe_offset:
                if not source.request_started.wait(timeout=30):
                    raise TimeoutError("Download never reached the HTTP server")
                time.sleep(probe_offset)
            with scheduler.connect(socket) as client:
                start = time.perf_counter()
                probe_ready.set()
                client.request("claim", workspace=str(probe_workspace))
                claimed = time.perf_counter()
                execute(client, "test ! -e /tmp/download-private")
                client.request("release")
            return (claimed - start) * 1000, (time.perf_counter() - start) * 1000

        with scheduler.connect(socket) as client:
            start = time.perf_counter()
            client.request("claim", workspace=str(workspace))
            first_claimed = time.perf_counter()
            execute(client, "printf artifact > request; touch /tmp/download-private")
            competing = tasks.submit(probe)
            if not probe_offset and not probe_ready.wait(timeout=5):
                raise TimeoutError("Immediate probe did not become runnable")
            release_for_io = mode == "release_for_io" or (
                mode == "dynamic" and probe_ready.is_set() and estimated_io >= threshold
            )
            io_start = time.perf_counter()
            artifact = Path(staging) / "artifact"
            pending_download = io_pool.submit(download, connection, artifact)
            if release_for_io:
                client.request("release")
            first_lease_end = time.perf_counter()
            io_end = pending_download.result()
            if release_for_io:
                reclaim_start = time.perf_counter()
                client.request("claim", workspace=str(workspace))
            claimed_again = time.perf_counter()
            if artifact.read_bytes() != ARTIFACT:
                raise RuntimeError("Downloaded artifact failed validation")
            artifact.replace(workspace / "artifact")
            state_check = "test ! -e" if release_for_io else "test -e"
            output = execute(client, f"{state_check} /tmp/download-private && test -f request && cat artifact")
            if output != ARTIFACT.decode().strip():
                raise RuntimeError(f"Unexpected artifact: {output!r}")
            client.request("release")
            done = time.perf_counter()
        probe_claim_ms, probe_done_ms = competing.result()

    occupied = done - first_claimed
    if release_for_io:
        occupied = (first_lease_end - first_claimed) + (done - claimed_again)
    return {
        "probe_claim_ms": probe_claim_ms,
        "probe_done_ms": probe_done_ms,
        "download_ms": (io_end - io_start) * 1000,
        "download_task_ms": (done - start) * 1000,
        "download_task_granted_lease_ms": occupied * 1000,
        "reclaim_ms": (claimed_again - reclaim_start) * 1000 if release_for_io else None,
        "released_for_io": release_for_io,
    }


def run(image, rounds, delay, probe_offset, threshold):
    modes = ["hold_lease", "release_for_io"]
    if threshold is not None:
        modes.append("dynamic")
    samples = {mode: [] for mode in modes}
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        root = Path(directory).resolve()
        workspaces = root / "workspaces"
        workspaces.mkdir()
        socket = root / "pool.sock"
        with scheduler.Server(str(socket), scheduler.Handler) as server, HTTPServer(("127.0.0.1", 0), SlowSource) as source:
            source.delay = delay
            source.request_started = threading.Event()
            start = time.perf_counter()
            pool = scheduler.Pool(image, workspaces, 1, 1, 30, root)
            preparation_ms = (time.perf_counter() - start) * 1000
            server.pool = pool
            try:
                with serving(server), serving(source):
                    for mode in modes:
                        measure(socket, source, workspaces, mode, probe_offset, delay, threshold)
                    for index in range(rounds):
                        for mode in modes[index % len(modes):] + modes[:index % len(modes)]:
                            sample = measure(socket, source, workspaces, mode, probe_offset, delay, threshold)
                            samples[mode].append(sample)
            finally:
                pool.close()

    summary = {}
    for mode, rows in samples.items():
        summary[mode] = {}
        for metric in rows[0]:
            if not metric.endswith("_ms"):
                continue
            values = sorted(row[metric] for row in rows if row[metric] is not None)
            if values:
                summary[mode][metric] = {
                    "p50": statistics.median(values),
                    "p95": values[math.ceil(0.95 * len(values)) - 1],
                }
    return {
        "image": image, "image_id": pool.image, "workers": 1,
        "rounds_per_mode": rounds, "warmup_per_mode": 1,
        "source_delay_seconds": delay, "artifact_bytes": len(ARTIFACT),
        "probe_offset_seconds": probe_offset,
        "dynamic_threshold_seconds": threshold,
        "preparation_ms": preparation_ms, "summary_ms": summary, "samples": samples,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=scheduler.DEFAULT_IMAGE)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--delay", type=float, default=1)
    parser.add_argument("--probe-offset", type=float, default=0, help="Zero for immediate demand, otherwise seconds after GET")
    parser.add_argument("--dynamic-threshold", type=float, help="Add dynamic mode using this minimum predicted wait in seconds")
    options = parser.parse_args()
    if options.rounds < 1 or not math.isfinite(options.delay) or options.delay <= 0:
        parser.error("rounds and delay must be positive")
    if not math.isfinite(options.probe_offset) or options.probe_offset < 0:
        parser.error("probe offset must be finite and nonnegative")
    threshold = options.dynamic_threshold
    if threshold is not None and (not math.isfinite(threshold) or threshold <= 0):
        parser.error("dynamic threshold must be finite and positive")
    print(json.dumps(run(options.image, options.rounds, options.delay, options.probe_offset, threshold), indent=2))
