import asyncio
from tests import thread_rwlock_benchmark, async_rwlock_benchmark

if __name__ == '__main__':
    thread_rwlock_benchmark.main()
    asyncio.run(async_rwlock_benchmark.main())
