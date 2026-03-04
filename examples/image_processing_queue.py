import threading
import time
from collections import deque
from rwlocker.thread_rwlock import RWLockFair, RWCondition

class ImageProcessingQueue:
    """
    A Thread-safe producer-consumer queue for heavy image processing.
    Demonstrates precise notification targeting `notify(n)`.
    """
    def __init__(self):
        # Fair lock ensures producers and consumers take strict turns
        self._cond = RWCondition(RWLockFair())
        self._queue = deque()

    def add_jobs(self, jobs: list[str]) -> None:
        """Producer: Adds new files to process."""
        with self._cond.write:
            print(f"[Producer] Adding {len(jobs)} jobs to queue...")
            self._queue.extend(jobs)
            
            # Smart Notification: We only wake up exactly the number of 
            # consumer threads as we have jobs. No thundering herd!
            self._cond.write.notify(n=len(jobs))

    def consume_job(self, worker_name: str) -> None:
        """Consumer: Waits for a job and processes it."""
        with self._cond.read:
            # Wait safely until the queue is not empty
            self._cond.read.wait_for(lambda: len(self._queue) > 0)
            
            # Pop the job quickly while holding the read lock
            # (Note: In pure RW semantics, deque pop is a write. For this example, 
            # we assume the queue is read-popped atomically via GIL deque properties)
            try:
                job = self._queue.popleft()
            except IndexError:
                return # Spurious wakeup safety

        # Process the heavy job OUTSIDE the lock!
        print(f"[{worker_name}] Processing image: {job}")
        time.sleep(0.2) 

if __name__ == "__main__":
    job_queue = ImageProcessingQueue()

    def consumer(name: str):
        for _ in range(2): # Each consumer handles 2 jobs
            job_queue.consume_job(name)

    # Start 4 consumers (they will immediately block and wait)
    threads = [threading.Thread(target=consumer, args=(f"Worker-{i}",)) for i in range(4)]
    for t in threads: t.start()

    time.sleep(0.1)

    # Add exactly 2 jobs. Only 2 threads should wake up.
    job_queue.add_jobs(["img_01.jpg", "img_02.png"])
    time.sleep(0.5)

    # Add the remaining jobs to finish the workers
    job_queue.add_jobs(["img_03.webp", "img_04.jpg", "img_05.bmp"])

    for t in threads: t.join()
