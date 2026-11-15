#!/usr/bin/env python3
"""Replay every selected SWE-bench Multilingual trajectory and grade it.

Runs replay-swebench.py (with --evaluate) and then grade-swebench.py for each
task in swebench-ml-selection.json, each submission that has a trajectory for
it, and each requested policy. Policies for one trajectory run back to back so
the task image stays warm. Results already in the index are skipped, so the
driver can be stopped and restarted. One JSON line per attempt is appended to
INDEX (default RUNS_DIR/index.jsonl); the per-run result.json stays in its run
directory.

Runs are sequential: each replay starts its own one-worker scheduler.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def load_index(path):
    done = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                if entry.get("status") == "ok":
                    done[(entry["instance_id"], entry["submission"], entry["policy"])] = entry
    return done


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
    args = parser.parse_args()

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
    done = load_index(index)
    attempted = set()
    if not args.retry_failed and index.exists():
        for line in index.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                attempted.add((entry["instance_id"], entry["submission"], entry["policy"]))

    plan = []
    for instance in instances:
        for submission in submissions:
            if not (args.data_dir / "trajs" / submission / f"{instance}.traj.json").exists():
                continue
            for policy in policies:
                key = (instance, submission, policy)
                if key not in done and key not in attempted:
                    plan.append(key)
    if args.limit:
        plan = plan[:args.limit]
    print(f"{len(plan)} attempts planned, {len(done)} already ok", flush=True)

    for number, (instance, submission, policy) in enumerate(plan, 1):
        if subprocess.run(["docker", "info"], capture_output=True).returncode:
            raise SystemExit("Docker daemon is unreachable; stopping before the next attempt")
        entry = {"instance_id": instance, "submission": submission, "policy": policy,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        begin = time.monotonic()
        command = [sys.executable, str(HERE / "replay-swebench.py"), "--instance", instance,
                   "--submission", submission, "--policy", policy, "--evaluate",
                   "--data-dir", str(args.data_dir), "--runs-dir", str(args.runs_dir)]
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
        print(f"[{number}/{len(plan)}] {instance} {submission.split('_')[-1]} {policy}: "
              f"{entry['status']} resolved={entry.get('resolved')} {entry['wall_s']}s",
              flush=True)


if __name__ == "__main__":
    main()
