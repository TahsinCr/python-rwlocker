import unittest
import threading
import time
from typing import Type

from rwlocker.thread_rwlock import (
    RWLockWrite, RWLockWriteReentrantWriter,
    RWLockRead, RWLockReadReentrantWriter,
    RWLockFIFO, RWLockFIFOReentrantWriter,
    RWLockBase
)

class BaseRWLockTests:
    lock_class: Type[RWLockBase] = None

    def setUp(self):
        if self.lock_class:
            self.lock = self.lock_class()

    def test_initial_state(self):
        self.assertFalse(self.lock.read.locked())
        self.assertFalse(self.lock.write.locked())

    def test_lock_status_reflection(self):
        self.lock.read.acquire()
        self.assertTrue(self.lock.read.locked())
        self.assertFalse(self.lock.write.locked())
        self.lock.read.release()
        
        self.lock.write.acquire()
        self.assertFalse(self.lock.read.locked())
        self.assertTrue(self.lock.write.locked())
        self.lock.write.release()

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

    def test_context_managers(self):
        with self.lock.write:
            self.assertTrue(self.lock.write.locked())
        self.assertFalse(self.lock.write.locked())

        with self.lock.read:
            self.assertTrue(self.lock.read.locked())
        self.assertFalse(self.lock.read.locked())

    def test_downgrade_functionality(self):
        self.lock.write.acquire()
        self.lock.write.downgrade()
        
        self.assertTrue(self.lock.read.acquire(blocking=False))
        self.lock.read.release()
   
        self.assertFalse(self.lock.write.acquire(blocking=False))

        self.lock.read.release()
        self.assertFalse(self.lock.read.locked())

    def test_timeout_functionality(self):
        self.lock.write.acquire()
        
        start_time = time.monotonic()
        success = self.lock.read.acquire(timeout=0.1)
        elapsed = time.monotonic() - start_time
        
        self.assertFalse(success, "Acquire should fail when timeout is reached.")
        self.assertGreaterEqual(elapsed, 0.1, "Elapsed time should be greater than or equal to the specified timeout.")
        self.lock.write.release()

    def test_unacquired_release_raises(self):
        with self.assertRaises(RuntimeError, msg="Releasing an unacquired write lock should raise RuntimeError."):
            self.lock.write.release()
        
        with self.assertRaises(RuntimeError, msg="Releasing an unacquired read lock should raise RuntimeError."):
            self.lock.read.release()


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


class TestRWLockWrite(BaseRWLockTests, unittest.TestCase):
    lock_class = RWLockWrite

class TestRWLockWriteReentrantWriter(ReentrantWriterTestsMixin, BaseRWLockTests, unittest.TestCase):
    lock_class = RWLockWriteReentrantWriter

class TestRWLockRead(BaseRWLockTests, unittest.TestCase):
    lock_class = RWLockRead

class TestRWLockReadReentrantWriter(ReentrantWriterTestsMixin, BaseRWLockTests, unittest.TestCase):
    lock_class = RWLockReadReentrantWriter

class TestRWLockFIFO(BaseRWLockTests, unittest.TestCase):
    lock_class = RWLockFIFO

class TestRWLockFIFOReentrantWriter(ReentrantWriterTestsMixin, BaseRWLockTests, unittest.TestCase):
    lock_class = RWLockFIFOReentrantWriter

if __name__ == '__main__':
    unittest.main()
