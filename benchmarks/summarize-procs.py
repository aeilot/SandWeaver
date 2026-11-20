#!/usr/bin/env python3
"""Attribute per-process CPU and major faults to replay phases.

Reads the per-process ticks written by sandweaver/procs.py, either from a
desktop-swarm.py run (procs.jsonl, one stream per container) or from an
osworld-replay.py run (guest-procs.jsonl, every guest process), and splits each
process's CPU time and major faults across the phases of the replay:

  action      executing the recorded action and taking the screenshot
  wait 0-10s  the first 10 s of the wait after an action (the aftershock)
  wait >10s   the rest of the wait
  frozen      the container was frozen (swarm freeze policies only)
  idle tail   after the last step (osworld-replay --idle-tail only)

A tick lists a process only when its counters changed, so a change seen at
tick k happened between ticks k-1 and k; it is attributed to the phase that
contains the midpoint of that interval. Guest timestamps are mapped to the
host clock with the probes osworld-replay.py records (error up to half the
probe's round trip). Process names are grouped: digits and kernel-thread
suffixes are dropped (kworker/3:1-events -> kworker).

Usage: summarize-procs.py RUN_DIR [RUN_DIR ...] [--top 12] [--json]
"""
import argparse
import bisect
import collections
import json
from pathlib import Path
import re

AFTERSHOCK_S = 10.0


def group(comm):
    comm = comm.split("/")[0]
    return re.sub(r"[-_:.]?\d+$", "", comm) or comm


def swarm_phases(result):
    """{container name: sorted [(start_ns, end_ns, phase)]} on the run's epoch clock."""
    epoch = result.get("epoch_ns")
    out = {}
    for inst in result.get("instances", []):
        spans = []
        steps = inst.get("steps", [])
        for i, step in enumerate(steps):
            begin = step["action_begin_ns"]
            done = begin + step.get("exec_ns", 0) + step.get("shot_ns", 0)
            spans.append((begin, done, "action"))
            nxt = steps[i + 1]["action_begin_ns"] if i + 1 < len(steps) else inst.get("end_ns", done)
            if "frozen_at_ns" in step:
                spans.append((done, step["frozen_at_ns"], "wait 0-10s"))
                spans.append((step["frozen_at_ns"], step["thawed_at_ns"], "frozen"))
                spans.append((step["thawed_at_ns"], nxt, "wait >10s"))
            else:
                cut = min(nxt, done + int(AFTERSHOCK_S * 1e9))
                spans.append((done, cut, "wait 0-10s"))
                spans.append((cut, nxt, "wait >10s"))
        out[inst["name"]] = (epoch, sorted(spans))
    return out


def vm_phases(result):
    spans = []
    steps = result.get("steps", [])
    for step in steps:
        begin = step["action_begin_ns"]
        done = begin + step["action_ns"]
        spans.append((begin, done, "action"))
        if "wait_ns" in step:
            end = step["wait_begin_ns"] + step["wait_ns"]
            cut = min(end, done + int(AFTERSHOCK_S * 1e9))
            spans.append((done, cut, "wait 0-10s"))
            spans.append((cut, end, "wait >10s"))
    if "idle_tail_begin_ns" in result:
        spans.append((result["idle_tail_begin_ns"],
                      result["idle_tail_begin_ns"] + result["idle_tail_ns"], "idle tail"))
    return sorted(spans)


def phase_at(spans, t):
    starts = [s[0] for s in spans]
    i = bisect.bisect_right(starts, t) - 1
    if i >= 0 and spans[i][0] <= t < spans[i][1]:
        return spans[i][2]
    return None


def attribute(ticks, to_host, spans, clk_tck, cpu, faults, seconds):
    """Add per-(phase, group) CPU seconds and major faults from one tick stream."""
    last = {}
    prev_t = None
    for tick in ticks:
        t = to_host(tick[to_host.key])
        phase = phase_at(spans, (prev_t + t) // 2) if prev_t is not None else None
        if phase:
            seconds[phase] += (t - prev_t) / 1e9
        for pid, row in tick["procs"].items():
            key = (pid, row[6])  # (pid, start time) survives pid reuse
            if phase and key in last:
                old = last[key]
                name = group(row[0])
                cpu[phase][name] += ((row[1] + row[2]) - (old[1] + old[2])) / clk_tck
                faults[phase][name] += row[4] - old[4]
            last[key] = row
        prev_t = t


class Clock:
    """Maps a tick's timestamp field (`key`) to the host clock of the phase spans."""

    def __init__(self, fn, key):
        self.fn, self.key = fn, key

    def __call__(self, t):
        return self.fn(t)


def summarize(run, top):
    result = json.loads((run / "result.json").read_text())
    cpu = collections.defaultdict(collections.Counter)
    faults = collections.defaultdict(collections.Counter)
    seconds = collections.Counter()
    if (run / "procs.jsonl").exists():
        phases = swarm_phases(result)
        streams = collections.defaultdict(list)
        for line in (run / "procs.jsonl").read_text().splitlines():
            tick = json.loads(line)
            streams[tick["container"]].append(tick)
        for name, ticks in streams.items():
            epoch, spans = phases.get(name, (None, []))
            if epoch is None or not spans:
                continue
            clock = Clock(lambda t, e=epoch: t - e, "t_ns")
            # Host ticks carry no header; Linux USER_HZ is 100.
            attribute(ticks, clock, spans, 100, cpu, faults, seconds)
        kind = "swarm"
    elif (run / "guest-procs.jsonl").exists():
        lines = (run / "guest-procs.jsonl").read_text().splitlines()
        header, ticks = json.loads(lines[0]), [json.loads(x) for x in lines[1:]]
        probes = [result[k] for k in ("guest_probe_start", "guest_probe_end") if k in result]
        offsets = [p["guest_wall_ns"] - (p["host_before_ns"] + p["host_after_ns"]) // 2
                   for p in probes]
        offset = sum(offsets) // len(offsets)
        clock = Clock(lambda w: w - offset, "wall_ns")
        attribute(ticks, clock, vm_phases(result), header["clk_tck"], cpu, faults, seconds)
        kind = "vm"
    else:
        return None
    rows = {}
    for phase in sorted(seconds):
        total = sum(cpu[phase].values())
        span = seconds[phase]
        rows[phase] = {
            "seconds": round(span, 1),
            "cores": round(total / span, 3) if span else None,
            "top": [(name, round(value / span, 3), round(value / total, 3) if total else None,
                     faults[phase][name])
                    for name, value in cpu[phase].most_common(top)],
            "majflt_per_s": round(sum(faults[phase].values()) / span, 1) if span else None,
        }
    out = {"run": run.name, "kind": kind, "phases": rows}
    if kind == "vm":
        out["clock_offset_spread_ms"] = (abs(offsets[0] - offsets[-1]) / 1e6
                                         if len(offsets) > 1 else None)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = [r for r in (summarize(run, args.top) for run in args.runs) if r]
    if args.json:
        print(json.dumps(results, indent=1))
        return
    for res in results:
        print(f"== {res['run']} ({res['kind']})")
        for phase, row in res["phases"].items():
            print(f"  {phase:11s} {row['seconds']:8.1f}s  {row['cores']} cores"
                  f"  majflt/s {row['majflt_per_s']}")
            for name, cores, share, majflt in row["top"]:
                print(f"      {name:24s} {cores:6.3f}  {share:6.1%}  majflt {majflt}")


if __name__ == "__main__":
    main()
