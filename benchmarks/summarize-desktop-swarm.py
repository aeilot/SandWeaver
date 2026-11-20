#!/usr/bin/env python3
"""Summarize desktop-swarm.py runs: one row per (N, policy).

Reads every <run>/result.json and <run>/samples.jsonl under the given
directory. Host memory in use is MemTotal - MemAvailable. Container figures
are summed over the swarm per host sample, then summarized over the replay
window (first replay start to last instance end), so boot is excluded.
"""
import argparse
import json
from pathlib import Path
import statistics

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
    samples = [json.loads(line) for line in (run / "samples.jsonl").read_text().splitlines()]
    epoch = samples[0]["t_ns"] if samples else 0
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
    # Per instance: frozen time over that instance's own replay span. The host-sample
    # share above also counts instances that already finished as not frozen.
    instance_frozen = [
        sum(s["thawed_at_ns"] - s["frozen_at_ns"] for s in i["steps"] if "frozen_at_ns" in s)
        / (i["end_ns"] - i["replay_begin_ns"])
        for i in instances if "end_ns" in i and "replay_begin_ns" in i]
    reclaims = [s["reclaim"] for s in steps if "reclaim" in s]
    ms = lambda key: [s[key] / 1e6 for s in steps if key in s]
    return {
        "run": run.name, "n": int(cfg["n"]), "policy": cfg["policy"],
        "errors": sum(1 for i in instances if "error" in i),
        "boot_s_p50": pct([i["boot_ns"] / 1e9 for i in instances if "boot_ns" in i], 0.5),
        "boot_s_max": max((i["boot_ns"] / 1e9 for i in instances if "boot_ns" in i), default=None),
        "steps": len(steps),
        "exec_fail": sum(1 for s in steps if s.get("kind") == "command" and not s.get("exec_ok")),
        "exec_ms_p50": pct(ms("exec_ns"), 0.5), "exec_ms_p95": pct(ms("exec_ns"), 0.95),
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
