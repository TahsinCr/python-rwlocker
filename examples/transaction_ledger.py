import threading
import time
import uuid
from rwlocker.thread_rwlock import RWLockWriteReentrantWriter

class TransactionLedger:
    """A financial ledger demonstrating atomic lock downgrading."""
    
    def __init__(self, initial_balance: float):
        self._lock = RWLockWriteReentrantWriter()
        self._balance = initial_balance
        self._audit_log = []

    def process_payment(self, amount: float) -> None:
        tx_id = str(uuid.uuid4())
        
        self._lock.write.acquire()
        try:
            # Phase 1: Exclusive Write (Mutate state)
            if self._balance + amount < 0:
                raise ValueError("Insufficient funds")
            
            self._balance += amount
            self._audit_log.append(tx_id)
            
            # ATOMIC DOWNGRADE: Convert Write Lock -> Read Lock.
            # Allows other waiting readers to enter immediately,
            # but strictly blocks other writers until auditing is done.
            self._lock.write.downgrade()
            
            # Phase 2: Shared Read (Safe auditing / Network I/O)
            self._dispatch_audit_event(tx_id, self._balance)
            
        finally:
            # Important: Since we downgraded, we must release the READ lock.
            # The smart proxy handles this safely.
            self._lock.read.release()

    def _dispatch_audit_event(self, tx_id: str, balance: float) -> None:
        """Simulates a slow network call to an external auditing service."""
        time.sleep(0.05) 
        print(f"Audit dispatched: {tx_id} -> New Balance: {balance}")

if __name__ == "__main__":
    ledger = TransactionLedger(1000.0)

    # Launch 2 concurrent writers. 
    # Downgrade ensures Writer 2 waits until Writer 1 fully finishes auditing.
    t1 = threading.Thread(target=ledger.process_payment, args=(500.0,))
    t2 = threading.Thread(target=ledger.process_payment, args=(-200.0,))
    
    t1.start(); t2.start()
    t1.join(); t2.join()
