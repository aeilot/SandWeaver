#!/usr/bin/env python3
"""Summarize desktop-swarm.py runs: one row per (N, policy).

Reads every <run>/result.json and <run>/samples.jsonl under the given
directory. Host memory in use is MemTotal - MemAvailable. Container figures
are summed over the swarm per host sample, then summarized over the replay
window (first replay start to last instance end). That window excludes the
first instance's boot but not the others': with staggered starts, instances
keep booting until the last replay starts. Host CPU is therefore also reported
separately for the boot phase (run start to last replay start) and the
all-booted phase (last replay start to last instance end). Execution latency
counts only steps that ran a command.
"""
import argparse
import gzip
import json
from pathlib import Path
import statistics


def read_text(path):
    """Read a raw output file, or its gzipped copy (path + ".gz") from docs/results/raw."""
    path = Path(path)
    if not path.exists() and path.with_name(path.name + ".gz").exists():
        return gzip.decompress(path.with_name(path.name + ".gz").read_bytes()).decode()
    return path.read_text()


GIB = 1024 ** 3


def pct(values, q):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]


def summarize(run):
    result = json.loads((run / "result.json").read_text())
    cfg = result["config"]
    instances = result.get("instances", [])
    steps = [s for i in instances for s in i["steps"]]
    starts = [i["replay_begin_ns"] for i in instances if "replay_begin_ns" in i]
    ends = [i["end_ns"] for i in instances if "end_ns" in i]
    samples = [json.loads(line) for line in read_text(run / "samples.jsonl").splitlines()]
    epoch = result.get("epoch_ns") or (samples[0]["t_ns"] if samples else 0)
    # samples carry absolute monotonic ns; result times are relative to the runner's epoch,
    # which is a few ms before the first sample.
    lo, hi = (min(starts), max(ends)) if starts else (0, 0)
    window = [s for s in samples if lo <= s["t_ns"] - epoch <= hi]
    used = [(s["mem"]["MemTotal"] - s["mem"]["MemAvailable"]) / GIB for s in window]
    anon = [s["mem"]["AnonPages"] / GIB for s in window]
    sums = {k: [] for k in ("memory_current", "memory_anon", "memory_file", "memory_shmem")}
    frozen_share = []
    for s in window:
        live = [c for c in s["containers"].values() if c]
        for key in sums:
            sums[key].append(sum(c.get(key, 0) for c in live) / GIB)
        if live:
            frozen_share.append(sum(1 for c in live if c.get("frozen")) / len(live))
    pss = [c["pss"] / GIB for s in window for c in s["containers"].values() if c and "pss" in c]
    private = [c["private"] / GIB for s in window for c in s["containers"].values()
               if c and "private" in c]
    cpu = []
    for a, b in zip(window, window[1:]):
        total = b["cpu"]["total_ticks"] - a["cpu"]["total_ticks"]
        if total:
            cpu.append((b["cpu"]["busy_ticks"] - a["cpu"]["busy_ticks"]) / total * result["cpus"])
    psi_mem = [s["psi_memory"]["some"]["avg10"] for s in window]
    psi_cpu = [s["psi_cpu"]["some"]["avg10"] for s in window]
    # Phases of the window: some instances still boot until the last replay starts.
    all_booted = max(starts) if starts else 0

    def cores_between(a_ns, b_ns):
        part = [s for s in samples if a_ns <= s["t_ns"] - epoch <= b_ns]
        if len(part) < 2:
            return None
        busy = part[-1]["cpu"]["busy_ticks"] - part[0]["cpu"]["busy_ticks"]
        return busy / (part[-1]["cpu"]["total_ticks"] - part[0]["cpu"]["total_ticks"]) * result["cpus"]

    # Per instance: frozen time over that instance's own replay span. The host-sample
    # share above also counts instances that already finished as not frozen.
    instance_frozen = [
        sum(s["thawed_at_ns"] - s["frozen_at_ns"] for s in i["steps"] if "frozen_at_ns" in s)
        / (i["end_ns"] - i["replay_begin_ns"])
        for i in instances if "end_ns" in i and "replay_begin_ns" in i]
    reclaims = [s["reclaim"] for s in steps if "reclaim" in s]
    ms = lambda key: [s[key] / 1e6 for s in steps if key in s]
    # Execution latency only for steps that ran a command; DONE, FAIL and WAIT
    # steps execute nothing and would pull the percentiles down.
    exec_ms = [s["exec_ns"] / 1e6 for s in steps if s.get("kind") == "command"]
    return {
        "run": run.name, "n": int(cfg["n"]), "policy": cfg["policy"],
        "errors": sum(1 for i in instances if "error" in i),
        "boot_s_p50": pct([i["boot_ns"] / 1e9 for i in instances if "boot_ns" in i], 0.5),
        "boot_s_max": max((i["boot_ns"] / 1e9 for i in instances if "boot_ns" in i), default=None),
        "steps": len(steps),
        "exec_fail": sum(1 for s in steps if s.get("kind") == "command" and not s.get("exec_ok")),
        "exec_ms_p50": pct(exec_ms, 0.5), "exec_ms_p95": pct(exec_ms, 0.95),
        "shot_ms_p50": pct(ms("shot_ns"), 0.5), "shot_ms_p95": pct(ms("shot_ns"), 0.95),
        "freeze_ms_p95": pct(ms("freeze_ns"), 0.95), "thaw_ms_p50": pct(ms("thaw_ns"), 0.5),
        "thaw_ms_p95": pct(ms("thaw_ns"), 0.95), "thaw_ms_max": max(ms("thaw_ns"), default=None),
        "freezes": len(ms("freeze_ns")),
        "reclaim_mib_mean": (statistics.mean((r["before"] - r["after"]) / 2**20 for r in reclaims)
                             if reclaims else None),
        "reclaim_ms_p50": pct([r["reclaim_ns"] / 1e6 for r in reclaims], 0.5),
        "frozen_share_mean": statistics.mean(frozen_share) if frozen_share else None,
        "instance_frozen_share_mean": (statistics.mean(instance_frozen)
                                       if instance_frozen else None),
        "host_used_gib_mean": statistics.mean(used) if used else None,
        "host_used_gib_max": max(used, default=None),
        "host_anon_gib_max": max(anon, default=None),
        "swarm_current_gib_mean": statistics.mean(sums["memory_current"]) if window else None,
        "swarm_anon_gib_mean": statistics.mean(sums["memory_anon"]) if window else None,
        "swarm_anon_gib_max": max(sums["memory_anon"], default=None),
        "swarm_file_gib_mean": statistics.mean(sums["memory_file"]) if window else None,
        "per_desktop_pss_gib_p50": pct(pss, 0.5), "per_desktop_private_gib_p50": pct(private, 0.5),
        "host_cpu_cores_mean": statistics.mean(cpu) if cpu else None,
        "host_cpu_cores_p95": pct(cpu, 0.95),
        # Run start to the last replay start (instances still booting), and from
        # there to the last instance's end (all booted; replaying or idle).
        "host_cpu_cores_boot_phase": cores_between(0, all_booted),
        "host_cpu_cores_all_booted": cores_between(all_booted, hi),
        "psi_mem_some_avg10_max": max(psi_mem, default=None),
        "psi_cpu_some_avg10_mean": statistics.mean(psi_cpu) if psi_cpu else None,
        "window_s": (hi - lo) / 1e9,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = [summarize(p.parent) for p in sorted(args.directory.glob("*/result.json"))]
    rows.sort(key=lambda r: (r["n"], ["always", "freeze", "freeze-reclaim"].index(r["policy"])))
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    for row in rows:
        print(" ".join(f"{k}={round(v, 2) if isinstance(v, float) else v}" for k, v in row.items()))


if __name__ == "__main__":
    main()
