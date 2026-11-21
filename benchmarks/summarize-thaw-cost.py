#!/usr/bin/env python3
"""Measure what the first action after a thaw pays for, per desktop-swarm.py run.

For every step that ran a command, takes the container's cgroup counters
(sampled by desktop-swarm.py every --host-interval seconds) from the last
sample before the action began to the first sample after its screenshot ended,
and reports major faults, file refaults (workingset_refault_file), memory and
IO stall time (memory.pressure / io.pressure "some" totals) and bytes read
(io.stat rbytes). Steps whose previous wait ended in a thaw are reported apart
from the others. The window is widened to sample boundaries, so the counts
include up to one sample interval on each side of the action.

For freeze-reclaim runs it also prints the Pearson correlation between the
execution time of the step after a thaw and each counter, and the amount the
preceding reclaim freed.

Usage: summarize-thaw-cost.py RUN_DIR [RUN_DIR ...] [--json]
"""
import argparse
import bisect
import collections
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


FIELDS = {
    "majflt": ("pgmajfault", 1),
    "refault_file": ("workingset_refault_file", 1),
    "mem_stall_ms": ("psi_memory_some_us", 1e3),
    "io_stall_ms": ("psi_io_some_us", 1e3),
    "read_mib": ("io_rbytes", 2 ** 20),
}


def steps(run):
    """One row per command step: exec time, counter deltas, and whether it followed a thaw."""
    result = json.loads((run / "result.json").read_text())
    epoch = result["epoch_ns"]
    series = collections.defaultdict(list)
    for line in read_text(run / "samples.jsonl").splitlines():
        sample = json.loads(line)
        for name, values in (sample.get("containers") or {}).items():
            series[name].append(values)
    rows = []
    for inst in result["instances"]:
        samples = series[inst["name"]]
        times = [s["t_ns"] - epoch for s in samples]
        for i, step in enumerate(inst["steps"]):
            if step.get("kind") != "command":
                continue
            prev = inst["steps"][i - 1] if i else {}
            begin = step["action_begin_ns"]
            end = begin + step["exec_ns"] + step.get("shot_ns", 0)
            lo = bisect.bisect_right(times, begin) - 1
            hi = bisect.bisect_left(times, end)
            if lo < 0 or hi >= len(samples):
                continue
            row = {"instance": inst["name"], "step": step["step"],
                   "after_thaw": "thawed_at_ns" in prev,
                   "exec_ms": step["exec_ns"] / 1e6}
            for key, (field, scale) in FIELDS.items():
                row[key] = (samples[hi][field] - samples[lo][field]) / scale
            reclaim = prev.get("reclaim")
            row["reclaimed_mib"] = ((reclaim["before"] - reclaim["after"]) / 2 ** 20
                                    if reclaim else None)
            rows.append(row)
    return result["config"], rows


def pearson(xs, ys):
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)


def summarize(run):
    config, rows = steps(run)
    out = {"run": run.name, "n": int(config["n"]), "policy": config["policy"], "groups": {}}
    for label, after in (("after_thaw", True), ("other", False)):
        sel = [r for r in rows if r["after_thaw"] is after]
        if not sel:
            continue
        group = {"steps": len(sel),
                 "exec_ms_p50": round(statistics.median(r["exec_ms"] for r in sel), 1)}
        for key in FIELDS:
            group[f"{key}_mean"] = round(statistics.fmean(r[key] for r in sel), 1)
            group[f"{key}_p50"] = round(statistics.median(r[key] for r in sel), 1)
        out["groups"][label] = group
    thawed = [r for r in rows if r["after_thaw"] and r["reclaimed_mib"] is not None]
    if thawed:
        execs = [r["exec_ms"] for r in thawed]
        out["corr_exec_after_thaw"] = {key: pearson(execs, [r[key] for r in thawed])
                                       for key in list(FIELDS) + ["reclaimed_mib"]}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = [summarize(run) for run in args.runs if (run / "result.json").exists()]
    results.sort(key=lambda r: (r["n"], r["policy"]))
    if args.json:
        print(json.dumps(results, indent=1))
        return
    for res in results:
        print(f"== {res['run']}")
        for label, g in res["groups"].items():
            print(f"  {label:10s} steps {g['steps']:3d}  exec p50 {g['exec_ms_p50']:6.0f} ms"
                  f"  majflt p50 {g['majflt_p50']:5.0f}  refault mean {g['refault_file_mean']:7.0f}"
                  f"  io stall mean {g['io_stall_ms_mean']:6.1f} ms"
                  f"  mem stall mean {g['mem_stall_ms_mean']:5.1f} ms"
                  f"  read mean {g['read_mib_mean']:5.1f} MiB")
        if "corr_exec_after_thaw" in res:
            print("  r(exec after thaw, x):", ", ".join(
                f"{k} {v}" for k, v in res["corr_exec_after_thaw"].items()))


if __name__ == "__main__":
    main()
