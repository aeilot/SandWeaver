from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from sandweaver.scheduler import Pool, Worker


class RetirementTest(unittest.TestCase):
    def test_workspace_stays_reserved_until_container_is_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = Pool.__new__(Pool)
            pool.root = Path(directory).resolve()
            pool.minimum = 0
            pool.lock = threading.Condition()
            pool.stop = Mock()
            pool.stop.is_set.return_value = False
            pool.stop.wait.side_effect = [False, True]
            workspace = pool.root / "workspace"
            workspace.mkdir()
            worker = Worker("sandweaver-test", 0, workspace)
            pool.workers = [worker]

            failed_remove = subprocess.CompletedProcess([], 1)
            container_present = subprocess.CompletedProcess([], 0, stdout="container-id\n")
            container_absent = subprocess.CompletedProcess([], 0, stdout="")
            with patch("sandweaver.scheduler.docker", side_effect=[
                RuntimeError("reset failed"), failed_remove, container_present,
                failed_remove, container_absent,
            ]):
                pool.release(worker)
                self.assertEqual(pool.status(), {"total": 1, "leased": 1, "idle": 0})
                with self.assertRaisesRegex(RuntimeError, "overlaps an active lease"):
                    pool.acquire(workspace)

                pool.maintain()
                self.assertEqual(pool.status(), {"total": 0, "leased": 0, "idle": 0})
