"""
Shared state-machine Mixins for both Thread and Async RWLock implementations.
These mixins encapsulate the core scheduling algorithms (Write-Pref, Read-Pref, Fair)
to eliminate code duplication across synchronous and asynchronous domains.
"""

class _RWLockWriteMixin:
    __slots__ = ()

    def _can_read(self) -> bool: 
        return not self._writer_active and self.write.those_waiting == 0
    
    def _acquire_read_core(self): 
        self._readers_active += 1

    def _release_read_core(self):
        if self._readers_active == 0: 
            raise RuntimeError("Unacquired read lock")
        self._readers_active -= 1
        if self._readers_active == 0: 
            self.write.condition.notify()

    def _on_reader_abort(self):
        pass

    def _can_write(self) -> bool: 
        return not self._writer_active and self._readers_active == 0
    
    def _acquire_write_core(self): 
        self._writer_active = True

    def _release_write_core(self):
        if not self._writer_active: 
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._on_writer_abort()

    def _downgrade_core(self):
        if not self._writer_active: 
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._readers_active += 1
        self.read.condition.notify_all()

    def _on_writer_abort(self):
        if self.write.those_waiting > 0: 
            self.write.condition.notify()
        else: 
            self.read.condition.notify_all()

    def _is_write_locked(self) -> bool: 
        return self._writer_active
    
    def _is_read_locked(self) -> bool:
        return self._readers_active > 0


class _RWLockWriteReentrantMixin:
    __slots__ = ()

    def _can_read(self) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        return self.write.those_waiting == 0

    def _can_write(self) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        return self._readers_active == 0
    
    def _acquire_write_core(self):
        self._set_current_writer()
        self._write_count += 1

    def _release_write_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._clear_current_writer()
            self._on_writer_abort()

    def _downgrade_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._clear_current_writer()
        self._write_count = 0
        self._readers_active += 1
        self.read.condition.notify_all()
        
    def _is_write_locked(self) -> bool: 
        return self._writer_id is not None


class _RWLockReadMixin:
    __slots__ = ()

    def _can_read(self) -> bool: 
        return not self._writer_active
    
    def _acquire_read_core(self): 
        self._readers_active += 1

    def _release_read_core(self):
        if self._readers_active == 0: 
            raise RuntimeError("Unacquired read lock")
        self._readers_active -= 1
        if self._readers_active == 0: 
            self.write.condition.notify()

    def _on_reader_abort(self):
        if self.read.those_waiting == 0 and self._readers_active == 0: 
            self.write.condition.notify()

    def _can_write(self) -> bool: 
        return not self._writer_active and self._readers_active == 0 and self.read.those_waiting == 0
    
    def _acquire_write_core(self): 
        self._writer_active = True

    def _release_write_core(self):
        if not self._writer_active: 
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._on_writer_abort()

    def _downgrade_core(self):
        if not self._writer_active: 
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._readers_active += 1
        self.read.condition.notify_all()

    def _on_writer_abort(self):
        if self.read.those_waiting > 0: 
            self.read.condition.notify_all()
        else: 
            self.write.condition.notify()

    def _is_write_locked(self) -> bool: 
        return self._writer_active
    
    def _is_read_locked(self) -> bool:
        return self._readers_active > 0


class _RWLockReadReentrantMixin:
    __slots__ = ()

    def _can_read(self) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        return True

    def _can_write(self) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        return self._readers_active == 0 and self.read.those_waiting == 0
    
    def _acquire_write_core(self):
        self._set_current_writer()
        self._write_count += 1

    def _release_write_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._clear_current_writer()
            self._on_writer_abort()

    def _downgrade_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._clear_current_writer()
        self._write_count = 0
        self._readers_active += 1
        self.read.condition.notify_all()
        
    def _is_write_locked(self) -> bool:
        return self._writer_id is not None


class _RWLockFairMixin:
    __slots__ = ()

    def _can_read(self) -> bool:
        if self._writer_active: 
            return False
        return self._readers_turn or self.write.those_waiting == 0
    
    def _acquire_read_core(self): 
        self._readers_active += 1

    def _release_read_core(self):
        if self._readers_active == 0: 
            raise RuntimeError("Unacquired read lock")
        self._readers_active -= 1
        if self._readers_active == 0:
            self._readers_turn = False
            self.write.condition.notify()

    def _on_reader_abort(self):
        if self._readers_turn and self.read.those_waiting == 0 and self._readers_active == 0:
            self._readers_turn = False
            self.write.condition.notify()

    def _can_write(self) -> bool:
        if self._writer_active or self._readers_active > 0: 
            return False
        if self._readers_turn and self.read.those_waiting > 0: 
            return False
        return True
    
    def _acquire_write_core(self):
        self._writer_active = True

    def _release_write_core(self):
        if not self._writer_active: 
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._on_writer_abort()

    def _downgrade_core(self):
        if not self._writer_active: 
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._readers_active += 1
        self._readers_turn = True
        self.read.condition.notify_all()

    def _on_writer_abort(self):
        if self.read.those_waiting > 0:
            self._readers_turn = True
            self.read.condition.notify_all()
        else: 
            self.write.condition.notify()

    def _is_write_locked(self) -> bool:
        return self._writer_active
    
    def _is_read_locked(self) -> bool:
        return self._readers_active > 0


class _RWLockFairReentrantMixin:
    __slots__ = ()

    def _can_read(self) -> bool:
        if self._writer_id is not None:
            if self._is_current_writer():
                return True
            return False
        return self._readers_turn or self.write.those_waiting == 0

    def _can_write(self) -> bool:
        if self._writer_id is not None:
            if self._is_current_writer():
                return True
            return False
        if self._readers_active > 0:
            return False
        if self._readers_turn and self.read.those_waiting > 0: 
            return False
        return True
    
    def _acquire_write_core(self):
        self._set_current_writer()
        self._write_count += 1
        
    def _release_write_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._clear_current_writer()
            self._on_writer_abort()

    def _downgrade_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._clear_current_writer()
        self._write_count = 0
        self._readers_active += 1
        self._readers_turn = True
        self.read.condition.notify_all()

    def _is_write_locked(self) -> bool: 
        return self._writer_id is not None


class _RWConditionMixin:
    __slots__ = ()

    def _is_owned_read(self) -> bool:
        return self._lock._is_read_locked()

    def _is_owned_write(self) -> bool:
        return self._lock._is_write_locked()
