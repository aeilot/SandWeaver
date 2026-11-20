"""Per-process CPU, fault and memory sampling from /proc.

Standard library only, so the same file runs on the host (for the processes of
one cgroup, such as a container desktop) and inside an OSWorld guest VM (for
every process, kernel threads included), where it is copied in and started
as a script.

Each record is one tick: {"t_ns", "wall_ns", "procs": {pid: row}}. A row is
[comm, utime_ticks, stime_ticks, minflt, majflt, rss_bytes, starttime] and, with
io, [..., read_bytes, write_bytes]. CPU and fault counters are cumulative, so
attribution is the difference between two ticks for the same (pid, starttime).
To keep files small a tick lists only processes whose CPU or fault counters
changed since the previous tick, plus every process every `full_every` ticks
and on the first tick. `t_ns` is CLOCK_MONOTONIC on the machine that sampled;
`wall_ns` is CLOCK_REALTIME, for aligning a guest's samples with the host.

Run as a script: python3 procs.py --interval 0.25 --io --out procs.jsonl
The sampling process renames itself to "sw-procs" so it can be told apart.
"""
import argparse
import json
import os
import signal
import sys
import time

PAGE = os.sysconf("SC_PAGE_SIZE")
CLK_TCK = os.sysconf("SC_CLK_TCK")


def list_pids(cgroup=None):
    """Processes of a cgroup v2 directory, or every process on the machine."""
    if cgroup:
        with open(os.path.join(cgroup, "cgroup.procs")) as handle:
            return [int(x) for x in handle.read().split()]
    return [int(name) for name in os.listdir("/proc") if name.isdigit()]


def read_process(pid, io=False):
    """One process's row, or None if it exited while being read."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    # comm may contain spaces and parentheses; it ends at the last ")".
    left, right = data.index(b"("), data.rindex(b")")
    comm = data[left + 1:right].decode(errors="replace")
    fields = data[right + 2:].split()
    # fields[0] is stat field 3 (state): minflt 10, majflt 12, utime 14, stime 15,
    # starttime 22, rss 24 (pages).
    row = [comm, int(fields[11]), int(fields[12]), int(fields[7]), int(fields[9]),
           int(fields[21]) * PAGE, int(fields[19])]
    if io:
        read = written = 0
        try:
            with open(f"/proc/{pid}/io") as handle:
                for line in handle:
                    key, _, value = line.partition(":")
                    if key == "read_bytes":
                        read = int(value)
                    elif key == "write_bytes":
                        written = int(value)
        except OSError:
            read = written = -1  # not permitted or exited; -1 marks unknown
        row += [read, written]
    return row


class ProcessSampler:
    """Produces change-only ticks for one cgroup or for the whole machine."""

    def __init__(self, cgroup=None, io=False, full_every=40):
        self.cgroup, self.io, self.full_every = cgroup, io, full_every
        self.last = {}
        self.ticks = 0

    def tick(self):
        full = self.ticks % self.full_every == 0
        self.ticks += 1
        record = {"t_ns": time.monotonic_ns(), "wall_ns": time.time_ns(), "procs": {}}
        seen = {}
        for pid in list_pids(self.cgroup):
            row = read_process(pid, self.io)
            if row is None:
                continue
            key = (row[1], row[2], row[3], row[4])
            seen[pid] = key
            if full or self.last.get(pid) != key:
                record["procs"][pid] = row
        self.last = seen
        if full:
            record["full"] = True
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--cgroup", help="cgroup v2 directory; default: every process")
    parser.add_argument("--io", action="store_true", help="also read /proc/<pid>/io (needs root)")
    parser.add_argument("--full-every", type=int, default=40)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        with open("/proc/self/comm", "w") as handle:
            handle.write("sw-procs")
    except OSError:
        pass
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    sampler = ProcessSampler(args.cgroup, args.io, args.full_every)
    with open(args.out, "w") as out:
        out.write(json.dumps({"clk_tck": CLK_TCK, "page": PAGE, "interval_s": args.interval,
                              "t_ns": time.monotonic_ns(), "wall_ns": time.time_ns()}) + "\n")
        next_due = time.monotonic()
        while not stop:
            out.write(json.dumps(sampler.tick(), separators=(",", ":")) + "\n")
            out.flush()
            next_due += args.interval
            time.sleep(max(0.0, next_due - time.monotonic()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
