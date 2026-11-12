"""One bounded DeepSeek Flash repair task; credentials stay in the external client."""
import argparse
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--state-dir", type=Path, required=True)
args = parser.parse_args()
key = os.environ.get("LLM_API_KEY")
if not key:
    parser.error("Provide LLM_API_KEY in the environment")
environment = dict(os.environ, LLM_API_KEY=key,
                   LLM_MODEL="openrouter/deepseek/deepseek-v4-flash",
                   LLM_BASE_URL="https://openrouter.ai/api/v1",
                   PYTHONPATH=os.getcwd(), PYTHONDONTWRITEBYTECODE="1",
                   OPENHANDS_SUPPRESS_BANNER="1")
server_environment = {k: v for k, v in os.environ.items()
                      if k not in ("LLM_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY")}
python = sys.executable
state = str(args.state_dir.resolve())
prompt = """Fix the bug in intervals.py so merge_intervals merges overlapping AND touching intervals, accepts unsorted input, handles empty input, and does not mutate its input. Use the shell tool to inspect files and run the existing tests first. Then fix the implementation, rerun tests and report the result. Work only in /workspace. Do not install anything or access the network."""
with tempfile.TemporaryDirectory(dir="/tmp") as directory:
    root = Path(directory)
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "intervals.py").write_text("def merge_intervals(intervals):\n    return intervals\n")
    (workspace / "test_intervals.py").write_text("""import unittest
from intervals import merge_intervals
class MergeTests(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(merge_intervals([[1,4],[2,5]]), [[1,5]])
    def test_touching(self):
        self.assertEqual(merge_intervals([[1,2],[2,3]]), [[1,3]])
    def test_unsorted(self):
        self.assertEqual(merge_intervals([[8,10],[1,3],[2,6]]), [[1,6],[8,10]])
    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])
    def test_no_mutation(self):
        data = [[4,6],[1,5]]
        merge_intervals(data)
        self.assertEqual(data, [[4,6],[1,5]])
if __name__ == "__main__":
    unittest.main()
""")
    original_tests = (workspace / "test_intervals.py").read_text()
    socket = root / "pool.sock"
    # Model credentials are passed only to the external agent.
    server = subprocess.Popen([python, "-m", "sandweaver.scheduler", "--socket", str(socket),
                               "serve", "--workspace-root", str(workspace), "--min", "1", "--max", "1"],
                              stdout=subprocess.PIPE, text=True, env=server_environment)
    try:
        if not select.select([server.stdout], [], [], 180)[0]:
            raise TimeoutError("Scheduler startup timeout")
        if not server.stdout.readline().startswith("Ready"):
            raise RuntimeError("Scheduler failed")
        result = subprocess.run([python, "-m", "sandweaver.agent", "--socket", str(socket),
                                 "--workspace", str(workspace), "--state-dir", state,
                                 "--observe", "--max-iterations", "8", "--max-output-tokens", "2048", "--llm-attempts", "1", "--prompt", prompt], env=environment,
                                capture_output=True, text=True, timeout=240)
        print((result.stdout + result.stderr).replace(key, "[REDACTED]"))
        if result.returncode:
            raise SystemExit(result.returncode)
        (workspace / "test_intervals.py").write_text(original_tests)
        verified = subprocess.run([python, "-m", "unittest", "-v"], cwd=workspace,
                                  capture_output=True, text=True, env=server_environment)
        print("Independent verification:", verified.stdout, verified.stderr)
        if verified.returncode:
            raise SystemExit(verified.returncode)
    finally:
        server.terminate()
        server.wait(timeout=30)
