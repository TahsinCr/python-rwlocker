import asyncio
from tests import (
    thread_rwlock_benchmark, 
    async_rwlock_benchmark,
    thread_rwcondition_benchmark, 
    async_rwcondition_benchmark
)

if __name__ == '__main__':
    thread_rwlock_benchmark.main()
    asyncio.run(async_rwlock_benchmark.main())
    print("\n\n","="*0,"\n\n")
    thread_rwcondition_benchmark.main()
    asyncio.run(async_rwcondition_benchmark.main())
