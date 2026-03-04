import unittest
import asyncio
from typing import Type

from rwlocker.async_rwlock import (
    AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
    AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
    AsyncRWLockFair, AsyncRWLockFairReentrantWriter,
    AsyncRWLockBase, AsyncRWCondition, AsyncCondition
)

class BaseAsyncConditionTests:
    lock_class: Type[AsyncRWLockBase] = None

    async def asyncSetUp(self):
        if self.lock_class:
            self.lock = self.lock_class()
            self.condition = AsyncCondition(self.lock)

    async def test_initial_state(self):
        self.assertFalse(self.condition.read.locked())
        self.assertFalse(self.condition.write.locked())

    async def test_wait_without_acquire_raises(self):
        with self.assertRaises(RuntimeError, msg="Waiting on an un-acquired read condition should raise RuntimeError."):
            await self.condition.read.wait()
            
        with self.assertRaises(RuntimeError, msg="Waiting on an un-acquired write condition should raise RuntimeError."):
            await self.condition.write.wait()

    async def test_notify_without_acquire_raises(self):
        with self.assertRaises(RuntimeError, msg="Notifying on an un-acquired read condition should raise RuntimeError."):
            self.condition.read.notify()
            
        with self.assertRaises(RuntimeError, msg="Notifying on an un-acquired write condition should raise RuntimeError."):
            self.condition.write.notify_all()

    async def test_wait_and_notify_single(self):
        event_happened = False
        wait_success = False

        async def waiter_task():
            nonlocal wait_success
            async with self.condition.read:
                # wait_for handles the predicate loop internally
                await self.condition.read.wait_for(lambda: event_happened)
                wait_success = True

        t = asyncio.create_task(waiter_task())
        # Yield to allow the waiter task to acquire the lock and enter wait()
        await asyncio.sleep(0.05)

        async with self.condition.write:
            event_happened = True
            self.condition.write.notify()

        await t
        self.assertTrue(wait_success, "The waiter task should successfully wake up and evaluate the predicate.")

    async def test_notify_all_wakes_multiple_waiters(self):
        wait_count = 0
        event_happened = False

        async def waiter_task():
            nonlocal wait_count
            async with self.condition.read:
                await self.condition.read.wait_for(lambda: event_happened)
                wait_count += 1

        tasks = [asyncio.create_task(waiter_task()) for _ in range(5)]
        await asyncio.sleep(0.05)

        async with self.condition.write:
            event_happened = True
            self.condition.write.notify_all()

        await asyncio.gather(*tasks)
        self.assertEqual(wait_count, 5, "All waiting tasks should have been awoken by notify_all().")

    async def test_notify_n_wakes_specific_number_of_waiters(self):
        wait_count = 0

        async def waiter_task():
            nonlocal wait_count
            async with self.condition.read:
                await self.condition.read.wait()
                wait_count += 1

        tasks = [asyncio.create_task(waiter_task()) for _ in range(4)]
        await asyncio.sleep(0.05)

        async with self.condition.write:
            # Wake exactly 2 tasks out of 4
            self.condition.write.notify(n=2)

        # Small delay to let notified tasks complete
        await asyncio.sleep(0.05)
        
        # At this stage, 2 should be done, 2 should be waiting
        self.assertEqual(wait_count, 2, "Exactly n tasks should have been awoken.")

        # Cleanup: wake the remaining tasks
        async with self.condition.write:
            self.condition.write.notify_all()
            
        await asyncio.gather(*tasks)
        self.assertEqual(wait_count, 4)

    async def test_wait_cancellation_safety(self):
        """
        Verify that cancelling a waiting task does not corrupt the lock state
        and that the task re-acquires the lock before propagating the error.
        """
        async with self.condition.read:
            wait_task = asyncio.create_task(self.condition.read.wait())
            await asyncio.sleep(0.05)
            
            wait_task.cancel()
            
            try:
                await wait_task
            except asyncio.CancelledError:
                pass
        
        # The lock should be released and available for others
        self.assertFalse(self.condition.read.locked())
        async with self.condition.write:
            self.assertTrue(self.condition.write.locked())

    async def test_wait_for_timeout(self):
        async with self.condition.read:
            start_time = asyncio.get_running_loop().time()
            success = True
            try:
                # Using external asyncio.wait_for as per docstring recommendation
                await asyncio.wait_for(self.condition.read.wait_for(lambda: False), timeout=0.1)
            except asyncio.TimeoutError:
                success = False
            
            elapsed = asyncio.get_running_loop().time() - start_time
            self.assertFalse(success, "wait_for should timeout when the predicate remains False.")
            self.assertGreaterEqual(elapsed, 0.09)

class AsyncRWConditionTests(BaseAsyncConditionTests):
    async def asyncSetUp(self):
        if self.lock_class:
            self.lock = self.lock_class()
            self.condition = AsyncRWCondition(self.lock)

    async def test_downgrade_condition_release_safety(self):
        """
        Verify that if the underlying Write proxy is downgraded, the Condition 
        Proxy routes the release logic correctly via the smart proxy.
        """
        async with self.condition.write:
            self.condition.write._lock_proxy.downgrade()
            # Smart Proxy should handle the __aexit__ release correctly
        
        self.assertFalse(self.condition.read.locked())
        self.assertFalse(self.condition.write.locked())


class TestAsyncRWConditionWithWriteLock(AsyncRWConditionTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockWrite

class TestAsyncRWConditionWithWriteReentrantLock(AsyncRWConditionTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockWriteReentrantWriter

class TestAsyncRWConditionWithReadLock(AsyncRWConditionTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockRead

class TestAsyncRWConditionWithReadReentrantLock(AsyncRWConditionTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockReadReentrantWriter

class TestAsyncRWConditionWithFairLock(AsyncRWConditionTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockFair

class TestAsyncRWConditionWithFairReentrantLock(AsyncRWConditionTests, unittest.IsolatedAsyncioTestCase):
    lock_class = AsyncRWLockFairReentrantWriter

class TestAsyncCondition(BaseAsyncConditionTests, unittest.IsolatedAsyncioTestCase):
    lock_class = asyncio.Lock

if __name__ == '__main__':
    unittest.main()
