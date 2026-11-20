"""Host-side resource sampler for one SandWeaver worker container.

Reads the worker's cgroup v2 files on a fixed period: CPU time, memory split
into anonymous and file-backed pages, and block I/O. The sampler runs outside
the worker and does not enter the lease, so it adds no process or file to the
state a release would discard.

The cgroup is the worker container's, not the lease's. With one lease per
worker it approximates the lease, but it also charges the worker's own
`sleep` process and the page cache of the extracted basis; record a baseline
sample before the first command and report deltas against it.

Timestamps come from `time.monotonic_ns()`, the clock used by the replay and
trace clients on the same host, so samples align with client intervals
without an offset.
"""
from dataclasses import dataclass, field
from pathlib import Path
import threading
import time

from sandweaver import procs, scheduler

CGROUP_ROOT = Path("/sys/fs/cgroup")
MEMORY_KEYS = ("anon", "file", "shmem", "file_dirty", "file_writeback", "file_mapped",
               "active_file", "inactive_file")
# Cumulative event counters from memory.stat: faults, refaults of evicted pages,
# and reclaim activity. Reported as deltas over a window.
MEMORY_COUNTERS = ("pgfault", "pgmajfault", "workingset_refault_anon",
                   "workingset_refault_file", "workingset_activate_file", "pgscan", "pgsteal")
PRESSURE = ("cpu", "memory", "io")


def cgroup_dir(container, root=CGROUP_ROOT):
    """Locate a container's cgroup v2 directory for the systemd or cgroupfs driver."""
    container_id = scheduler.docker("inspect", "-f", "{{.Id}}", container).stdout.strip()
    for candidate in (root / "system.slice" / f"docker-{container_id}.scope",
                      root / "docker" / container_id):
        if (candidate / "cpu.stat").exists():
            return candidate
    raise FileNotFoundError(f"No cgroup v2 directory for container {container}")


def read_sample(directory):
    """One reading of cumulative CPU and I/O counters and current memory."""
    sample = {"t_ns": time.monotonic_ns()}
    for line in (directory / "cpu.stat").read_text().splitlines():
        key, value = line.split()
        if key in ("usage_usec", "user_usec", "system_usec"):
            sample["cpu_" + key] = int(value)
    sample["memory_current"] = int((directory / "memory.current").read_text())
    for line in (directory / "memory.stat").read_text().splitlines():
        key, value = line.split()
        if key in MEMORY_KEYS:
            sample["memory_" + key] = int(value)
        elif key in MEMORY_COUNTERS:
            sample[key] = int(value)
    for kind in PRESSURE:
        # Cumulative stall time in microseconds; absent when PSI is disabled.
        try:
            text = (directory / f"{kind}.pressure").read_text()
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.split()
            sample[f"psi_{kind}_{parts[0]}_us"] = int(parts[-1].partition("=")[2])
    read = written = 0
    for line in (directory / "io.stat").read_text().splitlines():
        for item in line.split()[1:]:
            key, _, value = item.partition("=")
            if key == "rbytes":
                read += int(value)
            elif key == "wbytes":
                written += int(value)
    sample["io_rbytes"], sample["io_wbytes"] = read, written
    return sample


@dataclass
class Sampler:
    """Sample a worker's cgroup in a background thread until stopped."""
    container: str
    interval: float = 0.1
    samples: list = field(default_factory=list)
    errors: int = 0
    directory: Path | None = None
    # Seconds between per-process readings of the same cgroup (procs.py); None: off.
    process_interval: float | None = None
    process_ticks: list = field(default_factory=list)

    def __post_init__(self):
        self.directory = self.directory or cgroup_dir(self.container)
        self._procs = (procs.ProcessSampler(str(self.directory))
                       if self.process_interval else None)
        self._every = max(1, round((self.process_interval or 0) / self.interval))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._cost_ns = 0

    def _run(self):
        next_due = time.monotonic()
        count = 0
        while not self._stop.is_set():
            begin = time.monotonic_ns()
            try:
                self.samples.append(read_sample(self.directory))
                if self._procs and count % self._every == 0:
                    self.process_ticks.append(self._procs.tick())
                count += 1
            except (OSError, ValueError):
                # The container is gone or a file was mid-update; keep sampling.
                self.errors += 1
            self._cost_ns += time.monotonic_ns() - begin
            next_due += self.interval
            self._stop.wait(max(0.0, next_due - time.monotonic()))

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()

    def summary(self):
        """Sampling overhead and the observed period, for reporting next to results."""
        count = len(self.samples)
        span = (self.samples[-1]["t_ns"] - self.samples[0]["t_ns"]) / 1e9 if count > 1 else 0
        return {"container_cgroup": str(self.directory), "interval_s": self.interval,
                "samples": count, "errors": self.errors,
                "process_interval_s": self.process_interval,
                "process_ticks": len(self.process_ticks),
                "mean_period_s": span / (count - 1) if count > 1 else None,
                "mean_read_cost_us": self._cost_ns / count / 1e3 if count else None}


def window(samples, start_ns, end_ns):
    """Usage over [start_ns, end_ns]: CPU and I/O deltas, memory peak and mean.

    The window is widened to the last sample at or before the start and the first
    at or after the end, so intervals shorter than the period still get a delta;
    `span_s` reports the widened span, which overstates short intervals by up to
    two periods.
    """
    lo = max((i for i, s in enumerate(samples) if s["t_ns"] <= start_ns), default=0)
    hi = min((i for i, s in enumerate(samples) if s["t_ns"] >= end_ns),
             default=len(samples) - 1)
    inside = samples[lo:hi + 1]
    if len(inside) < 2:
        return None
    first, last = inside[0], inside[-1]
    span = (last["t_ns"] - first["t_ns"]) / 1e9
    cpu = (last["cpu_usage_usec"] - first["cpu_usage_usec"]) / 1e6
    result = {"samples": len(inside), "span_s": span, "cpu_s": cpu,
              "cpu_util": cpu / span if span > 0 else None,
              "io_rbytes": last["io_rbytes"] - first["io_rbytes"],
              "io_wbytes": last["io_wbytes"] - first["io_wbytes"]}
    for key in MEMORY_COUNTERS + tuple(f"psi_{k}_some_us" for k in PRESSURE):
        if key in first and key in last:
            result[key] = last[key] - first[key]
    for key in ("memory_current", "memory_anon", "memory_file"):
        values = [s[key] for s in inside if key in s]
        if values:
            result[key + "_max"] = max(values)
            result[key + "_mean"] = sum(values) / len(values)
    return result
