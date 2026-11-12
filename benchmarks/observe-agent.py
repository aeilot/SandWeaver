#!/usr/bin/env python3
"""Record a deterministic SDK tool sequence against a temporary Docker worker."""
import argparse
from pathlib import Path
import select
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--state-dir", type=Path, required=True)
args = parser.parse_args()
with tempfile.TemporaryDirectory(dir="/tmp") as directory:
    root = Path(directory)
    workspace = root / "workspace"
    workspace.mkdir()
    socket = root / "pool.sock"
    server = subprocess.Popen(
        [sys.executable, "-m", "sandweaver.scheduler", "--socket", str(socket),
         "serve", "--workspace-root", str(workspace), "--min", "1", "--max", "1"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        if not select.select([server.stdout], [], [], 180)[0]:
            raise TimeoutError("Scheduler startup exceeded 180 seconds")
        if not server.stdout.readline().startswith("Ready"):
            raise RuntimeError("Scheduler did not become ready")
        subprocess.run(
            [sys.executable, "-m", "sandweaver.agent", "--socket", str(socket),
             "--workspace", str(workspace), "--state-dir", str(args.state_dir),
             "--observe",
             "--smoke-command", "/project/.venv/bin/python -c 'import humanize; print(humanize.intcomma(1000))'",
             "--smoke-command", """printf 'def total(values):\n    return sum(values)\n' > task.py; printf 'from task import total\nassert total([1, 2, 3]) == 6\nassert total([]) == 0\nprint("checks passed")\n' > check.py""",
             "--smoke-command", "python check.py"],
            check=True, timeout=120,
        )
    finally:
        server.terminate()
        server.wait(timeout=30)
