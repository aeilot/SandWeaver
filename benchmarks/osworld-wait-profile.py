#!/usr/bin/env python3
"""Profile desktop CPU during agent waits by time since the wait began.

Reads result.json and samples.jsonl written by osworld-replay.py under RUN_DIR
and prints, per domain, the VM cgroup's mean CPU (cores) in bins of seconds
since the previous action ended, plus the idle-tail CPU after the task.
"""
import argparse
import json
from pathlib import Path

BINS = [(0, 1), (1, 2), (2, 5), (5, 10), (10, 20), (20, float("inf"))]


def profile(result, samples):
    acc = {b: [0.0, 0.0] for b in BINS}  # cpu seconds, wall seconds
    for step in result["steps"]:
        begin = step.get("wait_begin_ns")
        if begin is None:
            continue
        end = begin + step["wait_ns"]
        for a, b in zip(samples, samples[1:]):
            if a["t_ns"] < begin or b["t_ns"] > end:
                continue
            rel = (a["t_ns"] - begin) / 1e9
            for lo, hi in BINS:
                if lo <= rel < hi:
                    acc[(lo, hi)][0] += (b["cpu_usage_usec"] - a["cpu_usage_usec"]) / 1e6
                    acc[(lo, hi)][1] += (b["t_ns"] - a["t_ns"]) / 1e9
                    break
    return {f"{lo}-{hi}s": (round(c / w, 3) if w else None) for (lo, hi), (c, w) in acc.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.run_dir.glob("*/result.json")):
        result = json.loads(path.read_text())
        samples = [json.loads(line) for line in (path.parent / "samples.jsonl").read_text().splitlines()]
        rows.append({"domain": result["domain"], "task_id": result["task_id"],
                     "wait_cpu_by_age": profile(result, samples),
                     "idle_tail_cpu": result.get("idle_tail_usage", {}).get("cpu_util")})
    for row in rows:
        cells = " ".join(f"{k}={'-' if v is None else f'{v:.2f}'}" for k, v in row["wait_cpu_by_age"].items())
        print(f"{row['domain']:22s} {cells} idle={row['idle_tail_cpu']:.2f}")
    if args.output:
        args.output.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
