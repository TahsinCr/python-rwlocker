import unittest
import asyncio
from typing import Type

from rwlocker.async_rwlock import (
    AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
    AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
    AsyncRWLockFIFO, AsyncRWLockFIFOReentrantWriter,
    AsyncRWLockBase
)

class BaseAsyncRWLockTests(unittest.IsolatedAsyncioTestCase):
    lock_class: Type[AsyncRWLockBase] = None

    async def asyncSetUp(self):
        if self.lock_class:
            self.lock = self.lock_class()

    async def test_initial_state(self):
        if not self.lock_class: return
        self.assertFalse(await self.lock.read.locked())
        self.assertFalse(await self.lock.write.locked())

    async def test_lock_status_reflection(self):
        if not self.lock_class: return
        await self.lock.read.acquire()
        self.assertTrue(await self.lock.read.locked())
        self.assertFalse(await self.lock.write.locked())
        await self.lock.read.release()
        
        await self.lock.write.acquire()
        self.assertFalse(await self.lock.read.locked())
        self.assertTrue(await self.lock.write.locked())
        await self.lock.write.release()

    async def test_multiple_readers_concurrently(self):
        if not self.lock_class: return
        acquired_flags = []

        async def reader_task():
            async with self.lock.read:
                acquired_flags.append(True)
                await asyncio.sleep(0.05)

        tasks = [asyncio.create_task(reader_task()) for _ in range(3)]
        await asyncio.gather(*tasks)

        self.assertEqual(len(acquired_flags), 3, "All reader tasks should have acquired the lock concurrently.")

    async def test_writer_exclusivity(self):
        if not self.lock_class: return
        self.assertTrue(await self.lock.write.acquire())
        
        read_success = await self.lock.read.acquire(blocking=False)
        write_success = await self.lock.write.acquire(blocking=False)
        
        self.assertFalse(read_success, "No reader should be allowed while a writer is active.")
        self.assertFalse(write_success, "No other writer should be allowed while a writer is active.")
        
        await self.lock.write.release()

    async def test_reader_blocks_writer(self):
        if not self.lock_class: return
        self.assertTrue(await self.lock.read.acquire())
        
        write_success = await self.lock.write.acquire(blocking=False)
        self.assertFalse(write_success, "A writer cannot enter while a reader is present.")
        
        await self.lock.read.release()

    async def test_context_managers(self):
        if not self.lock_class: return
        async with self.lock.write:
            self.assertTrue(await self.lock.write.locked())
        self.assertFalse(await self.lock.write.locked())

        async with self.lock.read:
            self.assertTrue(await self.lock.read.locked())
        self.assertFalse(await self.lock.read.locked())

    async def test_downgrade_functionality(self):
        if not self.lock_class: return
        await self.lock.write.acquire()
        await self.lock.write.downgrade()
        
        self.assertTrue(await self.lock.read.acquire(blocking=False))
        await self.lock.read.release()
   
        self.assertFalse(await self.lock.write.acquire(blocking=False))

        await self.lock.read.release()
        self.assertFalse(await self.lock.read.locked())

    async def test_timeout_functionality(self):
        if not self.lock_class: return
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
        await self.lock.write.release()

    async def test_unacquired_release_raises(self):
        if not self.lock_class: return
        with self.assertRaises(RuntimeError, msg="Releasing an unacquired write lock should raise RuntimeError."):
            await self.lock.write.release()
        
        with self.assertRaises(RuntimeError, msg="Releasing an unacquired read lock should raise RuntimeError."):
            await self.lock.read.release()


class ReentrantWriterAsyncTestsMixin:
    async def test_reentrant_write(self):
        if not self.lock_class: return
        async with self.lock.write:
            success = await self.lock.write.acquire(blocking=False)
            self.assertTrue(success, "ReentrantWriter must allow nested writing from the same task.")
            self.assertTrue(await self.lock.write.locked())
            await self.lock.write.release()
        self.assertFalse(await self.lock.write.locked(), "Lock should be fully released after all nested context exits.")

    async def test_reentrant_downgrade_exception(self):
        if not self.lock_class: return
        await self.lock.write.acquire()
        await self.lock.write.acquire()
        
        with self.assertRaisesRegex(RuntimeError, "Cannot downgrade a nested write lock"):
            await self.lock.write.downgrade()
            
        await self.lock.write.release()
        await self.lock.write.release()

    async def test_cross_task_release_protection(self):
        if not self.lock_class: return
        await self.lock.write.acquire()
        
        exception_caught = False
        async def malicious_task():
            nonlocal exception_caught
            try:
                await self.lock.write.release()
            except RuntimeError as e:
                if "Permission denied" in str(e):
                    exception_caught = True

        t = asyncio.create_task(malicious_task())
        await t
        
        self.assertTrue(exception_caught, "The release process from a different task must be blocked.")
        await self.lock.write.release()

    async def test_writer_exclusivity(self):
        if not self.lock_class: return
        self.assertTrue(await self.lock.write.acquire())
        self.assertTrue(await self.lock.read.acquire(blocking=False))
        await self.lock.read.release()

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
        
        await self.lock.write.release()
    
    async def test_timeout_functionality(self):
        if not self.lock_class: return
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
        
        await self.lock.write.release()


class TestAsyncRWLockWrite(BaseAsyncRWLockTests):
    lock_class = AsyncRWLockWrite

class TestAsyncRWLockWriteReentrantWriter(ReentrantWriterAsyncTestsMixin, BaseAsyncRWLockTests):
    lock_class = AsyncRWLockWriteReentrantWriter

class TestAsyncRWLockRead(BaseAsyncRWLockTests):
    lock_class = AsyncRWLockRead

class TestAsyncRWLockReadReentrantWriter(ReentrantWriterAsyncTestsMixin, BaseAsyncRWLockTests):
    lock_class = AsyncRWLockReadReentrantWriter

class TestAsyncRWLockFIFO(BaseAsyncRWLockTests):
    lock_class = AsyncRWLockFIFO

class TestAsyncRWLockFIFOReentrantWriter(ReentrantWriterAsyncTestsMixin, BaseAsyncRWLockTests):
    lock_class = AsyncRWLockFIFOReentrantWriter


if __name__ == '__main__':
    unittest.main()