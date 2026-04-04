import unittest
import threading
import time
from typing import Type
from unittest.mock import patch

import rwlocker.thread_rwlock as thread_rwlock_mod
from rwlocker.thread_rwlock import (
    RWLockWrite, RWLockWriteReentrantWriter,
    RWLockRead, RWLockReadReentrantWriter,
    RWLockReaderPhaseFair, RWLockReaderPhaseFairReentrantWriter,
    RWLockFair, RWLockFairReentrantWriter,
    RWLockBase, Lock
)

class BaseLockTests:
    lock_class: Type[RWLockBase] = None
    lock_inner: Type[threading.Lock] = None

    def setUp(self):
        if self.lock_class:
            self.lock = self.lock_class(self.lock_inner() if self.lock_inner else None)

    def test_initial_state(self):
        self.assertFalse(self.lock.read.locked())
        self.assertFalse(self.lock.write.locked())

    def test_multiple_readers_concurrently(self):
        acquired_flags = []

        def reader_func():
            with self.lock.read:
                acquired_flags.append(True)
                time.sleep(0.05)

        threads = [threading.Thread(target=reader_func) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(acquired_flags), 3, "All readers should have acquired the lock concurrently.")

    def test_context_managers(self):
        with self.lock.write:
            self.assertTrue(self.lock.write.locked())
        self.assertFalse(self.lock.write.locked())

        with self.lock.read:
            self.assertTrue(self.lock.read.locked())
        self.assertFalse(self.lock.read.locked())

    def test_unacquired_release_raises(self):
        with self.assertRaises(RuntimeError, msg="Releasing an unacquired write lock should raise RuntimeError."):
            self.lock.write.release()
        
        with self.assertRaises(RuntimeError, msg="Releasing an unacquired read lock should raise RuntimeError."):
            self.lock.read.release()

    def test_exception_handling_in_context_manager(self):
        class CustomException(Exception): pass
        
        try:
            with self.lock.write:
                raise CustomException()
        except CustomException:
            pass
        self.assertFalse(self.lock.write.locked(), "Write lock must be released if an exception occurs inside the context.")

        try:
            with self.lock.read:
                raise CustomException()
        except CustomException:
            pass
        self.assertFalse(self.lock.read.locked(), "Read lock must be released if an exception occurs inside the context.")

class RWLockTests(BaseLockTests):
    def test_lock_status_reflection(self):
        self.lock.read.acquire()
        self.assertTrue(self.lock.read.locked())
        self.assertFalse(self.lock.write.locked())
        self.lock.read.release()
        
        self.lock.write.acquire()
        self.assertFalse(self.lock.read.locked())
        self.assertTrue(self.lock.write.locked())
        self.lock.write.release()

    def test_timeout_functionality(self):
        self.lock.write.acquire()
        
        start_time = time.monotonic()
        success = self.lock.read.acquire(timeout=0.1)
        elapsed = time.monotonic() - start_time
        
        self.assertFalse(success, "Acquire should fail when timeout is reached.")
        self.assertGreaterEqual(elapsed, 0.1, "Elapsed time should be greater than or equal to the specified timeout.")
        self.lock.write.release()

    def test_writer_exclusivity(self):
        self.assertTrue(self.lock.write.acquire())
        
        read_success = self.lock.read.acquire(blocking=False)
        write_success = self.lock.write.acquire(blocking=False)
        
        self.assertFalse(read_success, "No reader should be allowed while a writer is active.")
        self.assertFalse(write_success, "No other writer should be allowed while a writer is active.")
        
        self.lock.write.release()

    def test_reader_blocks_writer(self):
        self.assertTrue(self.lock.read.acquire())
        
        write_success = self.lock.write.acquire(blocking=False)
        self.assertFalse(write_success, "A writer cannot enter while a reader is present.")
        
        self.lock.read.release()

    def test_downgrade_functionality(self):
        self.lock.write.acquire()
        self.lock.write.downgrade()
        
        self.assertTrue(self.lock.read.acquire(blocking=False))
        self.lock.read.release()
   
        self.assertFalse(self.lock.write.acquire(blocking=False))

        self.lock.read.release()
        self.assertFalse(self.lock.read.locked())

    def test_writer_downgrade_wakes_readers(self):
        self.lock.write.acquire()
        
        reader_acquired = threading.Event()
        def reader_func():
            with self.lock.read:
                reader_acquired.set()

        t = threading.Thread(target=reader_func)
        t.start()
        
        time.sleep(0.05)
        self.assertFalse(reader_acquired.is_set(), "Reader should block while write lock is held.")
        
        self.lock.write.downgrade()
        reader_acquired.wait(timeout=1.0)
        self.assertTrue(reader_acquired.is_set(), "Reader should wake up when writer downgrades.")
        
        self.lock.read.release()
        t.join()

    def test_manual_read_release_after_downgrade_does_not_poison_next_write_release(self):
        self.assertTrue(self.lock.write.acquire())
        self.lock.write.downgrade()
        self.lock.read.release()
        self.assertTrue(self.lock.write.acquire())
        self.lock.write.release()
        self.assertFalse(self.lock.write.locked())

    def test_timeout_removes_waiter_from_queue(self):
        self.lock.write.acquire()
        t = threading.Thread(target=lambda: self.lock.read.acquire(timeout=0.05))
        t.start()
        t.join()
        
        try:
            self.lock.write.release()
        except Exception as e:
            self.fail(f"Releasing write lock after a timed-out read attempt raised an exception: {e}")

class ReentrantWriterTestsMixin:
    def test_reentrant_write(self):
        with self.lock.write:
            success = self.lock.write.acquire(blocking=False)
            self.assertTrue(success, "ReentrantWriter must allow nested writing from the same thread.")
            self.assertTrue(self.lock.write.locked())
            self.lock.write.release()
        self.assertFalse(self.lock.write.locked(), "Lock should be fully released after all nested context exits.")

    def test_reentrant_downgrade_exception(self):
        self.lock.write.acquire()
        self.lock.write.acquire()
        
        with self.assertRaisesRegex(RuntimeError, "Cannot downgrade a nested write lock"):
            self.lock.write.downgrade()
            
        self.lock.write.release()
        self.lock.write.release()

    def test_cross_thread_release_protection(self):
        self.lock.write.acquire()
        
        exception_caught = False
        def malicious_thread():
            nonlocal exception_caught
            try:
                self.lock.write.release()
            except RuntimeError as e:
                if "Permission denied" in str(e):
                    exception_caught = True

        t = threading.Thread(target=malicious_thread)
        t.start()
        t.join()
        
        self.assertTrue(exception_caught, "The release process from a different thread must be blocked.")
        self.lock.write.release()

    def test_writer_exclusivity(self):
        self.assertTrue(self.lock.write.acquire())
        self.assertTrue(self.lock.read.acquire(blocking=False))
        self.lock.read.release()

        other_thread_read = True
        other_thread_write = True
        
        def other_thread():
            nonlocal other_thread_read, other_thread_write
            other_thread_read = self.lock.read.acquire(blocking=False)
            other_thread_write = self.lock.write.acquire(blocking=False)

        t = threading.Thread(target=other_thread)
        t.start()
        t.join()

        self.assertFalse(other_thread_read, "No other thread should acquire the read lock.")
        self.assertFalse(other_thread_write, "No other thread should acquire the write lock.")
        
        self.lock.write.release()

    def test_timeout_functionality(self):
        self.lock.write.acquire()
        
        timeout_failed = False
        def other_thread():
            nonlocal timeout_failed
            if not self.lock.read.acquire(timeout=0.1):
                timeout_failed = True

        start_time = time.monotonic()
        t = threading.Thread(target=other_thread)
        t.start()
        t.join()
        elapsed = time.monotonic() - start_time
        
        self.assertTrue(timeout_failed, "Another thread should fail to acquire the lock and timeout.")
        self.assertGreaterEqual(elapsed, 0.1)
        
        self.lock.write.release()


class FairPhaseTestsMixin:
    def _start_waiting_reader(self, entered_event: threading.Event, release_event: threading.Event):
        def reader():
            with self.lock.read:
                entered_event.set()
                release_event.wait(1.0)

        thread = threading.Thread(target=reader)
        thread.start()
        return thread

    def _start_waiting_writer(self, entered_event: threading.Event):
        def writer():
            with self.lock.write:
                entered_event.set()

        thread = threading.Thread(target=writer)
        thread.start()
        return thread

    def test_reader_phase_drains_waiting_readers_before_writer(self):
        self.lock.write.acquire()
        release_readers = threading.Event()
        first_reader_entered = threading.Event()
        second_reader_entered = threading.Event()
        writer_entered = threading.Event()

        readers = [
            self._start_waiting_reader(first_reader_entered, release_readers),
            self._start_waiting_reader(second_reader_entered, release_readers),
        ]
        writer = self._start_waiting_writer(writer_entered)

        time.sleep(0.05)
        self.lock.write.release()

        self.assertTrue(first_reader_entered.wait(1.0), "First waiting reader should enter the fair reader phase.")
        self.assertTrue(second_reader_entered.wait(1.0), "Second waiting reader should drain before the waiting writer.")
        self.assertFalse(writer_entered.is_set(), "Writer must not cut in before the queued reader phase is drained.")

        release_readers.set()
        for reader in readers:
            reader.join()
        writer.join(timeout=1.0)
        self.assertFalse(writer.is_alive(), "Writer should enter after the reader phase completes.")
        self.assertTrue(writer_entered.is_set())

    def test_downgrade_starts_reader_phase_before_writer(self):
        self.lock.write.acquire()
        release_readers = threading.Event()
        first_reader_entered = threading.Event()
        second_reader_entered = threading.Event()
        writer_entered = threading.Event()

        readers = [
            self._start_waiting_reader(first_reader_entered, release_readers),
            self._start_waiting_reader(second_reader_entered, release_readers),
        ]
        writer = self._start_waiting_writer(writer_entered)

        time.sleep(0.05)
        self.lock.write.downgrade()

        self.assertTrue(first_reader_entered.wait(1.0), "Downgrade should let queued readers join the new reader phase.")
        self.assertTrue(second_reader_entered.wait(1.0), "Queued readers should continue draining after downgrade.")
        self.assertFalse(writer_entered.is_set(), "Writer must wait until the downgraded reader phase finishes.")

        release_readers.set()
        self.lock.write.release()
        for reader in readers:
            reader.join()
        writer.join(timeout=1.0)
        self.assertFalse(writer.is_alive(), "Writer should proceed once downgraded readers are done.")
        self.assertTrue(writer_entered.is_set())

    def test_reader_phase_can_use_reader_notify_all(self):
        self.lock.write.acquire()
        release_readers = threading.Event()
        reader_entered = threading.Event()
        writer_entered = threading.Event()
        reader_notify_all_calls = 0
        original_notify_all = thread_rwlock_mod.ThreadWaitQueue.notify_all

        def counting_notify_all(queue_self):
            nonlocal reader_notify_all_calls
            if queue_self is self.lock.read.condition:
                reader_notify_all_calls += 1
            return original_notify_all(queue_self)

        with patch.object(thread_rwlock_mod.ThreadWaitQueue, 'notify_all', new=counting_notify_all):
            reader = self._start_waiting_reader(reader_entered, release_readers)
            writer = self._start_waiting_writer(writer_entered)
            time.sleep(0.05)
            self.lock.write.release()

            self.assertTrue(reader_entered.wait(1.0))
            self.assertFalse(writer_entered.is_set())

            release_readers.set()
            reader.join()
            writer.join(timeout=1.0)

        if isinstance(self.lock, (RWLockFair, RWLockFairReentrantWriter)):
            self.assertEqual(
                reader_notify_all_calls,
                0,
                "Strict fair should still avoid reader notify_all broadcasts."
            )
        else:
            self.assertGreater(
                reader_notify_all_calls,
                0,
                "Reader-phase fair should now use aggressive reader wakeups."
            )
        self.assertFalse(writer.is_alive())

    def test_late_reader_barging_behavior(self):
        self.lock.write.acquire()
        release_first_reader = threading.Event()
        first_reader_entered = threading.Event()
        late_reader_entered = threading.Event()
        writer_entered = threading.Event()
        order: list[str] = []

        def first_reader():
            with self.lock.read:
                order.append('first_reader')
                first_reader_entered.set()
                release_first_reader.wait(1.0)

        def late_reader():
            with self.lock.read:
                order.append('late_reader')
                late_reader_entered.set()

        def writer():
            with self.lock.write:
                order.append('writer')
                writer_entered.set()

        first_reader_thread = threading.Thread(target=first_reader)
        writer_thread = threading.Thread(target=writer)
        first_reader_thread.start()
        writer_thread.start()

        time.sleep(0.05)
        self.lock.write.release()

        self.assertTrue(first_reader_entered.wait(1.0))
        late_reader_thread = threading.Thread(target=late_reader)
        late_reader_thread.start()

        if self.expect_late_reader_barging:
            self.assertTrue(late_reader_entered.wait(1.0), "Reader-phase fair locks should allow late readers to join an open reader phase.")
            self.assertFalse(writer_entered.is_set(), "Queued writer should still wait while the open reader phase continues.")
        else:
            time.sleep(0.1)
            self.assertFalse(late_reader_entered.is_set(), "Strict fair locks must block readers that arrive after the reader phase has started.")
            self.assertFalse(writer_entered.is_set(), "Writer should still be waiting while the reserved reader is active.")

        release_first_reader.set()
        first_reader_thread.join()
        writer_thread.join(timeout=1.0)
        late_reader_thread.join(timeout=1.0)

        self.assertFalse(writer_thread.is_alive())
        self.assertFalse(late_reader_thread.is_alive())
        self.assertEqual(order[0], 'first_reader')
        if self.expect_late_reader_barging:
            self.assertEqual(order[1], 'late_reader')
            self.assertEqual(order[2], 'writer')
        else:
            self.assertEqual(order[1], 'writer')
            self.assertEqual(order[2], 'late_reader')


class TestRWLockWrite(RWLockTests, unittest.TestCase):
    lock_class = RWLockWrite

class TestRWLockWriteReentrantWriter(ReentrantWriterTestsMixin, RWLockTests, unittest.TestCase):
    lock_class = RWLockWriteReentrantWriter

class TestRWLockRead(RWLockTests, unittest.TestCase):
    lock_class = RWLockRead

class TestRWLockReadReentrantWriter(ReentrantWriterTestsMixin, RWLockTests, unittest.TestCase):
    lock_class = RWLockReadReentrantWriter

class TestRWLockReaderPhaseFair(FairPhaseTestsMixin, RWLockTests, unittest.TestCase):
    lock_class = RWLockReaderPhaseFair
    expect_late_reader_barging = True

class TestRWLockReaderPhaseFairReentrantWriter(FairPhaseTestsMixin, ReentrantWriterTestsMixin, RWLockTests, unittest.TestCase):
    lock_class = RWLockReaderPhaseFairReentrantWriter
    expect_late_reader_barging = True

class TestRWLockFair(FairPhaseTestsMixin, RWLockTests, unittest.TestCase):
    lock_class = RWLockFair
    expect_late_reader_barging = False

class TestRWLockFairReentrantWriter(FairPhaseTestsMixin, ReentrantWriterTestsMixin, RWLockTests, unittest.TestCase):
    lock_class = RWLockFairReentrantWriter
    expect_late_reader_barging = False

class TestLock(BaseLockTests, unittest.TestCase):
    lock_class = Lock

class TestRLock(BaseLockTests, unittest.TestCase):
    lock_class = Lock
    lock_inner = threading.RLock


if __name__ == '__main__':
    unittest.main()
