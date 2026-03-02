import threading
import time
from rwlocker.thread_rwlock import RWLockWrite, RWCondition

class ServiceBootBarrier:
    """
    Coordinates multi-service initialization.
    Demonstrates how to safely use timeouts with Condition.wait()
    """
    def __init__(self):
        self._cond = RWCondition(RWLockWrite())
        self._is_database_ready = False

    def mark_database_ready(self) -> None:
        """Called by the DB connection thread once ping is successful."""
        with self._cond.write:
            self._is_database_ready = True
            print("[System] Database is ready. Signalling waiting services.")
            self._cond.write.notify_all()

    def start_api_server(self) -> None:
        """API server must wait for DB, but shouldn't wait forever."""
        print("[API] Attempting to boot. Waiting for DB...")
        with self._cond.read:
            # Wait for DB to be ready, but give up if it takes longer than 2 seconds.
            success = self._cond.read.wait_for(
                predicate=lambda: self._is_database_ready, 
                timeout=2.0
            )

        if success:
            print("[API] DB is connected. Booting HTTP server on port 8080...")
        else:
            print("[API] CRITICAL ERROR: Database connection timeout. Halting boot sequence.")

if __name__ == "__main__":
    barrier = ServiceBootBarrier()

    api_thread = threading.Thread(target=barrier.start_api_server)
    api_thread.start()

    # Change to 3.0 to test the Timeout failure mechanism
    time.sleep(1.0) 
    
    db_thread = threading.Thread(target=barrier.mark_database_ready)
    db_thread.start()

    api_thread.join()
    db_thread.join()
