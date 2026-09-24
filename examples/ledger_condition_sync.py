import asyncio
from rwlocker.async_rwlock import AsyncRWLockWriteReentrantWriter, AsyncRWCondition

class LedgerConditionSync:
    """
    A high-concurrency ledger syncing mechanism using Atomic Downgrades 
    paired with Condition Notifications.
    """
    def __init__(self):
        self._cond = AsyncRWCondition(AsyncRWLockWriteReentrantWriter())
        self._current_tx_id = 0
        self._sync_completed = True

    async def commit_and_sync(self, amount: float) -> None:
        """Writer: Mutates the ledger, downgrades, and triggers a sync."""
        async with self._cond.write:
            self._current_tx_id += 1
            self._sync_completed = False
            print(f"[Writer] Committed TX-{self._current_tx_id} for ${amount}.")
            
            # Atomic Downgrade: Lock becomes a Read lock.
            # We notify readers that a sync is STARTING.
            self._cond.write.downgrade()
            
            # Now we perform the slow sync (Network Call) while holding a READ lock.
            # This allows other tasks to read the state safely but blocks new Writers.
            print(f"[Sync] Uploading TX-{self._current_tx_id} to cloud...")
            await asyncio.sleep(0.5) 
        # The write context releases its downgraded read side. Reacquire write
        # access to publish completion and notify condition waiters.
        async with self._cond.write:
            self._sync_completed = True
            self._cond.write.notify_all()

    async def wait_for_sync(self, reader_id: int) -> None:
        """Reader: Waits until the ledger is fully synced to the cloud."""
        async with self._cond.read:
            if not self._sync_completed:
                print(f"[Reader-{reader_id}] Sync in progress. Waiting...")
                await self._cond.read.wait_for(lambda: self._sync_completed)
            
            print(f"[Reader-{reader_id}] Read confirmed for TX-{self._current_tx_id}.")

async def main():
    ledger = LedgerConditionSync()

    # Launch a write that triggers a slow cloud sync
    write_task = asyncio.create_task(ledger.commit_and_sync(250.0))
    
    # Wait slightly so the Writer acquires the lock and starts the sync
    await asyncio.sleep(0.1)

    # These readers will hit the lock during the "Downgrade" phase.
    # They will acquire the Read lock alongside the Writer, see that 
    # _sync_completed is False, and go to sleep via Condition.wait()
    reader_tasks = [asyncio.create_task(ledger.wait_for_sync(i)) for i in range(1, 4)]
    
    await write_task
    
    await asyncio.gather(*reader_tasks)

if __name__ == "__main__":
    asyncio.run(main())
