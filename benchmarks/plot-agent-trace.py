#!/usr/bin/env python3
"""Render timing metadata using matplotlib (an optional analysis dependency)."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("trace", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
records = [json.loads(line) for line in args.trace.read_text().splitlines()]
starts = {}
spans = []
lease_start = None
lease_end = None
events = []
mode = "unknown"
for record in records:
    timestamp = record["elapsed_ns"] / 1e9
    if record["event"] == "span_start":
        starts[record["span"]] = (record["name"], timestamp)
    elif record["event"] == "span_end":
        name, start = starts.pop(record["span"])
        spans.append((name, start, timestamp, record["outcome"]))
    elif record["event"] == "lease_acquired":
        lease_start = timestamp
    elif record["event"] == "lease_released":
        lease_end = timestamp
    elif record["event"] == "sdk_event":
        events.append(timestamp)
    elif record["event"] == "run_mode":
        mode = record["mode"]
if starts or lease_start is None or lease_end is None:
    raise ValueError("Trace is incomplete; cannot render a completed run")

fig, ax = plt.subplots(figsize=(12, 4.8), layout="constrained")
colors = {"claim": "#d69e2e", "exec": "#247ba0", "release": "#d69e2e",
          "conversation_run": "#dddddd", "llm_call": "#8c6bb1"}
ax.broken_barh([(lease_start, lease_end - lease_start)], (2.7, .6), facecolors="#a9c9a4")
tool_number = 0
for name, start, end, outcome in sorted(spans, key=lambda row: row[0] != "conversation_run"):
    lane = 1 if name == "exec" else 2
    if name in ("conversation_run", "llm_call"):
        lane = 0
    ax.broken_barh([(start, end - start)], (lane - .3, .6),
                  facecolors=colors[name] if outcome == "ok" else "#d1495b")
    if name == "exec":
        tool_number += 1
        ax.annotate(str(tool_number), ((start + end) / 2, lane + (.35 if tool_number % 2 else .62)),
                    ha="center", fontsize=9)
    elif name not in ("conversation_run", "llm_call"):
        ax.annotate(name, ((start + end) / 2, lane + .35),
                    ha="center", fontsize=9)
ax.scatter(events, [-1] * len(events), marker="|", color="#555555", s=100)
ax.set_yticks([-1, 0, 1, 2, 3],
              ["SDK events", "Conversation run", "Shell tools", "Lease requests", "Lease held"])
ax.set_xlabel("Seconds since tracing started (monotonic clock)")
ax.set_title(f"SandWeaver agent timeline — {mode}", loc="left", weight="bold")
ax.set_ylim(-1.6, 3.8)
ax.set_xlim(left=0)
ax.grid(axis="x", alpha=.2)
for side in ("top", "right"):
    ax.spines[side].set_visible(False)
tool_seconds = sum(end - start for name, start, end, _ in spans if name == "exec")
fig.supxlabel(
    f"Lease held: {lease_end-lease_start:.3f}s | Shell round trips: {tool_seconds:.3f}s\n"
    "Purple: model client calls (including network / retries). Blank intervals are unclassified.",
    fontsize=9,
)
fig.savefig(args.output, dpi=180)
print(json.dumps({"mode": mode, "lease_seconds": lease_end - lease_start,
                  "shell_round_trip_seconds": tool_seconds, "sdk_events": len(events)}))
