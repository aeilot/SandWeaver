#!/usr/bin/env python3
"""Summarize characterization runs made with replay-swebench.py --sample --wait-scale.

For every result.json under RUNS_DIR, reports:

- RQ1 phase structure: replayed model-wait time against command time, and the
  share of the lease lifetime spent executing commands.
- RQ2 occupancy against use: worker cgroup CPU utilisation and memory (anon and
  file pages separately) during waits and during commands.
- RQ3 state at wait boundaries: how many waits begin with live processes,
  listening ports or a non-empty write layer, by write-layer category.

It also writes one row per wait boundary (wait length, live state, write-layer
bytes) to CSV, the x-axis and colour of the decision plot. Recovery cost (RQ4)
is not measured here.

The cgroup is the worker container's; see sandweaver/sampler.py for what that
includes. Replayed waits are the recorded ones scaled by wait_scale; they are
not new model calls.
"""
import argparse
import csv
import json
from pathlib import Path


def pct(values, q):
    values = sorted(v for v in values if v is not None)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def dist(values):
    return {"n": len([v for v in values if v is not None]), "p50": pct(values, .5),
            "p90": pct(values, .9), "max": max((v for v in values if v is not None), default=None)}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs_dir", type=Path)
    parser.add_argument("--output", type=Path, help="JSON summary path")
    parser.add_argument("--points", type=Path, help="CSV of wait boundaries")
    args = parser.parse_args()

    runs, points = [], []
    wait_cpu, wait_anon, wait_file, cmd_cpu, cmd_anon = [], [], [], [], []
    boundaries = with_procs = with_ports = with_upper = 0
    categories = {}
    for path in sorted(args.runs_dir.glob("*/result.json")):
        result = json.loads(path.read_text())
        if not result.get("wait_scale") or "sampler" not in result:
            continue
        steps = result["steps"]
        wait_s = sum(s.get("wait_ns", 0) for s in steps) / 1e9
        exec_s = sum(c["exec_ns"] for s in steps for c in s["commands"]) / 1e9
        runs.append({"instance_id": result["instance_id"], "submission": result["submission"],
                     "policy": result["policy"], "steps": len(steps),
                     "wait_s": round(wait_s, 1), "exec_s": round(exec_s, 1),
                     "exec_share": round(exec_s / (wait_s + exec_s), 4) if wait_s + exec_s else None,
                     "sampler": list(result["sampler"].values())})
        previous_state = None
        for step in steps:
            usage = step.get("wait_usage")
            if usage:
                wait_cpu.append(usage["cpu_util"])
                wait_anon.append(usage.get("memory_anon_max"))
                wait_file.append(usage.get("memory_file_max"))
            for command in step["commands"]:
                if command.get("usage"):
                    cmd_cpu.append(command["usage"]["cpu_util"])
                    cmd_anon.append(command["usage"].get("memory_anon_max"))
            # The state a release at the start of this wait would discard is the
            # state left by the previous step.
            if "wait_ns" in step and previous_state and "processes" in previous_state:
                boundaries += 1
                procs = previous_state["processes"]
                ports = previous_state.get("listening_ports", [])
                cats = {k: v for k, v in previous_state.get("upper_category_bytes", {}).items()
                        if k != "dev" and v}
                with_procs += bool(procs)
                with_ports += bool(ports)
                with_upper += bool(cats)
                # The write layer accumulates over a session, so summing across
                # boundaries would count the same files repeatedly; keep the largest.
                for k, v in cats.items():
                    categories[k] = max(categories.get(k, 0), v)
                points.append({"instance_id": result["instance_id"], "step": step["index"],
                               "wait_s": round(step["wait_ns"] / 1e9, 3),
                               "live_processes": len(procs), "listening_ports": len(ports),
                               "upper_bytes": sum(cats.values()),
                               "safe_to_release": not procs and not cats})
            if step.get("lease_state"):
                previous_state = step["lease_state"]

    report = {
        "runs": runs,
        "rq1": {"wait_s_total": round(sum(r["wait_s"] for r in runs), 1),
                "exec_s_total": round(sum(r["exec_s"] for r in runs), 1),
                "wait_s_per_boundary": dist([p["wait_s"] for p in points])},
        "rq2": {"wait_cpu_util": dist(wait_cpu), "wait_memory_anon_max": dist(wait_anon),
                "wait_memory_file_max": dist(wait_file), "command_cpu_util": dist(cmd_cpu),
                "command_memory_anon_max": dist(cmd_anon)},
        "rq3": {"wait_boundaries": boundaries, "with_live_processes": with_procs,
                "with_listening_ports": with_ports, "with_upper_files": with_upper,
                "upper_files_only": sum(1 for p in points
                                        if p["upper_bytes"] and not p["live_processes"]),
                "nothing_to_lose": sum(p["safe_to_release"] for p in points),
                "upper_bytes_per_boundary": dist([p["upper_bytes"] for p in points]),
                "upper_category_bytes_max": categories},
    }
    total = report["rq1"]["wait_s_total"] + report["rq1"]["exec_s_total"]
    report["rq1"]["exec_share"] = round(report["rq1"]["exec_s_total"] / total, 4) if total else None
    text = json.dumps(report, indent=1)
    if args.output:
        args.output.write_text(text)
    if args.points and points:
        with args.points.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(points[0]))
            writer.writeheader()
            writer.writerows(points)
    print(text)


if __name__ == "__main__":
    main()
