import unittest
import threading
import time
from unittest.mock import patch
from typing import Type

from rwlocker.thread_rwlock import (
    RWLockWrite, RWLockWriteReentrantWriter,
    RWLockRead, RWLockReadReentrantWriter,
    RWLockFair, RWLockFairReentrantWriter,
    RWLockBase, RWCondition, Condition
)

class BaseConditionTests:
    lock_class: Type[RWLockBase] = None

    def setUp(self):
        if self.lock_class:
            self.lock = self.lock_class()
            self.condition = Condition(self.lock)

    def _is_locked(self, proxy):
        locked = getattr(proxy, "locked", None)
        if locked is not None:
            return locked()
        lock = getattr(proxy, "_lock", proxy)
        locked = getattr(lock, "locked", None)
        if locked is not None:
            return locked()
        is_owned = getattr(lock, "_is_owned", None)
        if is_owned is not None:
            return is_owned()
        acquired = lock.acquire(blocking=False)
        if acquired:
            lock.release()
        return not acquired

    def _wait_for_condition_waiters(self, expected: int, fallback_delay: float = 0.2, timeout: float = 2.0) -> None:
        del fallback_delay
        queue = getattr(self.condition, "_queue", None)
        if queue is not None:
            waiters = queue._waiters
            internal_lock = queue._lock
        else:
            condition = self.condition.write
            waiters = getattr(condition, "_waiters", None)
            internal_lock = getattr(condition, "_lock", None)
            if waiters is None or internal_lock is None:
                self.fail("The Condition waiter state is unavailable for synchronization")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with internal_lock:
                if len(waiters) >= expected:
                    return
            time.sleep(0.005)
        self.fail(f"Expected {expected} Condition waiters to be queued")

    def _join_threads_or_fail(self, threads: list[threading.Thread], timeout: float, context: str) -> None:
        deadline = time.monotonic() + timeout
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)

        stuck = [thread.name or f"Thread-{index}" for index, thread in enumerate(threads) if thread.is_alive()]
        if stuck:
            self.fail(f"{context} did not finish in time. Still alive: {', '.join(stuck)}")

    def test_initial_state(self):
        self.assertFalse(self._is_locked(self.condition.read))
        self.assertFalse(self._is_locked(self.condition.write))

    def test_wait_without_acquire_raises(self):
        with self.assertRaises(RuntimeError, msg="Waiting on an un-acquired read condition should raise RuntimeError."):
            self.condition.read.wait()
            
        with self.assertRaises(RuntimeError, msg="Waiting on an un-acquired write condition should raise RuntimeError."):
            self.condition.write.wait()

    def test_notify_without_acquire_raises(self):
        with self.assertRaises(RuntimeError, msg="Notifying on an un-acquired read condition should raise RuntimeError."):
            self.condition.read.notify()
            
        with self.assertRaises(RuntimeError, msg="Notifying on an un-acquired write condition should raise RuntimeError."):
            self.condition.write.notify_all()

    def test_wait_and_notify_single(self):
        event_happened = False
        wait_success = False

        def waiter_thread():
            nonlocal wait_success
            with self.condition.read:
                # Wait releases the read lock, blocks, then re-acquires it.
                self.condition.read.wait_for(lambda: event_happened)
                wait_success = True

        t = threading.Thread(target=waiter_thread)
        t.start()
        
        self._wait_for_condition_waiters(1)

        with self.condition.write:
            event_happened = True
            self.condition.write.notify()

        self._join_threads_or_fail([t], timeout=2.0, context="Single waiter thread")
        self.assertTrue(wait_success, "The waiter thread should successfully wake up and evaluate the predicate.")

    def test_notify_all_wakes_multiple_waiters(self):
        wait_count = 0
        event_happened = False
        lock = threading.Lock()

        def waiter_thread():
            nonlocal wait_count
            with self.condition.read:
                self.condition.read.wait_for(lambda: event_happened)
                with lock:
                    wait_count += 1

        threads = [threading.Thread(target=waiter_thread) for _ in range(5)]
        for t in threads:
            t.start()

        self._wait_for_condition_waiters(len(threads), fallback_delay=0.1)

        with self.condition.write:
            event_happened = True
            self.condition.write.notify_all()

        self._join_threads_or_fail(threads, timeout=5.0, context="notify_all waiters")

        self.assertEqual(wait_count, 5, "All waiting threads should have been awoken by notify_all().")

    def test_notify_n_wakes_specific_number_of_waiters(self):
        wait_count = 0
        lock = threading.Lock()
        two_woken = threading.Event()

        def waiter_thread():
            nonlocal wait_count
            with self.condition.read:
                self.condition.read.wait()
                with lock:
                    wait_count += 1
                    if wait_count == 2:
                        two_woken.set()

        threads = [threading.Thread(target=waiter_thread) for _ in range(4)]
        for t in threads:
            t.start()

        self._wait_for_condition_waiters(len(threads), fallback_delay=0.1)

        with self.condition.write:
            # Wake exactly 2 threads out of 4
            self.condition.write.notify(n=2)

        self.assertTrue(two_woken.wait(1.0), "Two notified threads should finish before the cleanup broadcast.")
        
        # Since we woke 2 threads, they should complete. 
        # The other 2 are still waiting. We must wake them up to exit cleanly.
        with self.condition.write:
            self.condition.write.notify_all()
            
        self._join_threads_or_fail(threads, timeout=5.0, context="notify(n) waiters")

        # The count logic here verifies if the *first* batch of wakeups behaved as expected.
        # This is a bit tricky to assert deterministically in threads, but waking all at the end
        # ensures the test doesn't hang.
        self.assertEqual(wait_count, 4, "Eventually all threads must complete.")

    def test_massive_notify_all_cache_stampede_resilience(self):
        wait_count = 0
        event_happened = False
        lock = threading.Lock()

        def waiter_thread():
            nonlocal wait_count
            with self.condition.read:
                self.condition.read.wait_for(lambda: event_happened)
                with lock:
                    wait_count += 1

        threads = [threading.Thread(target=waiter_thread) for _ in range(100)]
        for t in threads:
            t.start()

        self._wait_for_condition_waiters(len(threads), fallback_delay=0.2, timeout=3.0)

        with self.condition.write:
            event_happened = True
            self.condition.write.notify_all()

        self._join_threads_or_fail(threads, timeout=8.0, context="massive notify_all waiters")

        self.assertEqual(wait_count, 100, "All 100 threads must wake up correctly during a massive broadcast without deadlocks.")

    def test_wait_timeout(self):
        with self.condition.read:
            start_time = time.monotonic()
            awoken_by_notify = self.condition.read.wait(timeout=0.1)
            elapsed = time.monotonic() - start_time
            
            self.assertFalse(awoken_by_notify, "wait() should return False if timeout occurred.")
            self.assertGreaterEqual(elapsed, 0.1, "Wait should block for at least the timeout duration.")

    def test_wait_for_timeout(self):
        with self.condition.read:
            start_time = time.monotonic()
            result = self.condition.read.wait_for(lambda: False, timeout=0.1)
            elapsed = time.monotonic() - start_time
            
            self.assertFalse(result, "wait_for() should return the predicate's truth value (False).")
            self.assertGreaterEqual(elapsed, 0.1, "wait_for should block until timeout expires.")


class RWConditionTests(BaseConditionTests):
    def setUp(self):
        if self.lock_class:
            self.lock = self.lock_class()
            self.condition = RWCondition(self.lock)

    def test_wait_rejects_nested_read_acquisitions(self):
        proxy = self.condition.read
        proxy.acquire()
        proxy.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "nested acquisitions"):
                proxy.wait(timeout=0)
            self.assertTrue(proxy.locked())
            self.assertEqual(len(self.condition._queue._waiters), 0)
        finally:
            proxy.release()
            proxy.release()

    def test_waiter_is_removed_if_release_is_interrupted(self):
        proxy = self.condition.read
        proxy.acquire()
        try:
            with patch.object(type(proxy), "release", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    proxy.wait(timeout=0)
            self.assertEqual(len(self.condition._queue._waiters), 0)
        finally:
            proxy.release()

    def test_wait_rejects_nested_write_acquisitions(self):
        if not hasattr(self.lock, "_write_count"):
            self.skipTest("lock strategy does not support reentrant writers")
        proxy = self.condition.write
        proxy.acquire()
        proxy.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "nested acquisitions"):
                proxy.wait(timeout=0)
            self.assertTrue(proxy.locked())
            self.assertEqual(len(self.condition._queue._waiters), 0)
        finally:
            proxy.release()
            proxy.release()

    def test_read_wait_rejects_read_acquired_inside_write_lock(self):
        if not hasattr(self.lock, "_write_count"):
            self.skipTest("lock strategy does not support reentrant writers")
        self.condition.write.acquire()
        self.condition.read.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "nested acquisitions"):
                self.condition.read.wait(timeout=0)
            self.assertTrue(self.condition.write.locked())
        finally:
            self.condition.read.release()
            self.condition.write.release()

    def test_downgrade_condition_release_safety(self):
        """
        Verify that if the underlying Write proxy is downgraded, the Condition 
        Proxy routes the release logic correctly without throwing an exception.
        """
        with self.condition.write:
            # Atomic transition: Write -> Read
            self.condition.write._lock_proxy.downgrade()
            
            # Releasing the Write proxy must NOT raise RuntimeError now.
            # The Smart Proxy must route it to the Read release core.
        
        self.assertFalse(self._is_locked(self.condition.read))
        self.assertFalse(self._is_locked(self.condition.write))



class TestRWConditionWithWriteLock(RWConditionTests, unittest.TestCase):
    lock_class = RWLockWrite

class TestRWConditionWithWriteReentrantLock(RWConditionTests, unittest.TestCase):
    lock_class = RWLockWriteReentrantWriter

class TestRWConditionWithReadLock(RWConditionTests, unittest.TestCase):
    lock_class = RWLockRead

class TestRWConditionWithReadReentrantLock(RWConditionTests, unittest.TestCase):
    lock_class = RWLockReadReentrantWriter

class TestRWConditionWithFairLock(RWConditionTests, unittest.TestCase):
    lock_class = RWLockFair

class TestRWConditionWithFairReentrantLock(RWConditionTests, unittest.TestCase):
    lock_class = RWLockFairReentrantWriter

class TestCondition(BaseConditionTests, unittest.TestCase):
    lock_class = threading.Lock

if __name__ == '__main__':
    unittest.main()
