from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from sandweaver import scheduler as pool


def demand_smoke(path, a, b, c, execute):
    with pool.connect(path) as session, pool.connect(path) as other, pool.connect(path) as waiting:
        session.request("reserve", workspace=str(a))
        initial = session.request("claim")["worker"]
        execute(session, "touch /tmp/parked")
        session.request("park")
        other.request("claim", workspace=str(b))
        resumed = session.request("claim", observe=True)
        assert resumed["worker"] == initial and resumed["timing"]["resumed_parked"]
        execute(session, "test -f /tmp/parked")
        session.request("park")
        reclaimed = waiting.request("claim", workspace=str(c), observe=True)
        assert reclaimed["worker"] == initial and reclaimed["timing"]["reclaim_ns"] > 0
        execute(waiting, "test ! -e /tmp/parked")
        waiting.request("release")
        resumed = session.request("claim", observe=True)
        assert not resumed["timing"]["resumed_parked"]
        execute(session, "test ! -e /tmp/parked")
        session.request("park")
        session.request("release")
        other.request("release")


def batch_smoke(path, root, workspace, other):
    calls = []
    errors = []
    held_worker = None
    child = workspace / "nested"
    child.mkdir()

    with pool.connect(path) as blocker:
        class Model(BaseHTTPRequestHandler):
            def do_POST(self):
                nonlocal held_worker
                try:
                    request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    step = len(calls)
                    if step == 0:
                        assert blocker.request("status")["leased"] == 0
                        commands = ["echo sdk > saved-batch; touch /tmp/batch",
                                    "test -e /tmp/batch"]
                    elif step == 1:
                        assert blocker.request("status")["leased"] == 0
                        for overlap in (workspace, child, root):
                            with pool.connect(path) as duplicate:
                                try:
                                    duplicate.request("claim", workspace=str(overlap))
                                except RuntimeError as exc:
                                    assert "session reservation" in str(exc)
                                else:
                                    raise AssertionError("Reserved workspace was acquired")
                        held_worker = blocker.request("claim", workspace=str(other))["worker"]
                        commands = ['test "$(cat saved-batch)" = sdk && test ! -e /tmp/batch '
                                    '&& echo resumed > result-batch']
                    elif step == 2:
                        assert blocker.request("status")["leased"] == 1
                        commands = []
                    else:
                        raise AssertionError(f"Unexpected model request {step}")
                    calls.append(step)
                    message = {"role": "assistant", "content": "Done."}
                    if commands:
                        message.update(content=None, tool_calls=[
                            {"id": f"call_{step}_{index}", "type": "function",
                             "function": {"name": "sandweaver_shell",
                                          "arguments": json.dumps({"command": command})}}
                            for index, command in enumerate(commands)
                        ])
                    body = json.dumps({
                        "id": f"chatcmpl-{step}", "object": "chat.completion",
                        "created": int(time.time()), "model": request["model"],
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
                    errors.append(exc)
                    self.send_error(500)

            def log_message(self, *_):
                pass

        with HTTPServer(("127.0.0.1", 0), Model) as model:
            thread = threading.Thread(target=model.serve_forever)
            thread.start()
            try:
                state = root / "batch-agent-state"
                result = subprocess.run([
                    sys.executable, "-m", "sandweaver.agent", "--socket", str(path),
                    "--workspace", str(workspace), "--state-dir", str(state),
                    "--batch-leases", "--observe", "--prompt", "Run the fixed tools.",
                    "--llm-attempts", "1", "--max-iterations", "3",
                ], env={**os.environ, "LLM_MODEL": "openai/gpt-4o-mini", "LLM_API_KEY": "fixture",
                        "LLM_BASE_URL": f"http://127.0.0.1:{model.server_port}/v1"},
                    capture_output=True, text=True, timeout=45)
            finally:
                model.shutdown()
                thread.join()
        assert not errors, errors
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert calls == [0, 1, 2], calls
        blocker.request("release")
        assert (workspace / "result-batch").read_text() == "resumed\n"
        trace, = state.glob("*/trace.jsonl")
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        workers = [row["worker"] for row in records if row["event"] == "lease_acquired"]
        assert len(workers) == 2 and workers[0] == held_worker and workers[0] != workers[1], workers
        assert [row["exit_code"] for row in records if row["event"] == "command_result"] == [0, 0, 0]
        assert sum(row["event"] == "lease_released" for row in records) == 2
        states = [row for row in records if row["event"] == "lease_state"]
        assert len(states) == 2 and "tmp/batch" in states[0]["upper_prefix_bytes"], states
        assert "tmp/batch" not in states[1]["upper_prefix_bytes"], states
        deadline = time.monotonic() + 3
        while True:
            with pool.connect(path) as next_session:
                try:
                    next_session.request("claim", workspace=str(workspace))
                except RuntimeError as exc:
                    if "session reservation" not in str(exc) or time.monotonic() >= deadline:
                        raise
                else:
                    next_session.request("release")
                    break
            time.sleep(.01)
        # The reservation is dropped only after root-created files are handed back.
        owners = {p.lstat().st_uid for p in [workspace, *workspace.rglob("*")]}
        assert owners == {os.getuid()}, owners


def options_smoke(image):
    """Custom mount path, disk-backed write layer beyond the tmpfs default, exec timeout."""
    with tempfile.TemporaryDirectory(dir="/tmp") as temp:
        root = Path(temp)
        path, workspace = root / "options.sock", root / "w"
        workspace.mkdir()
        cmd = [sys.executable, "-m", "sandweaver.scheduler", "--socket", str(path), "serve",
               "--workspace-root", str(root), "--min", "1", "--max", "1", "--image", image,
               "--workspace-mount", "/srv/testbed", "--state-size", "disk", "--exec-timeout", "20",
               "--proc"]
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) as server:
            try:
                assert server.stdout.readline().startswith("Ready")
                with pool.connect(path) as client:
                    client.request("claim", workspace=str(workspace))
                    result = client.request("exec", command="pwd; touch made; "
                                            "dd if=/dev/zero of=/tmp/big bs=1M count=600 status=none")
                    assert result["exit_code"] == 0 and result["stdout"] == "/srv/testbed\n", result
                    state = client.request("inspect")
                    assert state["upper_prefix_bytes"]["tmp/big"] == 600 << 20, state
                    assert state["upper_category_bytes"]["tmp"] == 600 << 20, state
                    # Lease-private procfs; kernel tunables stay read-only. Writes use
                    # harmless values in case the masking ever regresses.
                    probe = ("test -r /proc/self/status && ls -d /proc/[0-9]* | wc -l; "
                             "v=$(cat /proc/sys/vm/swappiness); "
                             "if (echo $v > /proc/sys/vm/swappiness) 2>/dev/null; then echo sys-writable; fi; "
                             "if (echo h > /proc/sysrq-trigger) 2>/dev/null; then echo sysrq-writable; fi")
                    result = client.request("exec", command=probe)
                    lines = result["stdout"].split()
                    assert result["exit_code"] == 0 and int(lines[0]) <= 4 and len(lines) == 1, result
                    try:
                        client.request("exec", command="sleep 30")
                    except RuntimeError as exc:
                        assert "timed out" in str(exc)
                    else:
                        raise AssertionError("Command did not time out")
                # Ownership is restored by the server after the connection closes, here
                # after the timed-out worker was retired.
                deadline = time.monotonic() + 60
                while (workspace / "made").stat().st_uid != os.getuid():
                    assert time.monotonic() < deadline, "workspace ownership not restored"
                    time.sleep(.2)
            finally:
                server.terminate()
                server.wait(timeout=60)


image = sys.argv[1] if len(sys.argv) > 1 else pool.DEFAULT_IMAGE
options_smoke(image)
with tempfile.TemporaryDirectory(dir="/tmp") as temp:
    root = Path(temp)
    path = root / "pool.sock"
    a, b, c = (root / name for name in "abc")
    for workspace in (a, b, c):
        workspace.mkdir()
    cmd = [sys.executable, "-m", "sandweaver.scheduler", "--socket", str(path)]
    with subprocess.Popen(cmd + ["serve", "--workspace-root", str(root), "--min", "1", "--max", "2",
                                 "--idle-seconds", "1", "--image", image], stdout=subprocess.PIPE, text=True) as server:
        try:
            assert server.stdout.readline().startswith("Ready")
            def claim(client, workspace):
                return client.request("claim", workspace=str(workspace))["worker"]
            def execute(client, command):
                result = client.request("exec", command=command)
                assert result["exit_code"] == 0, result
                return result["stdout"].strip()
            with pool.connect(path) as control, pool.connect(path) as first:
                assert control.request("status") == {"total": 1, "leased": 0, "idle": 1}
                worker = claim(first, a)
                execute(first, "touch /tmp/private /root/private saved; sleep 60 </dev/null >/dev/null 2>&1 & echo $! > /tmp/bg")
                execute(first, 'test -f /tmp/private && kill -0 "$(cat /tmp/bg)"')
                execute(first, "python -m http.server 19287 --bind 127.0.0.1 </dev/null >/tmp/server 2>&1 &")
                probe = 'python -c \'import socket; s=socket.socket(); s.settimeout(1); print(s.connect_ex(("127.0.0.1",19287)))\''
                deadline = time.monotonic() + 3
                while execute(first, probe) != "0":
                    assert time.monotonic() < deadline
                    time.sleep(.05)
                state = first.request("inspect")
                assert "sleep" in state["processes"], state
                assert state["listening_ports"] == [19287], state
                assert {"tmp/private", "root/private"} <= state["upper_prefix_bytes"].keys(), state
                assert "saved" not in state["upper_prefix_bytes"], state
                first.request("release")
                assert (a / "saved").exists()
                with pool.connect(path) as second, pool.connect(path) as third:
                    assert claim(second, b) == worker
                    assert execute(second, probe) != "0"
                    assert execute(second, """test ! -e /tmp/private && test ! -e /root/private && test ! -e saved && /project/.venv/bin/python -c 'import humanize; print(humanize.intcomma(1000))'""") == "1,000"
                    try:
                        with pool.connect(path) as duplicate:
                            claim(duplicate, b)
                    except RuntimeError as exc:
                        assert "overlaps" in str(exc)
                    else:
                        raise AssertionError("duplicate workspace acquired")
                    assert claim(third, c) != worker
                    assert control.request("status")["leased"] == 2
                    third.request("release")
                    second.request("release")
                deadline = time.monotonic() + 5
                while control.request("status")["total"] != 1:
                    assert time.monotonic() < deadline
                    time.sleep(.1)
                result = subprocess.run([sys.executable, "-m", "sandweaver.agent",
                                         "--socket", str(path), "--workspace", str(b), "--state-dir", str(root / "agent-state"),
                                         "--observe",
                                         "--smoke-command", "echo sdk > /tmp/sdk",
                                         "--smoke-command", "cat /tmp/sdk"],
                                        text=True, capture_output=True)
                assert result.returncode == 0 and "sdk" in result.stdout, (result.stdout, result.stderr)
                traces = list((root / "agent-state").glob("*/trace.jsonl"))
                assert len(traces) == 1
                records = [json.loads(line) for line in traces[0].read_text().splitlines()]
                assert [row["elapsed_ns"] for row in records] == sorted(row["elapsed_ns"] for row in records)
                assert sum(row["event"] == "span_end" and row["name"] == "exec" for row in records) == 2
                spans = {row["span"]: row["name"] for row in records if row["event"] == "span_end"}
                timings = [row for row in records if row["event"] == "scheduler_timing"]
                claims = [row for row in timings if spans[row["span"]] == "claim"]
                assert len(claims) == 1 and claims[0]["claim_ns"] > 0
                assert claims[0]["pool_wait_ns"] == 0
                executions = [row for row in timings if spans[row["span"]] == "exec"]
                assert len(executions) == 2 and all(row["exec_ns"] > 0 for row in executions)
                outputs = [row for row in records if row["event"] == "command_result"]
                assert [row["stdout_bytes"] for row in outputs] == [0, 4]
                assert all(row["stderr_bytes"] == 0 and spans[row["span"]] == "exec" for row in outputs)
                assert records[-1]["event"] == "lease_released"
                state, = [row for row in records if row["event"] == "lease_state"]
                assert "tmp/sdk" in state["upper_prefix_bytes"], state
                assert all("command" not in row and "stdout" not in row for row in records)
                batch_smoke(path, root, a, c)
                demand_smoke(path, a, b, c, execute)
                print(result.stdout)
                print(json.dumps({"same_worker": worker, "workspace_persisted": True,
                                  "private_files_reset": True, "background_service_reset": True, "lease_state_preserved": True,
                                  "overlap_rejected": True, "elastic_capacity": [1, 2, 1],
                                  "openhands_sdk_calls": 2, "openhands_batch_handover": True,
                                  "demand_reclaim": True}))
        finally:
            server.terminate()
            server.wait(timeout=30)
