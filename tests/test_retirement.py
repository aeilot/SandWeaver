from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import subprocess
import tempfile
import threading
import time
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


class ResumeGraceTest(unittest.TestCase):
    GRACE_MS = 300

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        pool = Pool.__new__(Pool)
        pool.root = Path(self.directory.name).resolve()
        pool.maximum = 1
        pool.mount = DEFAULT_MOUNT
        pool.anchor = ""
        pool.resume_grace_ms = self.GRACE_MS
        pool.lock = threading.Condition()
        pool.stop = threading.Event()
        pool.parked = {}
        pool.reclaiming = set()
        pool.reservations = {}
        pool.workers = []
        self.resuming_workspace = pool.root / "resuming"
        parked_workspace = pool.root / "parked"
        self.resuming_workspace.mkdir()
        parked_workspace.mkdir()
        self.resuming_owner = object()
        self.parked_owner = object()
        pool.reserve(self.resuming_workspace, self.resuming_owner)
        pool.reserve(parked_workspace, self.parked_owner)
        # The resuming session's own worker is gone; the only worker is parked by another session.
        worker = Worker("sandweaver-test", 0, parked_workspace)
        pool.workers = [worker]
        pool.park(self.parked_owner, worker)
        self.pool, self.worker = pool, worker
        patcher = patch("sandweaver.scheduler.docker",
                        return_value=subprocess.CompletedProcess([], 0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def acquire(self, resuming):
        timing = {}
        started = time.monotonic()
        worker = self.pool.acquire(self.resuming_workspace, timing, self.resuming_owner,
                                   resuming=resuming)
        return worker, timing, time.monotonic() - started

    def test_resuming_session_waits_out_grace_before_reclaiming(self):
        worker, timing, elapsed = self.acquire(resuming=True)
        self.assertIs(worker, self.worker)
        self.assertGreaterEqual(elapsed, self.GRACE_MS / 1000)
        self.assertGreater(timing["reclaim_ns"], 0)
        self.assertNotIn(self.parked_owner, self.pool.parked)

    def test_resuming_session_takes_capacity_freed_during_grace(self):
        releaser = threading.Timer(0.05, self.pool.release_parked, (self.parked_owner,))
        releaser.start()
        self.addCleanup(releaser.cancel)
        worker, timing, elapsed = self.acquire(resuming=True)
        self.assertIs(worker, self.worker)
        self.assertEqual(timing["reclaim_ns"], 0)
        self.assertLess(elapsed, self.GRACE_MS / 1000)

    def test_new_claim_reclaims_without_grace(self):
        worker, timing, elapsed = self.acquire(resuming=False)
        self.assertIs(worker, self.worker)
        self.assertGreater(timing["reclaim_ns"], 0)
        self.assertLess(elapsed, self.GRACE_MS / 1000)
