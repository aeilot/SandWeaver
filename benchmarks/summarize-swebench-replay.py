#!/usr/bin/env python3
"""Summarize replay-swebench-all.py results: boundary state and batch divergence.

Reads the indexes (default every ~/sandweaver-runs/index*.jsonl, which
includes the per-shard ones) and each run's result.json. A boundary is the end of a recorded step that ran commands; the
lease state there is what a release would discard. Under `session` it is the
write layer accumulated since the first step; under `batch` it is only that
step's writes.

Reported per policy: boundaries with live processes, write-layer size
percentiles, the write layer at each trajectory's last boundary (under session,
the net size the trajectory left, counting each file once), the process names and path prefixes seen most often, and exit-code
mismatches against the recorded trajectory. For trajectories replayed under
both policies, the grades are compared and, where batch diverged, the first
diverging step is reported with the session state left by the step before it.

Only one variant is read (`--variant`, default "base"). Each repeat gets its
own report; with more than one repeat, `across_repeats` gives the spread of the
headline counts and which grade flips and resolutions are stable or flaky.
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


def load(indexes, variant):
    """Return {repeat: {(instance, submission, policy): result}} for one variant."""
    runs = defaultdict(dict)
    lines = [line for index in indexes for line in index.read_text().splitlines()]
    for line in lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("status") != "ok" or entry.get("variant", "base") != variant:
            continue
        result = json.loads((Path(entry["run_dir"]) / "result.json").read_text())
        runs[entry.get("repeat", 0)][(entry["instance_id"], entry["submission"],
                                      entry["policy"])] = result
    return dict(sorted(runs.items()))


# The lease setup touches these as bind-mount targets; they are always in the write layer.
DEVICE_PLACEHOLDERS = {"dev/null", "dev/zero", "dev/random", "dev/urandom"}


def boundary_stats(results):
    sizes, files, with_procs, with_files, total = [], [], 0, 0, 0
    proc_names, prefixes, categories, ports = Counter(), Counter(), Counter(), Counter()
    with_ports = with_new_fields = 0
    mismatches = commands = timeouts = 0
    final_sizes, final_categories = [], Counter()
    for result in results:
        # The last boundary's write layer: under session, what the trajectory left in
        # total (net of deletions, each file once); under batch, only the last step's.
        final = next((step["lease_state"] for step in reversed(result["steps"])
                      if "processes" in (step.get("lease_state") or {})), None)
        if final:
            final_sizes.append(final["upper_bytes"])
            final_categories.update({k: v for k, v in
                                     final.get("upper_category_bytes", {}).items()
                                     if k != "dev"})
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
            # Ports and categories exist only in runs made after they were added.
            if "listening_ports" in state:
                with_new_fields += 1
                with_ports += bool(state["listening_ports"])
                ports.update(state["listening_ports"])
                categories.update({k: v for k, v in state["upper_category_bytes"].items()
                                   if k != "dev"})
    return {
        "trajectories": len(results), "boundaries": total,
        "boundaries_with_processes": with_procs,
        "boundaries_with_upper_files": with_files,
        "upper_bytes_p50_p90_max": [pct(sizes, .5), pct(sizes, .9), max(sizes, default=None)],
        "upper_files_p50_p90_max": [pct(files, .5), pct(files, .9), max(files, default=None)],
        "process_names": proc_names.most_common(15),
        "prefixes_seen_at_boundaries": prefixes.most_common(15),
        "boundaries_with_port_data": with_new_fields,
        "boundaries_with_listening_ports": with_ports,
        "listening_ports": ports.most_common(10),
        "upper_category_bytes_summed": dict(categories),
        "final_upper_bytes_p50_p90_max": [pct(final_sizes, .5), pct(final_sizes, .9),
                                          max(final_sizes, default=None)],
        "final_upper_bytes_total": sum(final_sizes),
        "final_upper_category_bytes": dict(final_categories),
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


def resolved(result):
    return bool((result.get("grade") or {}).get("resolved"))


def summarize(runs, official):
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
        s_ok = resolved(session)
        b_ok = resolved(batch)
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
    agreement = defaultdict(lambda: {"agree": 0, "disagree": [], "no_record": 0})
    for (instance, submission, policy), result in runs.items():
        recorded = official.get((instance, submission))
        if recorded is None:
            agreement[policy]["no_record"] += 1
        elif recorded == resolved(result):
            agreement[policy]["agree"] += 1
        else:
            agreement[policy]["disagree"].append({"instance_id": instance,
                                                  "submission": submission,
                                                  "recorded_resolved": recorded})
    report["official_agreement"] = agreement
    report["paired"] = {"trajectories": pairs, "grade_flips": grade_flips,
                        "rc_divergent": len(divergent), "divergences": divergent}
    return report


def spread(values):
    return {"min": min(values), "max": max(values),
            "mean": round(sum(values) / len(values), 2)}


def across_repeats(repeats, reports):
    """Spread of headline counts, and per-trajectory stability, across repeats."""
    headline = defaultdict(list)
    for report in reports.values():
        for policy, stats in report["policies"].items():
            headline[f"{policy}_resolved"].append(stats["resolved"])
            headline[f"{policy}_rc_mismatches"].append(stats["rc_mismatches"])
            headline[f"{policy}_boundaries_with_processes"].append(
                stats["boundaries_with_processes"])
        headline["grade_flips"].append(len(report["paired"]["grade_flips"]))
        headline["rc_divergent"].append(report["paired"]["rc_divergent"])
    # Per trajectory and policy: in how many repeats it resolved.
    counts = defaultdict(lambda: defaultdict(int))
    seen = defaultdict(lambda: defaultdict(int))
    for runs in repeats.values():
        for (instance, submission, policy), result in runs.items():
            seen[(instance, submission)][policy] += 1
            counts[(instance, submission)][policy] += resolved(result)
    flaky = []
    for trajectory, by_policy in seen.items():
        for policy, n in by_policy.items():
            if 0 < counts[trajectory][policy] < n:
                flaky.append({"instance_id": trajectory[0], "submission": trajectory[1],
                              "policy": policy, "resolved": counts[trajectory][policy],
                              "of": n})
    flips = Counter()
    for report in reports.values():
        for flip in report["paired"]["grade_flips"]:
            flips[(flip["instance_id"], flip["submission"], flip["session_resolved"])] += 1
    return {
        "repeats": len(reports),
        "headline": {name: spread(values) for name, values in headline.items()},
        "flaky_resolution": sorted(flaky, key=lambda f: (f["instance_id"], f["submission"],
                                                         f["policy"])),
        "grade_flips": [{"instance_id": i, "submission": s, "session_resolved": ok,
                         "in_repeats": n} for (i, s, ok), n in sorted(flips.items())],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", type=Path, nargs="+",
                        help="Index files; default every index*.jsonl in ~/sandweaver-runs")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "sandweaver-data")
    parser.add_argument("--variant", default="base")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    indexes = args.index or sorted((Path.home() / "sandweaver-runs").glob("index*.jsonl"))
    repeats = load(indexes, args.variant)
    if not repeats:
        raise SystemExit(f"No successful runs of variant {args.variant} in {indexes}")

    # Agreement with the submission's recorded verdict, where an analysis file exists.
    official = {}
    for path in (args.data_dir / "analysis").glob("2026*.json"):
        for item in json.loads(path.read_text()):
            official[(item["instance_id"], path.stem)] = item.get("resolved")
    reports = {repeat: summarize(runs, official) for repeat, runs in repeats.items()}
    report = {"variant": args.variant, "repeats": reports}
    if len(reports) > 1:
        report["across_repeats"] = across_repeats(repeats, reports)
    text = json.dumps(report, indent=1)
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
