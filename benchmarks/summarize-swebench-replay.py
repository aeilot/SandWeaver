#!/usr/bin/env python3
"""Summarize replay-swebench-all.py results: boundary state and batch divergence.

Reads the index (default ~/sandweaver-runs/index.jsonl) and each run's
result.json. A boundary is the end of a recorded step that ran commands; the
lease state there is what a release would discard. Under `session` it is the
write layer accumulated since the first step; under `batch` it is only that
step's writes.

Reported per policy: boundaries with live processes, write-layer size
percentiles, the process names and path prefixes seen most often, and exit-code
mismatches against the recorded trajectory. For trajectories replayed under
both policies, the grades are compared and, where batch diverged, the first
diverging step is reported with the session state left by the step before it.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


def pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def load(index):
    runs = {}
    for line in index.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("status") != "ok":
            continue
        result = json.loads((Path(entry["run_dir"]) / "result.json").read_text())
        runs[(entry["instance_id"], entry["submission"], entry["policy"])] = result
    return runs


# The lease setup touches these as bind-mount targets; they are always in the write layer.
DEVICE_PLACEHOLDERS = {"dev/null", "dev/zero", "dev/random", "dev/urandom"}


def boundary_stats(results):
    sizes, files, with_procs, with_files, total = [], [], 0, 0, 0
    proc_names, prefixes = Counter(), Counter()
    mismatches = commands = timeouts = 0
    for result in results:
        for step in result["steps"]:
            for command in step["commands"]:
                commands += 1
                mismatches += not command["rc_match"]
                timeouts += command["timed_out"]
            state = step.get("lease_state")
            if not state or "processes" not in state:
                continue
            total += 1
            seen = set(state["upper_prefix_bytes"]) - DEVICE_PLACEHOLDERS
            sizes.append(state["upper_bytes"])
            files.append(state["upper_files"] - len(DEVICE_PLACEHOLDERS
                                                    & set(state["upper_prefix_bytes"])))
            if seen:
                with_files += 1
            if state["processes"]:
                with_procs += 1
                proc_names.update(set(state["processes"]))
            prefixes.update(seen)
    return {
        "trajectories": len(results), "boundaries": total,
        "boundaries_with_processes": with_procs,
        "boundaries_with_upper_files": with_files,
        "upper_bytes_p50_p90_max": [pct(sizes, .5), pct(sizes, .9), max(sizes, default=None)],
        "upper_files_p50_p90_max": [pct(files, .5), pct(files, .9), max(files, default=None)],
        "process_names": proc_names.most_common(15),
        "prefixes_seen_at_boundaries": prefixes.most_common(15),
        "commands": commands, "rc_mismatches": mismatches, "timeouts": timeouts,
        "resolved": sum(bool((r.get("grade") or {}).get("resolved")) for r in results),
    }


def first_divergence(session, batch):
    for s_step, b_step in zip(session["steps"], batch["steps"]):
        s_rc = [c["exit_code"] for c in s_step["commands"]]
        b_rc = [c["exit_code"] for c in b_step["commands"]]
        if s_rc != b_rc:
            return s_step["index"], s_rc, b_rc
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", type=Path, default=Path.home() / "sandweaver-runs/index.jsonl")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "sandweaver-data")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runs = load(args.index)

    by_policy = defaultdict(list)
    for (_, _, policy), result in runs.items():
        by_policy[policy].append(result)
    report = {"policies": {p: boundary_stats(r) for p, r in sorted(by_policy.items())}}

    pairs, grade_flips, divergent = 0, [], []
    for (instance, submission, policy), session in runs.items():
        if policy != "session" or (instance, submission, "batch") not in runs:
            continue
        batch = runs[(instance, submission, "batch")]
        pairs += 1
        s_ok = bool((session.get("grade") or {}).get("resolved"))
        b_ok = bool((batch.get("grade") or {}).get("resolved"))
        if s_ok != b_ok:
            grade_flips.append({"instance_id": instance, "submission": submission,
                                "session_resolved": s_ok, "batch_resolved": b_ok})
        found = first_divergence(session, batch)
        if found:
            index, s_rc, b_rc = found
            before = session["steps"][index - 1].get("lease_state", {}) if index else {}
            divergent.append({
                "instance_id": instance, "submission": submission, "step": index,
                "session_rc": s_rc, "batch_rc": b_rc,
                "session_state_before": {k: before.get(k) for k in
                                         ("processes", "upper_files", "upper_bytes",
                                          "upper_prefix_bytes")},
            })
    # Agreement with the submission's recorded verdict, where an analysis file exists.
    official = {}
    for path in (args.data_dir / "analysis").glob("2026*.json"):
        for item in json.loads(path.read_text()):
            official[(item["instance_id"], path.stem)] = item.get("resolved")
    agreement = defaultdict(lambda: {"agree": 0, "disagree": [], "no_record": 0})
    for (instance, submission, policy), result in runs.items():
        recorded = official.get((instance, submission))
        if recorded is None:
            agreement[policy]["no_record"] += 1
        elif recorded == bool((result.get("grade") or {}).get("resolved")):
            agreement[policy]["agree"] += 1
        else:
            agreement[policy]["disagree"].append({"instance_id": instance,
                                                  "submission": submission,
                                                  "recorded_resolved": recorded})
    report["official_agreement"] = agreement
    report["paired"] = {"trajectories": pairs, "grade_flips": grade_flips,
                        "rc_divergent": len(divergent), "divergences": divergent}
    text = json.dumps(report, indent=1)
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
