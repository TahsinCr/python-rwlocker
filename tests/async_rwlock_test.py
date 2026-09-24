import unittest
import asyncio
from typing import Type

from rwlocker.async_rwlock import (
    AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
    AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
    AsyncRWLockReaderPhaseFair, AsyncRWLockReaderPhaseFairReentrantWriter,
    AsyncRWLockFair, AsyncRWLockFairReentrantWriter,
    AsyncRWLockBase, AsyncLock
)

class BaseAsyncLockTests:
    lock_class: Type[AsyncRWLockBase] = None

    async def asyncSetUp(self):
        if self.lock_class:
            self.lock = self.lock_class()

    async def test_initial_state(self):
        self.assertFalse(self.lock.read.locked())
        self.assertFalse(self.lock.write.locked())

    async def test_multiple_readers_concurrently(self):
        acquired_flags = []

        async def reader_task():
            async with self.lock.read:
                acquired_flags.append(True)
                await asyncio.sleep(0.05)

        tasks = [asyncio.create_task(reader_task()) for _ in range(3)]
        await asyncio.gather(*tasks)

        self.assertEqual(len(acquired_flags), 3, "All reader tasks should have acquired the lock concurrently.")

    async def test_context_managers(self):
        async with self.lock.write:
            self.assertTrue(self.lock.write.locked())
        self.assertFalse(self.lock.write.locked())

        async with self.lock.read:
            self.assertTrue(self.lock.read.locked())
        self.assertFalse(self.lock.read.locked())

    async def test_unacquired_release_raises(self):
        with self.assertRaises(RuntimeError, msg="Releasing an unacquired write lock should raise RuntimeError."):
            self.lock.write.release()
        
        with self.assertRaises(RuntimeError, msg="Releasing an unacquired read lock should raise RuntimeError."):
            self.lock.read.release()

    async def test_reader_release_must_match_acquiring_task(self):
        if not hasattr(self.lock, "_reader_owners"):
            self.skipTest("The standard asyncio lock adapter follows asyncio.Lock semantics.")
        acquired = asyncio.Event()
        release_reader = asyncio.Event()

        async def reader():
            await self.lock.read.acquire()
            acquired.set()
            await release_reader.wait()
            self.lock.read.release()

        task = asyncio.create_task(reader())
        await acquired.wait()
        with self.assertRaisesRegex(RuntimeError, "current task"):
            self.lock.read.release()
        self.assertTrue(self.lock.read.locked())
        release_reader.set()
        await task

    async def test_exception_handling_in_context_manager(self):
        class CustomException(Exception): pass
        
        try:
            async with self.lock.write:
                raise CustomException()
        except CustomException:
            pass
        self.assertFalse(self.lock.write.locked(), "Write lock must be released if an exception occurs inside the context.")

        try:
            async with self.lock.read:
                raise CustomException()
        except CustomException:
            pass
        self.assertFalse(self.lock.read.locked(), "Read lock must be released if an exception occurs inside the context.")

class AsyncRWLockTests(BaseAsyncLockTests):
    async def _wait_for_waiters(self, readers=0, writers=0, timeout=1.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.lock.read.those_waiting >= readers and self.lock.write.those_waiting >= writers:
                return
            await asyncio.sleep(0)
        self.fail(f"Expected at least {readers} readers and {writers} writers to be queued")

    async def test_lock_status_reflection(self):
        await self.lock.read.acquire()
        self.assertTrue(self.lock.read.locked())
        self.assertFalse(self.lock.write.locked())
        self.lock.read.release()
        
        await self.lock.write.acquire()
        self.assertFalse(self.lock.read.locked())
        self.assertTrue(self.lock.write.locked())
        self.lock.write.release()
    
    async def test_timeout_functionality(self):
        await self.lock.write.acquire()
        
        start_time = asyncio.get_running_loop().time()
        success = False
        try:
            await asyncio.wait_for(self.lock.read.acquire(), timeout=0.1)
            success = True
        except asyncio.TimeoutError:
            pass
            
        elapsed = asyncio.get_running_loop().time() - start_time
        
        self.assertFalse(success, "Acquire should fail when timeout is reached.")
        self.assertGreaterEqual(elapsed, 0.09, "Elapsed time should reflect the timeout duration.")
        self.lock.write.release()

    async def test_writer_exclusivity(self):
        self.assertTrue(await self.lock.write.acquire())
        
        read_success = await self.lock.read.acquire(blocking=False)
        write_success = await self.lock.write.acquire(blocking=False)
        
        self.assertFalse(read_success, "No reader should be allowed while a writer is active.")
        self.assertFalse(write_success, "No other writer should be allowed while a writer is active.")
        
        self.lock.write.release()

    async def test_reader_blocks_writer(self):
        self.assertTrue(await self.lock.read.acquire())
        
        write_success = await self.lock.write.acquire(blocking=False)
        self.assertFalse(write_success, "A writer cannot enter while a reader is present.")
        
        self.lock.read.release()

    async def test_downgrade_functionality(self):
        await self.lock.write.acquire()
        self.lock.write.downgrade()
        
        self.assertTrue(await self.lock.read.acquire(blocking=False))
        self.lock.read.release()
   
        self.assertFalse(await self.lock.write.acquire(blocking=False))

        self.lock.read.release()
        self.assertFalse(self.lock.read.locked())

    async def test_writer_downgrade_wakes_readers(self):
        await self.lock.write.acquire()
        
        reader_acquired = asyncio.Event()
        async def reader_task():
            async with self.lock.read:
                reader_acquired.set()

        t = asyncio.create_task(reader_task())
        await self._wait_for_waiters(readers=1)
        self.assertFalse(reader_acquired.is_set(), "Reader should block while write lock is held.")
        
        self.lock.write.downgrade()
        await asyncio.wait_for(reader_acquired.wait(), timeout=1.0)
        self.assertTrue(reader_acquired.is_set(), "Reader should wake up when writer downgrades.")
        
        self.lock.read.release()
        await t

    async def test_manual_read_release_after_downgrade_does_not_poison_next_write_release(self):
        self.assertTrue(await self.lock.write.acquire())
        self.lock.write.downgrade()
        self.lock.read.release()
        self.assertTrue(await self.lock.write.acquire())
        self.lock.write.release()
        self.assertFalse(self.lock.write.locked())

    async def test_task_cancellation_during_wait(self):
        await self.lock.write.acquire()
        
        wait_started = asyncio.Event()
        async def reader_task():
            wait_started.set()
            await self.lock.read.acquire()

        t = asyncio.create_task(reader_task())
        await wait_started.wait()
        await self._wait_for_waiters(readers=1)
        
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
            
        self.assertTrue(self.lock.write.locked(), "Lock must remain acquired safely.")
        self.lock.write.release()
        
        try:
            async def acquire_and_release():
                await self.lock.read.acquire()
                self.lock.read.release()

            await asyncio.wait_for(acquire_and_release(), timeout=0.5)
        except asyncio.TimeoutError:
            self.fail("Could not acquire lock after a waiting task was cancelled. Wait queue might be corrupted.")

class ReentrantWriterAsyncTestsMixin:
    async def test_reentrant_write(self):
        async with self.lock.write:
            success = await self.lock.write.acquire(blocking=False)
            self.assertTrue(success, "ReentrantWriter must allow nested writing from the same task.")
            self.assertTrue(self.lock.write.locked())
            self.lock.write.release()
        self.assertFalse(self.lock.write.locked(), "Lock should be fully released after all nested context exits.")

    async def test_reentrant_downgrade_exception(self):
        await self.lock.write.acquire()
        await self.lock.write.acquire()
        
        with self.assertRaisesRegex(RuntimeError, "Cannot downgrade a nested write lock"):
            self.lock.write.downgrade()
            
        self.lock.write.release()
        self.lock.write.release()

    async def test_cross_task_release_protection(self):
        await self.lock.write.acquire()
        
        exception_caught = False
        async def malicious_task():
            nonlocal exception_caught
            try:
                self.lock.write.release()
            except RuntimeError as e:
                if "Permission denied" in str(e):
                    exception_caught = True

        t = asyncio.create_task(malicious_task())
        await t
        
        self.assertTrue(exception_caught, "The release process from a different task must be blocked.")
        self.lock.write.release()

    async def test_writer_exclusivity(self):
        self.assertTrue(await self.lock.write.acquire())
        self.assertTrue(await self.lock.read.acquire(blocking=False))
        self.lock.read.release()

        other_task_read = True
        other_task_write = True
        
        async def other_task():
            nonlocal other_task_read, other_task_write
            other_task_read = await self.lock.read.acquire(blocking=False)
            other_task_write = await self.lock.write.acquire(blocking=False)

        t = asyncio.create_task(other_task())
        await t

        self.assertFalse(other_task_read, "No other task should acquire the read lock.")
        self.assertFalse(other_task_write, "No other task should acquire the write lock.")
        
        self.lock.write.release()
    
    async def test_timeout_functionality(self):
        await self.lock.write.acquire()
        
        timeout_failed = False
        async def other_task():
            nonlocal timeout_failed
            try:
                await asyncio.wait_for(self.lock.read.acquire(), timeout=0.1)
            except asyncio.TimeoutError:
                timeout_failed = True

        start_time = asyncio.get_running_loop().time()
        t = asyncio.create_task(other_task())
        await t
        elapsed = asyncio.get_running_loop().time() - start_time
        
        self.assertTrue(timeout_failed, "Another task should fail to acquire the lock and timeout.")
        self.assertGreaterEqual(elapsed, 0.09)
        
        self.lock.write.release()


class FairPhaseAsyncTestsMixin:
    async def test_late_reader_barging_behavior(self):
        await self.lock.write.acquire()
        release_first_reader = asyncio.Event()
        first_reader_entered = asyncio.Event()
        late_reader_entered = asyncio.Event()
        writer_entered = asyncio.Event()
        order: list[str] = []

        async def first_reader():
            async with self.lock.read:
                order.append('first_reader')
                first_reader_entered.set()
                await asyncio.wait_for(release_first_reader.wait(), timeout=1.0)

        async def late_reader():
            async with self.lock.read:
                order.append('late_reader')
                late_reader_entered.set()

        async def writer():
            async with self.lock.write:
                order.append('writer')
                writer_entered.set()

        first_reader_task = asyncio.create_task(first_reader())
        writer_task = asyncio.create_task(writer())

        await self._wait_for_waiters(readers=1, writers=1)
        self.lock.write.release()

        await asyncio.wait_for(first_reader_entered.wait(), timeout=1.0)
        late_reader_task = asyncio.create_task(late_reader())

        if self.expect_late_reader_barging:
            await asyncio.wait_for(late_reader_entered.wait(), timeout=1.0)
            self.assertFalse(writer_entered.is_set(), "Queued writer should still wait while the open reader phase continues.")
        else:
            await self._wait_for_waiters(readers=1)
            self.assertFalse(late_reader_entered.is_set(), "Strict fair locks must block readers that arrive after the reader phase has started.")
            self.assertFalse(writer_entered.is_set(), "Writer should still be waiting while the reserved reader is active.")

        release_first_reader.set()
        await asyncio.wait_for(first_reader_task, timeout=1.0)
        await asyncio.wait_for(writer_task, timeout=1.0)
        await asyncio.wait_for(late_reader_task, timeout=1.0)

        self.assertEqual(order[0], 'first_reader')
        if self.expect_late_reader_barging:
            self.assertEqual(order[1], 'late_reader')
            self.assertEqual(order[2], 'writer')
        else:
            self.assertEqual(order[1], 'writer')
            self.assertEqual(order[2], 'late_reader')


class TestAsyncRWLockWrite(AsyncRWLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockWrite

class TestAsyncRWLockWriteReentrantWriter(ReentrantWriterAsyncTestsMixin, AsyncRWLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockWriteReentrantWriter

class TestAsyncRWLockRead(AsyncRWLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockRead

class TestAsyncRWLockReadReentrantWriter(ReentrantWriterAsyncTestsMixin, AsyncRWLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockReadReentrantWriter

class TestAsyncRWLockReaderPhaseFair(FairPhaseAsyncTestsMixin, AsyncRWLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockReaderPhaseFair
    expect_late_reader_barging = True

class TestAsyncRWLockReaderPhaseFairReentrantWriter(ReentrantWriterAsyncTestsMixin, FairPhaseAsyncTestsMixin, AsyncRWLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockReaderPhaseFairReentrantWriter
    expect_late_reader_barging = True

class TestAsyncRWLockFair(FairPhaseAsyncTestsMixin, AsyncRWLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockFair
    expect_late_reader_barging = False

class TestAsyncRWLockFairReentrantWriter(ReentrantWriterAsyncTestsMixin, FairPhaseAsyncTestsMixin, AsyncRWLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockFairReentrantWriter
    expect_late_reader_barging = False

class TestAsyncLock(BaseAsyncLockTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncLock


if __name__ == '__main__':
    unittest.main()
