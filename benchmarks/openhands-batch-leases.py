#!/usr/bin/env python3
"""Compare OpenHands lease policies with deterministic local model responses."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time

from sandweaver import scheduler


class Fixture:
    def __init__(self, wait_ms):
        self.wait_ms = wait_ms
        self.steps = [0, 0]
        self.ready = threading.Event()
        self.barrier = threading.Barrier(2, action=self.begin_wait, timeout=15)

    def begin_wait(self):
        self.started = time.monotonic()
        self.ready.set()

    def commands(self, agent):
        step = self.steps[agent]
        self.steps[agent] += 1
        if step == 0:
            return ["printf 'ready\\n' > result"]
        if step == 1:
            self.barrier.wait()
            time.sleep(max(0, self.started + self.wait_ms / 1000 - time.monotonic()))
            return ['test "$(cat result)" = ready && touch verified']
        if step == 2:
            return []
        raise ValueError(f"Unexpected model call {step} from agent {agent}")


class ModelHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            agent = int(self.path.split("/")[1])
            commands = self.server.fixture.commands(agent)
            message = {"role": "assistant", "content": "Done."}
            if commands:
                message.update(content=None, tool_calls=[
                    {"id": f"call_{agent}_{self.server.fixture.steps[agent]}_{index}",
                     "type": "function", "function": {"name": "sandweaver_shell",
                     "arguments": json.dumps({"command": command})}}
                    for index, command in enumerate(commands)
                ])
            body = json.dumps({
                "id": f"chatcmpl-{agent}-{self.server.fixture.steps[agent]}",
                "object": "chat.completion", "created": int(time.time()),
                "model": request["model"],
                "choices": [{"index": 0, "message": message,
                             "finish_reason": "tool_calls" if commands else "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.send_error(500, str(exc))

    def log_message(self, *_):
        pass


def agent_metrics(state, policy):
    path, = state.glob("*/trace.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    ends = [row for row in rows if row["event"] == "span_end"]
    calls = [row for row in ends if row["name"] == "llm_call"]
    tools = [row for row in ends if row["name"] == "exec"]
    results = [row["exit_code"] for row in rows if row["event"] == "command_result"]
    if len(calls) != 3 or len(tools) != 2 or results != [0, 0]:
        raise RuntimeError(f"Unexpected model or tool trace: {results}")
    spans = {row["span"]: row for row in rows if row["event"] == "span_start"}
    run, = [row for row in ends if row["name"] == "conversation_run"]
    resume_claim = next((row for row in ends if row["name"] == "claim"
                         and calls[1]["elapsed_ns"] < row["elapsed_ns"] < tools[1]["elapsed_ns"]), None)
    if (resume_claim is not None) != (policy != "session"):
        raise RuntimeError("Lease trace did not match the requested policy")
    resume_timing = next((row for row in rows if resume_claim and row["event"] == "scheduler_timing"
                          and row["span"] == resume_claim["span"]), {})
    start, finish = spans[run["span"]]["elapsed_ns"], run["elapsed_ns"]
    return {
        "ready_to_tool_done_ms": (tools[1]["elapsed_ns"] - calls[1]["elapsed_ns"]) / 1e6,
        "first_to_last_tool_done_ms": (tools[1]["elapsed_ns"] - tools[0]["elapsed_ns"]) / 1e6,
        "conversation_run_ms": (finish - start) / 1e6,
        "resume_claim_ms": ((resume_claim["elapsed_ns"] - spans[resume_claim["span"]]["elapsed_ns"]) / 1e6
                            if resume_claim else 0),
        "resume_queue_ms": resume_timing.get("pool_wait_ns", 0) / 1e6,
        "resumed_parked": int(resume_timing.get("resumed_parked", False)),
    }


def trial(socket, workspaces, state, wait_ms, policy, with_probe):
    fixture = Fixture(wait_ms)
    with ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler) as model:
        model.fixture = fixture
        thread = threading.Thread(target=model.serve_forever, kwargs={"poll_interval": .05})
        thread.start()

        def agent(index):
            workspace = workspaces / str(index)
            (workspace / "verified").unlink(missing_ok=True)
            agent_state = state / str(index)
            command = [sys.executable, "-m", "sandweaver.agent", "--socket", str(socket),
                       "--workspace", str(workspace), "--state-dir", str(agent_state),
                       "--observe", "--prompt", "Run the supplied tools.", "--max-iterations", "3",
                       "--llm-attempts", "1"]
            if policy == "batch":
                command.append("--batch-leases")
            elif policy == "demand":
                command.append("--demand-leases")
            env = {**os.environ, "LLM_MODEL": "openai/gpt-4o-mini", "LLM_API_KEY": "fixture",
                   "LLM_BASE_URL": f"http://127.0.0.1:{model.server_port}/{index}/v1",
                   "LITELLM_LOCAL_MODEL_COST_MAP": "True"}
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=45)
            if result.returncode or not (workspace / "verified").is_file():
                raise RuntimeError(f"Agent {index} did not complete: {result.stdout}\n{result.stderr}")
            return agent_metrics(agent_state, policy)

        def probe():
            if not fixture.ready.wait(20):
                raise TimeoutError("Agents never entered the second model call")
            time.sleep(max(0, fixture.started + .05 - time.monotonic()))
            with scheduler.connect(socket) as client:
                start = time.monotonic_ns()
                reply = client.request("claim", workspace=str(workspaces / "probe"), observe=True)
                claimed = time.monotonic_ns()
                result = client.request("exec", command="true")
                finished = time.monotonic_ns()
                client.request("release")
            if result["exit_code"]:
                raise RuntimeError("Short task failed")
            return {"queue_ms": reply["timing"]["pool_wait_ns"] / 1e6,
                    "reclaim_ms": reply["timing"]["reclaim_ns"] / 1e6,
                    "claim_ms": (claimed - start) / 1e6, "completion_ms": (finished - start) / 1e6}

        try:
            with ThreadPoolExecutor(max_workers=3) as tasks:
                agents = [tasks.submit(agent, index) for index in range(2)]
                short = tasks.submit(probe) if with_probe else None
                return {"agents": [job.result() for job in agents],
                        "probe": short.result() if short is not None else None}
        finally:
            model.shutdown()
            thread.join()


def summarize(rows):
    result = {}
    for key in rows[0]:
        values = sorted(row[key] for row in rows)
        result[key] = {"p50": statistics.median(values),
                       "p95": values[(95 * len(values) + 99) // 100 - 1]}
    return result


def run(image, rounds):
    docker = scheduler.docker("info", "--format",
                              "{{.OSType}}/{{.Architecture}} {{.OperatingSystem}}").stdout.strip()
    result = {"docker": docker, "image": image, "workers": 2, "rounds_per_arm": rounds,
              "warmup_per_arm": 1, "probe_after_wait_start_ms": 50, "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="sw-oh-", dir="/tmp") as directory:
        scratch = Path(directory).resolve()
        workspaces = scratch / "workspaces"
        for name in ("0", "1", "probe"):
            (workspaces / name).mkdir(parents=True)
        socket = Path(directory) / "pool.sock"
        started = time.monotonic()
        pool = scheduler.Pool(image, workspaces, 2, 2, 60, scratch)
        result.update(image_id=pool.image, pool_setup_ms=(time.monotonic() - started) * 1000)
        try:
            with scheduler.Server(str(socket), scheduler.Handler) as server:
                server.pool = pool
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    for wait_ms, with_probe in ((150, True), (830, True), (830, False)):
                        samples = {"session": [], "batch": [], "demand": []}
                        arms = tuple(samples)
                        for index in range(rounds + 1):
                            offset = index % len(arms)
                            for arm in arms[offset:] + arms[:offset]:
                                state = scratch / f"trace-{wait_ms}-{with_probe}-{index}-{arm}"
                                row = trial(socket, workspaces, state, wait_ms, arm, with_probe)
                                if index:
                                    samples[arm].append(row)
                        result["scenarios"].append({
                            "wait_ms": wait_ms, "with_probe": with_probe, "samples": samples,
                            "summary": {arm: {
                                "agents": summarize([agent for row in rows for agent in row["agents"]]),
                                "probe": summarize([row["probe"] for row in rows]) if with_probe else None,
                            } for arm, rows in samples.items()},
                        })
                finally:
                    server.shutdown()
                    thread.join()
        finally:
            pool.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=scheduler.DEFAULT_IMAGE)
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    args.output.write_text(json.dumps(run(args.image, args.rounds), indent=2) + "\n")
