import asyncio
from rwlocker.async_rwlock import AsyncRWLockWrite

class AuthTokenManager:
    """Manages remote authentication tokens securely across hundreds of tasks."""
    
    def __init__(self):
        self._lock = AsyncRWLockWrite()
        self._token = "initial_token_123"
        self._is_expired = False

    async def get_valid_token(self) -> str:
        # Fast Path: 499 tasks will pass through here concurrently
        async with self._lock.read:
            if not self._is_expired:
                return self._token
                
        # Slow Path: Token expired. Acquire exclusive Write Lock.
        async with self._lock.write:
            # Double-checked locking: Another task might have already 
            # refreshed the token while we were waiting for the write lock.
            if self._is_expired:
                print("Token expired. Fetching new token from remote API...")
                await asyncio.sleep(0.5)  # Simulate HTTP request
                self._token = "new_remote_token_456"
                self._is_expired = False
                
            return self._token

    async def invalidate_token(self) -> None:
        """Can be triggered by a 401 Unauthorized interceptor."""
        async with self._lock.write:
            self._is_expired = True

async def main():
    manager = AuthTokenManager()
    await manager.invalidate_token() # Force expiration

    async def worker(task_id: int):
        print(f"Task {task_id} requesting token...")
        token = await manager.get_valid_token()
        print(f"Task {task_id} acquired token: {token}")

    # Launch 5 tasks simultaneously. Only ONE will make the API call!
    await asyncio.gather(*(worker(i) for i in range(1, 6)))

if __name__ == "__main__":
    asyncio.run(main())
