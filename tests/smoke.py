from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from sandweaver import scheduler as pool

image = sys.argv[1] if len(sys.argv) > 1 else pool.DEFAULT_IMAGE
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
                                         "--smoke-command", "echo sdk > /tmp/sdk",
                                         "--smoke-command", "cat /tmp/sdk"],
                                        text=True, capture_output=True)
                assert result.returncode == 0 and "sdk" in result.stdout, (result.stdout, result.stderr)
                print(result.stdout)
                print(json.dumps({"same_worker": worker, "workspace_persisted": True,
                                  "private_files_reset": True, "background_service_reset": True, "lease_state_preserved": True,
                                  "overlap_rejected": True, "elastic_capacity": [1, 2, 1],
                                  "openhands_sdk_calls": 2}))
        finally:
            server.terminate()
            server.wait(timeout=30)
