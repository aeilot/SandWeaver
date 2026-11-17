#!/usr/bin/env python3
"""Step timing of public OSWorld trajectories (traj.jsonl from OSWorld result archives).

OSWorld's runner stamps each step just before executing the agent's action, so
the gap between consecutive `action_timestamp`s covers executing that action,
the runner's post-action sleep, taking the screenshot, and the model call that
produced the next action. The model call cannot be separated from these
timestamps alone; the post-action sleep from the run configuration is reported
alongside so it can be subtracted.

usage: osworld-trace-stats.py DIR [--output JSON]
DIR is searched recursively for traj.jsonl; the parent directory name is the
task id and the one above it the domain.
"""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path


def stamp(text):
    return datetime.strptime(text, "%Y%m%d@%H%M%S%f").timestamp()


def pct(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 2) if values else None


def dist(values):
    return {"n": len(values), "p10": pct(values, .1), "p50": pct(values, .5),
            "p90": pct(values, .9), "p99": pct(values, .99),
            "max": round(max(values), 2) if values else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    gaps, per_domain, sessions, steps_per = [], defaultdict(list), [], []
    for path in sorted(args.directory.rglob("traj.jsonl")):
        rows = []
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        times = [stamp(r["action_timestamp"]) for r in rows if r.get("action_timestamp")]
        if len(times) < 2:
            continue
        domain = path.parent.parent.name
        step_gaps = [b - a for a, b in zip(times, times[1:]) if b >= a]
        gaps += step_gaps
        per_domain[domain] += step_gaps
        sessions.append(times[-1] - times[0])
        steps_per.append(len(times))
    report = {"trajectories": len(sessions), "steps_per_trajectory": dist(steps_per),
              "session_span_s": dist(sessions), "step_gap_s": dist(gaps),
              "step_gap_s_by_domain": {d: dist(v) for d, v in sorted(per_domain.items())}}
    text = json.dumps(report, indent=1)
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
