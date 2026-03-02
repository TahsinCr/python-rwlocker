import asyncio
from rwlocker.async_rwlock import AsyncRWLockRead, AsyncRWCondition

class GlobalConfigCache:
    """
    A globally shared configuration cache. 
    Demonstrates Cache Stampede protection using AsyncRWCondition.
    """
    def __init__(self):
        # We use Read-preferring lock as reads are extremely frequent.
        self._cond = AsyncRWCondition(AsyncRWLockRead())
        self._config = {}
        self._config_version = 0
        self._is_refreshing = False

    async def get_config(self) -> dict:
        """Called by thousands of concurrent requests."""
        async with self._cond.read:
            # If the config is currently being hard-refreshed, we don't want 
            # 10,000 requests hitting the DB. We make them wait.
            # Using wait_for handles spurious wakeups automatically.
            await self._cond.read.wait_for(lambda: not self._is_refreshing)
            return self._config

    async def force_refresh_from_db(self) -> None:
        """Triggered via a webhook when admin changes settings."""
        async with self._cond.write:
            print("\n[DB] Admin updated config. Locking out new readers...")
            self._is_refreshing = True
            
            # Simulate slow DB call
            await asyncio.sleep(0.5) 
            self._config = {"theme": "dark", "version": self._config_version + 1}
            self._config_version += 1
            self._is_refreshing = False
            
            print(f"[DB] Config refreshed to v{self._config_version}. Broadcasting to ALL waiting readers...")
            # O(1) wakeup for potentially thousands of waiting tasks
            self._cond.write.notify_all()

async def main():
    cache = GlobalConfigCache()

    async def worker(worker_id: int):
        print(f"Worker {worker_id} requesting config...")
        cfg = await cache.get_config()
        print(f"Worker {worker_id} got config: {cfg['theme']}")

    # Start 3 workers, they get empty config immediately
    await asyncio.gather(*(worker(i) for i in range(1, 4)))

    # Start an update process
    refresh_task = asyncio.create_task(cache.force_refresh_from_db())
    await asyncio.sleep(0.1) # Let the write lock acquire

    # While updating, 5 new workers arrive. They will gracefully WAIT 
    # instead of crashing or hitting the DB.
    await asyncio.gather(*(worker(i) for i in range(4, 9)))
    await refresh_task

if __name__ == "__main__":
    asyncio.run(main())
