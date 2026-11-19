#!/usr/bin/env python3
"""Replay every selected SWE-bench Multilingual trajectory and grade it.

Runs replay-swebench.py (with --evaluate) and then grade-swebench.py for each
task in swebench-ml-selection.json, each submission that has a trajectory for
it, and each requested policy. Policies for one trajectory run back to back so
the task image stays warm. Results already in the index are skipped, so the
driver can be stopped and restarted. One JSON line per attempt is appended to
INDEX (default RUNS_DIR/index.jsonl); the per-run result.json stays in its run
directory.

A variant names one replay configuration (`--cap`, `--sample`, `--wait-scale`,
`--wait-cap`); `--repeats` replays every trajectory that many times under it.
Attempts are keyed by (instance, submission, policy, variant, repeat), so
variants and repeats can share an index; index lines written before variants
existed count as variant "base", repeat 0. Repeats are the outer loop, so a
stopped run has covered every trajectory once before it starts repeating.

Runs are sequential: each replay starts its own one-worker scheduler.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


# Index lines from before variants were replayed with the driver's defaults.
BASE_OPTIONS = {"cap": None, "sample": None, "wait_scale": 0, "wait_cap": None}


def key(entry):
    return (entry["instance_id"], entry["submission"], entry["policy"],
            entry.get("variant", "base"), entry.get("repeat", 0))


def load_index(path):
    """Return (keys whose last attempt is ok, keys attempted at all)."""
    done, attempted = set(), set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                attempted.add(key(entry))
                if entry.get("status") == "ok":
                    done.add(key(entry))
    return done, attempted


def leftover_containers():
    out = subprocess.run(["docker", "ps", "-aq", "--filter", "name=sandweaver-"],
                         capture_output=True, text=True)
    return len(out.stdout.split())


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selection", type=Path, default=HERE / "swebench-ml-selection.json")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "sandweaver-data")
    parser.add_argument("--runs-dir", type=Path, default=Path.home() / "sandweaver-runs")
    parser.add_argument("--index", type=Path, help="Default: RUNS_DIR/index.jsonl")
    parser.add_argument("--policies", default="session,batch")
    parser.add_argument("--instances", help="Comma-separated subset of instance IDs")
    parser.add_argument("--submissions", help="Comma-separated subset of submissions")
    parser.add_argument("--limit", type=int, help="Stop after this many attempts")
    parser.add_argument("--timeout", type=float, default=4 * 3600,
                        help="Wall-clock limit per replay, seconds")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Also rerun attempts whose last status was not ok")
    parser.add_argument("--variant", default="base",
                        help="Name recorded with each attempt for this configuration")
    parser.add_argument("--repeats", type=int, default=1,
                        help="Replay every trajectory this many times")
    parser.add_argument("--cap", type=float,
                        help="Passed to replay-swebench.py; 0 disables the recorded timeout")
    parser.add_argument("--sample", type=float, metavar="SECONDS",
                        help="Passed to replay-swebench.py: cgroup sampling period")
    parser.add_argument("--wait-scale", type=float, default=0,
                        help="Passed to replay-swebench.py: replay recorded model waits")
    parser.add_argument("--wait-cap", type=float,
                        help="Passed to replay-swebench.py: upper bound on each wait")
    args = parser.parse_args()
    options = {"cap": args.cap, "sample": args.sample, "wait_scale": args.wait_scale,
               "wait_cap": args.wait_cap}
    replay_flags = []
    for name, value in options.items():
        if value is not None:
            replay_flags += [f"--{name.replace('_', '-')}", f"{value:g}"]

    selection = json.loads(args.selection.read_text())
    instances = [t["instance_id"] for t in selection["tasks"]]
    submissions = selection["submissions"]
    if args.instances:
        instances = [i for i in instances if i in args.instances.split(",")]
    if args.submissions:
        submissions = [s for s in submissions if s in args.submissions.split(",")]
    policies = args.policies.split(",")
    index = args.index or args.runs_dir / "index.jsonl"
    args.runs_dir.mkdir(parents=True, exist_ok=True)
    done, attempted = load_index(index)
    if index.exists():
        # One variant, one configuration: refuse to mix settings under a name.
        for line in index.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                if (entry.get("variant", "base") == args.variant
                        and entry.get("options", BASE_OPTIONS) != options):
                    raise SystemExit(f"Variant {args.variant} in {index} was run with "
                                     f"{entry.get('options', BASE_OPTIONS)}, not {options}")
    skip = done if args.retry_failed else attempted

    plan = []
    for repeat in range(args.repeats):
        for instance in instances:
            for submission in submissions:
                if not (args.data_dir / "trajs" / submission / f"{instance}.traj.json").exists():
                    continue
                for policy in policies:
                    if (instance, submission, policy, args.variant, repeat) not in skip:
                        plan.append((instance, submission, policy, repeat))
    if args.limit:
        plan = plan[:args.limit]
    ok_here = sum(k[3] == args.variant for k in done)
    print(f"{len(plan)} attempts planned, {ok_here} already ok in variant {args.variant}",
          flush=True)

    for number, (instance, submission, policy, repeat) in enumerate(plan, 1):
        if subprocess.run(["docker", "info"], capture_output=True).returncode:
            raise SystemExit("Docker daemon is unreachable; stopping before the next attempt")
        entry = {"instance_id": instance, "submission": submission, "policy": policy,
                 "variant": args.variant, "repeat": repeat, "options": options,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        begin = time.monotonic()
        command = [sys.executable, str(HERE / "replay-swebench.py"), "--instance", instance,
                   "--submission", submission, "--policy", policy, "--evaluate",
                   "--data-dir", str(args.data_dir), "--runs-dir", str(args.runs_dir),
                   *replay_flags]
        try:
            replay = subprocess.run(command, capture_output=True, text=True,
                                    timeout=args.timeout)
            lines = replay.stdout.splitlines()
            # replay-swebench.py prints "Result: RUN_DIR/result.json".
            run = next((str(Path(l.split("Result: ", 1)[1]).parent)
                        for l in lines if l.startswith("Result: ")), None)
            entry["replay_exit"] = replay.returncode
            entry["run_dir"] = run
            if replay.returncode or not run:
                entry["status"] = "replay_failed"
                entry["error_tail"] = (replay.stderr or replay.stdout)[-2000:]
            else:
                grade = subprocess.run([sys.executable, str(HERE / "grade-swebench.py"), run,
                                        "--data-dir", str(args.data_dir)],
                                       capture_output=True, text=True, timeout=600)
                if grade.returncode:
                    entry["status"] = "grade_failed"
                    entry["error_tail"] = grade.stderr[-2000:]
                else:
                    entry["status"] = "ok"
                result = json.loads((Path(run) / "result.json").read_text())
                entry["summary"] = result.get("summary")
                entry["resolved"] = (result.get("grade") or {}).get("resolved")
        except subprocess.TimeoutExpired:
            entry["status"] = "timeout"
        entry["wall_s"] = round(time.monotonic() - begin, 1)
        entry["leftover_containers"] = leftover_containers()
        with index.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
        print(f"[{number}/{len(plan)}] {args.variant}#{repeat} {instance} "
              f"{submission.split('_')[-1]} {policy}: "
              f"{entry['status']} resolved={entry.get('resolved')} {entry['wall_s']}s",
              flush=True)


if __name__ == "__main__":
    main()
