from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from sandweaver.scheduler import DEFAULT_MOUNT, Pool, RESET, Worker


class RetirementTest(unittest.TestCase):
    def test_resume_waits_for_in_flight_reclaim(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = Pool.__new__(Pool)
            pool.root = Path(directory).resolve()
            pool.maximum = 1
            pool.mount = DEFAULT_MOUNT
            pool.anchor = ""
            pool.resume_grace_ms = 0
            pool.lock = threading.Condition()
            pool.stop = threading.Event()
            pool.parked = {}
            pool.reclaiming = set()
            pool.reservations = {}
            pool.workers = []
            workspace = pool.root / "session"
            other = pool.root / "other"
            workspace.mkdir()
            other.mkdir()
            owner = object()
            pool.reserve(workspace, owner)
            worker = Worker("sandweaver-test", 0, workspace)
            pool.workers = [worker]
            pool.park(owner, worker)

            resetting = threading.Event()
            finish_reset = threading.Event()
            waiting = threading.Event()
            condition_wait = pool.lock.wait

            def docker(*args, **kwargs):
                if len(args) > 4 and args[4] == RESET and not resetting.is_set():
                    resetting.set()
                    if not finish_reset.wait(3):
                        raise TimeoutError("Test did not unblock reset")
                return subprocess.CompletedProcess([], 0)

            def mark_wait(timeout):
                waiting.set()
                return condition_wait(timeout)

            with (patch("sandweaver.scheduler.docker", side_effect=docker),
                  patch.object(pool.lock, "wait", side_effect=mark_wait),
                  ThreadPoolExecutor(max_workers=2) as executor):
                reclaim = {}
                resume = {}
                competitor = executor.submit(pool.acquire, other, reclaim)
                try:
                    self.assertTrue(resetting.wait(3))
                    original = executor.submit(pool.acquire, workspace, resume, owner)
                    self.assertTrue(waiting.wait(3))
                    self.assertFalse(original.done())
                finally:
                    finish_reset.set()
                done, pending = wait((competitor, original), timeout=3,
                                     return_when=FIRST_COMPLETED)
                first, = done
                second, = pending
                pool.release(first.result())
                pool.release(second.result(timeout=3))
                self.assertGreater(reclaim["reclaim_ns"], 0)
                self.assertFalse(resume["resumed_parked"])

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
            pool.reservations = {}
            pool.parked = {}
            pool.reclaiming = set()

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
