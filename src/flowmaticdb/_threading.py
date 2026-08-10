from __future__ import annotations

import threading
from typing import Generic, TypeVar

from flowmaticdb._exceptions import AdapterError

T = TypeVar("T")

_SHARED_KEY = "shared"


class ThreadLocalStore(Generic[T]):
    def __init__(self, shared_across_threads: bool = False) -> None:
        self._shared_across_threads = shared_across_threads
        self._lock = threading.RLock()
        self._values: dict[threading.Thread | str, T] = {}

    @property
    def shared_across_threads(self) -> bool:
        return self._shared_across_threads

    def _key(self) -> threading.Thread | str:
        if self._shared_across_threads:
            return _SHARED_KEY

        return threading.current_thread()

    def current(self) -> T | None:
        with self._lock:
            return self._values.get(self._key())

    def require(self) -> T:
        with self._lock:
            value = self._values.get(self._key())

        if value is None:
            raise AdapterError("no connection is bound to the current thread")

        return value

    def set(self, value: T) -> None:
        with self._lock:
            self._values[self._key()] = value

    def discard(self) -> T | None:
        with self._lock:
            return self._values.pop(self._key(), None)

    def values(self) -> list[T]:
        with self._lock:
            return list(self._values.values())

    def take_all(self) -> list[T]:
        with self._lock:
            values = list(self._values.values())
            self._values.clear()

        return values

    def take_orphaned(self) -> list[T]:
        with self._lock:
            orphaned = [
                key
                for key in self._values
                if isinstance(key, threading.Thread) and not key.is_alive()
            ]
            return [self._values.pop(key) for key in orphaned]

    def count(self) -> int:
        with self._lock:
            return len(self._values)
