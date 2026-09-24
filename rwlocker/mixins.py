"""
Internal mixins shared by the monolithic RWLock modules.

This module only contains non-public state-machine helpers. Concrete thread and
async classes keep their user-facing methods, constructor signatures, and
runtime-specific behavior in their own modules.
"""
from typing import Optional

class _RWLockWriteMixin:
    """Internal core logic for write-preferring RWLock variants."""

    __slots__ = ()

    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        return not self._writer_active and self.write.those_waiting == 0

    def _acquire_read_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None:
        del waiting, waiter_seq
        self._readers_active += 1
        self._record_reader_acquire()

    def _release_read_core(self) -> None:
        self._record_reader_release()
        self._readers_active -= 1
        if self._readers_active == 0 and self.write.condition.has_waiters():
            self.write.condition.notify()

    def _on_reader_abort(self, waiter_seq: Optional[int] = None) -> None:
        del waiter_seq

    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        return not self._writer_active and self._readers_active == 0

    def _acquire_write_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None:
        del waiting, waiter_seq
        self._writer_active = True
        self._writer_owner = self._current_reader_owner()

    def _release_write_core(self) -> None:
        if not self._writer_active:
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._writer_owner = None
        self._on_writer_abort()

    def _downgrade_core(self) -> None:
        if not self._writer_active:
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._writer_owner = None
        self._readers_active += 1
        self._record_reader_acquire()
        if self.read.condition.has_waiters():
            self.read.condition.notify_all()

    def _on_writer_abort(self, waiter_seq: Optional[int] = None) -> None:
        del waiter_seq
        if self.write.those_waiting > 0 and self.write.condition.has_waiters():
            self.write.condition.notify()
        elif self.read.condition.has_waiters():
            self.read.condition.notify_all()

    def _is_write_locked(self) -> bool:
        return self._writer_active

    def _is_read_locked(self) -> bool:
        return self._readers_active > 0

class _RWLockReadMixin:
    """Internal core logic for read-preferring RWLock variants."""

    __slots__ = ()

    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        return not self._writer_active

    def _acquire_read_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None:
        del waiting, waiter_seq
        self._readers_active += 1
        self._record_reader_acquire()

    def _release_read_core(self) -> None:
        self._record_reader_release()
        self._readers_active -= 1
        if self._readers_active == 0 and self.write.condition.has_waiters():
            self.write.condition.notify()

    def _on_reader_abort(self, waiter_seq: Optional[int] = None) -> None:
        del waiter_seq
        if self.read.those_waiting == 0 and self._readers_active == 0 and self.write.condition.has_waiters():
            self.write.condition.notify()

    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        return (
            not self._writer_active
            and self._readers_active == 0
            and self.read.those_waiting == 0
        )

    def _acquire_write_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None:
        del waiting, waiter_seq
        self._writer_active = True
        self._writer_owner = self._current_reader_owner()

    def _release_write_core(self) -> None:
        if not self._writer_active:
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._writer_owner = None
        self._on_writer_abort()

    def _downgrade_core(self) -> None:
        if not self._writer_active:
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._writer_owner = None
        self._readers_active += 1
        self._record_reader_acquire()
        if self.read.condition.has_waiters():
            self.read.condition.notify_all()

    def _on_writer_abort(self, waiter_seq: Optional[int] = None) -> None:
        del waiter_seq
        if self.read.those_waiting > 0 and self.read.condition.has_waiters():
            self.read.condition.notify_all()
        elif self.write.condition.has_waiters():
            self.write.condition.notify()

    def _is_write_locked(self) -> bool:
        return self._writer_active

    def _is_read_locked(self) -> bool:
        return self._readers_active > 0

class _RWLockReaderPhaseFairMixin:
    """Internal core logic for reader-phase fair RWLock variants."""

    __slots__ = ()

    def _wake_waiting_reader(self) -> None:
        if (
            not self._writer_active
            and self.read.those_waiting > 0
            and self.read.condition.has_waiters()
        ):
            self.read.condition.notify_all()

    def _start_reader_phase(self) -> None:
        self._readers_turn = True
        self._wake_waiting_reader()

    def _finish_or_continue_reader_phase(self) -> None:
        if self._readers_turn and self.read.those_waiting > 0:
            self._wake_waiting_reader()
            return
        self._readers_turn = False
        if self.write.those_waiting > 0 and self.write.condition.has_waiters():
            self.write.condition.notify()

    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_active:
            return False
        return self._readers_turn or self.write.those_waiting == 0

    def _acquire_read_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None:
        del waiting, waiter_seq
        self._readers_active += 1
        self._record_reader_acquire()
        if self._readers_turn and self.read.those_waiting > 0:
            self._wake_waiting_reader()

    def _release_read_core(self) -> None:
        self._record_reader_release()
        self._readers_active -= 1
        if self._readers_active == 0:
            self._finish_or_continue_reader_phase()

    def _on_reader_abort(self, waiter_seq: Optional[int] = None) -> None:
        del waiter_seq
        if self._readers_turn and self._readers_active == 0:
            self._finish_or_continue_reader_phase()

    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_active or self._readers_active > 0:
            return False
        if self._readers_turn and self.read.those_waiting > 0:
            return False
        return True

    def _acquire_write_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None:
        del waiting, waiter_seq
        self._writer_active = True
        self._writer_owner = self._current_reader_owner()

    def _release_write_core(self) -> None:
        if not self._writer_active:
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._writer_owner = None
        self._on_writer_abort()

    def _downgrade_core(self) -> None:
        if not self._writer_active:
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._writer_owner = None
        self._readers_active += 1
        self._record_reader_acquire()
        self._start_reader_phase()

    def _on_writer_abort(self, waiter_seq: Optional[int] = None) -> None:
        del waiter_seq
        if self.read.those_waiting > 0 and self.read.condition.has_waiters():
            self._start_reader_phase()
        elif self.write.condition.has_waiters():
            self.write.condition.notify()

    def _is_write_locked(self) -> bool:
        return self._writer_active

    def _is_read_locked(self) -> bool:
        return self._readers_active > 0

class _RWLockFairMixin:
    """Internal core logic for strict fair RWLock variants."""

    __slots__ = ()

    def _wake_waiting_reader(self) -> None:
        if (
            self._writer_active
            or self._reader_phase_pending <= 0
            or self.read.those_waiting <= 0
            or not self.read.condition.has_waiters()
        ):
            return
        notify_count = min(self.read.those_waiting, self._reader_phase_pending)
        self.read.condition.notify(notify_count)

    def _start_reader_phase(self) -> None:
        pending = self.read.those_waiting
        self._readers_turn = pending > 0
        self._reader_phase_pending = pending
        self._reader_phase_cutoff = self.read._waiter_seq
        if self._readers_turn:
            self._wake_waiting_reader()

    def _finish_or_continue_reader_phase(self) -> None:
        if self._readers_turn and self._reader_phase_pending > 0:
            self._wake_waiting_reader()
            return
        self._readers_turn = False
        self._reader_phase_cutoff = 0
        self._reader_phase_pending = 0
        if self.write.those_waiting > 0 and self.write.condition.has_waiters():
            self.write.condition.notify()

    def _is_reserved_reader(self, waiting: bool, waiter_seq: Optional[int]) -> bool:
        if not self._readers_turn or not waiting or waiter_seq is None:
            return False
        return waiter_seq <= self._reader_phase_cutoff and self._reader_phase_pending > 0

    def _consume_reader_phase_slot(self, waiting: bool, waiter_seq: Optional[int]) -> None:
        if self._is_reserved_reader(waiting, waiter_seq):
            self._reader_phase_pending -= 1

    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        if self._writer_active:
            return False
        if self._readers_turn:
            if self.write.those_waiting == 0:
                return True
            return self._is_reserved_reader(waiting, waiter_seq)
        return self.write.those_waiting == 0

    def _acquire_read_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None:
        self._consume_reader_phase_slot(waiting, waiter_seq)
        self._readers_active += 1
        self._record_reader_acquire()
        if self._readers_turn and self._reader_phase_pending > 0:
            self._wake_waiting_reader()

    def _on_reader_abort(self, waiter_seq: Optional[int] = None) -> None:
        if self._readers_turn and waiter_seq is not None and waiter_seq <= self._reader_phase_cutoff:
            if self._reader_phase_pending > 0:
                self._reader_phase_pending -= 1
        if self._readers_turn and self._reader_phase_pending > 0:
            self._wake_waiting_reader()
            return
        if self._readers_turn and self._readers_active == 0:
            self._finish_or_continue_reader_phase()

    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_active or self._readers_active > 0:
            return False
        if self._readers_turn and self._reader_phase_pending > 0:
            return False
        return True


class _RWLockReentrantWriterCoreMixin:
    """Common write-side core logic for reentrant writer variants."""

    __slots__ = ()

    def _acquire_write_core(self, waiting: bool = False, waiter_seq: Optional[int] = None):
        del waiting, waiter_seq
        self._set_current_writer()
        self._write_count += 1

    def _release_write_core(self):
        if not self._is_current_writer():
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._clear_current_writer()
            self._on_writer_abort()

    def _is_write_locked(self) -> bool:
        return self._writer_id is not None

    def _downgrade_to_read_notify_all(self) -> None:
        if not self._is_current_writer():
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._clear_current_writer()
        self._write_count = 0
        self._readers_active += 1
        self._record_reader_acquire()
        if self.read.condition.has_waiters():
            self.read.condition.notify_all()

    def _downgrade_to_reader_phase(self) -> None:
        if not self._is_current_writer():
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._clear_current_writer()
        self._write_count = 0
        self._readers_active += 1
        self._record_reader_acquire()
        self._start_reader_phase()

class _RWLockWriteReentrantWriterMixin(_RWLockReentrantWriterCoreMixin):
    """Internal write-preferring reentrant-writer logic."""

    __slots__ = ()

    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_id is not None:
            return self._is_current_writer()
        return self.write.those_waiting == 0

    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_id is not None:
            return self._is_current_writer()
        return self._readers_active == 0

    def _downgrade_core(self):
        self._downgrade_to_read_notify_all()

class _RWLockReadReentrantWriterMixin(_RWLockReentrantWriterCoreMixin):
    """Internal read-preferring reentrant-writer logic."""

    __slots__ = ()

    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_id is not None:
            return self._is_current_writer()
        return True

    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_id is not None:
            return self._is_current_writer()
        return self._readers_active == 0 and self.read.those_waiting == 0

    def _downgrade_core(self):
        self._downgrade_to_read_notify_all()

class _RWLockReaderPhaseFairReentrantWriterMixin(_RWLockReentrantWriterCoreMixin):
    """Internal reader-phase-fair reentrant-writer logic."""

    __slots__ = ()

    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_id is not None:
            return self._is_current_writer()
        return self._readers_turn or self.write.those_waiting == 0

    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_id is not None:
            return self._is_current_writer()
        if self._readers_active > 0:
            return False
        if self._readers_turn and self.read.those_waiting > 0:
            return False
        return True

    def _downgrade_core(self):
        self._downgrade_to_reader_phase()

class _RWLockFairReentrantWriterMixin(_RWLockReentrantWriterCoreMixin):
    """Internal strict-fair reentrant-writer logic."""

    __slots__ = ()

    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        if self._readers_turn:
            if self.write.those_waiting == 0:
                return True
            return self._is_reserved_reader(waiting, waiter_seq)
        return self.write.those_waiting == 0

    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool:
        del waiting, waiter_seq
        if self._writer_id is not None:
            return self._is_current_writer()
        if self._readers_active > 0:
            return False
        if self._readers_turn and self._reader_phase_pending > 0:
            return False
        return True

    def _downgrade_core(self):
        self._downgrade_to_reader_phase()


class _RWConditionMixin:
    """Internal queue-backed helpers shared by RWCondition variants."""

    __slots__ = ()

    def _is_owned_read(self) -> bool:
        is_owned = getattr(self._lock, "_is_current_reader", None)
        return is_owned() if is_owned is not None else self._lock._is_read_locked()

    def _is_owned_write(self) -> bool:
        is_owned = getattr(self._lock, "_is_current_writer", None)
        return is_owned() if is_owned is not None else self._lock._is_write_locked()

    def _add_waiter(self):
        return self._queue.add_waiter()

    def _remove_waiter(self, waiter) -> None:
        self._queue.remove_waiter(waiter)

    def _notify_core(self, n: int) -> None:
        self._queue.notify(n)

    def _notify_all_core(self) -> None:
        self._queue.notify_all()
