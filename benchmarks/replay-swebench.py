#!/usr/bin/env python3
"""Replay a public mini-swe-agent SWE-bench Multilingual trajectory on SandWeaver workers.

The commands, their order and the per-command timeout come from the recorded
trajectory; no model is called. `--policy session` holds one lease for the whole
run; `--policy batch` releases the worker after every step and claims it again
for the next one, so each step starts from a fresh write layer with only the
workspace carried over. Before each step ends, the lease state that a release
would discard is inspected and recorded.

The workspace is a root-owned copy of the image's /testbed, like the original
container, so tools that check ownership (git, npm) behave as recorded.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandweaver import scheduler  # noqa: E402
import minitraj  # noqa: E402

docker = scheduler.docker


def task_row(data, instance):
    table = pq.read_table(data / "dataset/test.parquet")
    for row in table.to_pylist():
        if row["instance_id"] == instance:
            return row
    raise SystemExit(f"Unknown instance {instance}")


def wrap(command, env, cap, login=True):
    """Match mini-swe-agent: `bash -lc` in /testbed with its env and timeout.

    The official eval runs its script with a non-login bash; a login shell would
    let /etc/profile reset root's PATH and drop image paths such as cargo's.
    """
    prefix = "exec env " + " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    limit = f" timeout {cap:g}" if cap else ""
    flag = "-lc" if login else "-c"
    return f"{prefix}{limit} bash {flag} {shlex.quote(command)}"


def as_root(image, root, script, *args, timeout=900):
    """Run a short root container with the run directory mounted at /run-root."""
    return docker("run", "--rm", "--network", "none", "--mount",
                  f"type=bind,src={root},dst=/run-root", "--entrypoint", "/bin/sh", image,
                  "-ec", script, "helper", *args, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--submission", default="20260213_mini-v2.0.0a0_deepseek-3-2")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "sandweaver-data")
    parser.add_argument("--runs-dir", type=Path, default=Path.home() / "sandweaver-runs")
    parser.add_argument("--policy", choices=("session", "batch"), default="batch")
    parser.add_argument("--cap", type=float, default=None,
                        help="Per-command timeout in seconds; default is the recorded one, 0 disables")
    parser.add_argument("--network", choices=("none", "bridge"), default="bridge",
                        help="The recorded runs had Docker's default network")
    parser.add_argument("--state-size", default="disk")
    parser.add_argument("--max-steps", type=int, help="Stop early, for debugging")
    parser.add_argument("--evaluate", action="store_true",
                        help="Run the official eval script on the final workspace in a fresh lease")
    parser.add_argument("--eval-timeout", type=float, default=1800,
                        help="Seconds for the eval script; 0 disables")
    parser.add_argument("--keep", action="store_true", help="Keep the run workspace")
    args = parser.parse_args()

    row = task_row(args.data_dir, args.instance)
    image = row["image"] if "/" in row["image"] else "swebench/" + row["image"]
    traj_path = args.data_dir / "trajs" / args.submission / f"{args.instance}.traj.json"
    info, steps = minitraj.load(traj_path)
    environment = info.get("config", {}).get("environment", {})
    env = environment.get("env", {})
    cap = environment.get("timeout", 60) if args.cap is None else args.cap
    if args.max_steps:
        steps = steps[:args.max_steps]

    run_id = f"{args.instance}--{args.submission.split('_')[-1]}--{args.policy}--{int(time.time())}"
    run = (args.runs_dir / run_id).resolve()
    root = run / "ws"
    root.mkdir(parents=True)
    result = {
        "instance_id": args.instance, "submission": args.submission, "policy": args.policy,
        "cap_s": cap, "network": args.network, "state_size": args.state_size, "image": image,
        "image_id": docker("image", "inspect", "-f", "{{.Id}}", image).stdout.strip(),
        "trajectory_sha256": hashlib.sha256(traj_path.read_bytes()).hexdigest(),
        "recorded_steps": len(steps), "steps": [],
    }

    workspace = root / "testbed"

    # Unix socket paths are limited to 108 bytes; run directories can be longer.
    socket_dir = Path(tempfile.mkdtemp(prefix="swr-", dir="/tmp"))
    socket = socket_dir / "pool.sock"
    command = [sys.executable, "-m", "sandweaver.scheduler", "--socket", str(socket), "serve",
               "--workspace-root", str(root), "--min", "1", "--max", "1", "--image", image,
               "--workspace-mount", "/testbed", "--network", args.network,
               "--state-size", args.state_size, "--exec-timeout", str(max(3600, 2 * cap)),
               "--proc"]
    with ExitStack() as stack:
        # Callbacks run in reverse: the scheduler stops before the root-owned copy is
        # removed, on success and on failure alike.
        if not args.keep:
            stack.callback(as_root, image, run, "rm -rf /run-root/ws/testbed")
        stack.callback(shutil.rmtree, socket_dir, ignore_errors=True)
        started = time.monotonic()
        as_root(image, root, "cp -a /testbed /run-root/testbed")
        result["export_s"] = time.monotonic() - started
        started = time.monotonic()
        server = stack.enter_context(subprocess.Popen(
            command, stdout=subprocess.PIPE, text=True, cwd=Path(__file__).resolve().parents[1]))
        stack.callback(server.wait, timeout=120)
        stack.callback(server.terminate)
        ready = server.stdout.readline()
        if not ready.startswith("Ready"):
            raise SystemExit(f"Scheduler did not start: {ready!r}")
        result["pool_start_s"] = time.monotonic() - started
        client = stack.enter_context(scheduler.connect(socket))
        client.request("reserve", workspace=str(workspace))
        leased = False
        replay_started = time.monotonic()
        for index, step in enumerate(steps):
            record = {"index": index, "recorded_model_wait_s": step.model_wait_s,
                      "commands": []}
            if not leased:
                begin = time.monotonic_ns()
                reply = client.request("claim", observe=True)
                record["claim_ns"] = time.monotonic_ns() - begin
                record["claim_timing"] = reply.get("timing", {})
                leased = True
            for position, original in enumerate(step.commands):
                begin = time.monotonic_ns()
                reply = client.request("exec", command=wrap(original, env, cap), observe=True)
                elapsed = time.monotonic_ns() - begin
                recorded_rc = step.returncodes[position] if position < len(step.returncodes) else None
                recorded_s = step.exec_s[position] if position < len(step.exec_s) else None
                record["commands"].append({
                    "exec_ns": elapsed, "exit_code": reply["exit_code"],
                    "recorded_exit_code": recorded_rc, "recorded_s": recorded_s,
                    "stdout_bytes": len(reply["stdout"]), "stderr_bytes": len(reply["stderr"]),
                    "timed_out": bool(cap) and reply["exit_code"] == 124,
                    "rc_match": recorded_rc is None or reply["exit_code"] == recorded_rc,
                })
            if step.commands:
                record["lease_state"] = client.request("inspect")
            if args.policy == "batch" and leased:
                begin = time.monotonic_ns()
                client.request("release")
                record["release_ns"] = time.monotonic_ns() - begin
                leased = False
            result["steps"].append(record)
            print(f"step {index + 1}/{len(steps)} "
                  f"rc={[c['exit_code'] for c in record['commands']]} "
                  f"rec={[c['recorded_exit_code'] for c in record['commands']]}", flush=True)
        result["replay_s"] = time.monotonic() - replay_started

        # Compare the final change with the patch the agent submitted.
        if not leased:
            client.request("claim")
            leased = True
        diff = client.request("exec", command=wrap(
            # Build output inside submodules only marks them dirty; it is not a change.
            f"git -c core.fileMode=false diff --ignore-submodules=dirty {row['base_commit']}",
            env, 0))
        submitted = info.get("submission") or ""
        (run / "final.diff").write_text(diff["stdout"])
        (run / "submission.diff").write_text(submitted)
        result["final_diff_sha256"] = hashlib.sha256(diff["stdout"].encode()).hexdigest()
        result["submission_matches"] = diff["stdout"].strip() == submitted.strip()
        result["submission_empty"] = not submitted.strip()
        client.request("release")
        leased = False

        if args.evaluate:
            client.request("claim")
            begin = time.monotonic()
            reply = client.request("exec", command=wrap(row["eval_script"], {},
                                                        args.eval_timeout, login=False))
            result["eval_s"] = time.monotonic() - begin
            result["eval_exit_code"] = reply["exit_code"]
            result["eval_timed_out"] = bool(args.eval_timeout) and reply["exit_code"] == 124
            (run / "eval.log").write_text(reply["stdout"] + reply["stderr"])
            client.request("release")

    commands = [c for s in result["steps"] for c in s["commands"]]
    result["summary"] = {
        "commands": len(commands),
        "rc_mismatches": sum(not c["rc_match"] for c in commands),
        "timeouts": sum(c["timed_out"] for c in commands),
        "exec_s": sum(c["exec_ns"] for c in commands) / 1e9,
        "recorded_exec_s": sum(c["recorded_s"] or 0 for c in commands),
        "claim_s": sum(s.get("claim_ns", 0) for s in result["steps"]) / 1e9,
        "release_s": sum(s.get("release_ns", 0) for s in result["steps"]) / 1e9,
        "steps_with_processes": sum(bool(s.get("lease_state", {}).get("processes"))
                                    for s in result["steps"]),
        "max_upper_bytes": max((s.get("lease_state", {}).get("upper_bytes", 0)
                                for s in result["steps"]), default=0),
    }
    (run / "result.json").write_text(json.dumps(result, indent=1))
    print(json.dumps({k: result[k] for k in ("instance_id", "policy", "export_s", "pool_start_s",
                                             "replay_s", "submission_matches")} | result["summary"]))
    print(f"Result: {run / 'result.json'}")


if __name__ == "__main__":
    main()
