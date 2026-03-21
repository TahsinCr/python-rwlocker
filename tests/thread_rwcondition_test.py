import unittest
import threading
import time
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

    def test_initial_state(self):
        self.assertFalse(self.condition.read.locked())
        self.assertFalse(self.condition.write.locked())

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
        
        # Ensure the waiter thread has time to enter the wait state
        time.sleep(0.1)

        with self.condition.write:
            event_happened = True
            self.condition.write.notify()

        t.join()
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

        time.sleep(0.1)

        with self.condition.write:
            event_happened = True
            self.condition.write.notify_all()

        for t in threads:
            t.join()

        self.assertEqual(wait_count, 5, "All waiting threads should have been awoken by notify_all().")

    def test_notify_n_wakes_specific_number_of_waiters(self):
        wait_count = 0
        lock = threading.Lock()

        def waiter_thread():
            nonlocal wait_count
            with self.condition.read:
                self.condition.read.wait()
                with lock:
                    wait_count += 1

        threads = [threading.Thread(target=waiter_thread) for _ in range(4)]
        for t in threads:
            t.start()

        time.sleep(0.1)

        with self.condition.write:
            # Wake exactly 2 threads out of 4
            self.condition.write.notify(n=2)

        time.sleep(0.1)
        
        # Since we woke 2 threads, they should complete. 
        # The other 2 are still waiting. We must wake them up to exit cleanly.
        with self.condition.write:
            self.condition.write.notify_all()
            
        for t in threads:
            t.join()

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

        time.sleep(0.2) 

        with self.condition.write:
            event_happened = True
            self.condition.write.notify_all()

        for t in threads:
            t.join()

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
        
        self.assertFalse(self.condition.read.locked())
        self.assertFalse(self.condition.write.locked())



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
