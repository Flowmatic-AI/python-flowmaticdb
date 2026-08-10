from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Generic, TypeVar

from flowmaticdb import AdapterError

T = TypeVar("T")

_SHARED_KEY = "shared"


class _ThreadExitHook:
    """Runs ``callback`` at the moment the thread that armed it exits.

    The hook is parked in a :class:`threading.local`, so CPython drops the last
    reference to it while tearing that thread's state down, and ``__del__`` runs
    *in the dying thread* while it can still do IO. That is what lets a store
    evict -- and an adapter close -- a finished thread's value immediately,
    rather than leaving it open until some later caller happens to notice.

    ``key`` is captured up front on purpose: by the time ``__del__`` runs the
    thread is already out of ``threading._active``, so
    :func:`threading.current_thread` would hand back a fresh dummy object."""

    def __init__(
        self,
        key: threading.Thread,
        callback: Callable[[threading.Thread], None],
    ) -> None:
        self._key = key
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def __del__(self) -> None:
        if self._cancelled:
            return

        # This runs during thread teardown, where an escaping exception is
        # unraisable noise on stderr that no caller is in a position to handle.
        with contextlib.suppress(Exception):
            self._callback(self._key)


class _ThreadExitHookSlot(threading.local):
    """Holds one store's exit hook for the calling thread.

    :class:`threading.local` re-runs ``__init__`` for every thread that touches
    the instance, so ``hook`` is always bound."""

    def __init__(self) -> None:
        super().__init__()
        self.hook: _ThreadExitHook | None = None


class ThreadLocalStore(Generic[T]):
    def __init__(
        self,
        shared_across_threads: bool = False,
        on_thread_exit: Callable[[T], None] | None = None,
    ) -> None:
        self._shared_across_threads = shared_across_threads
        self._on_thread_exit = on_thread_exit
        self._lock = threading.RLock()
        self._values: dict[threading.Thread | str, T] = {}
        self._hooks = _ThreadExitHookSlot()

    @property
    def shared_across_threads(self) -> bool:
        return self._shared_across_threads

    def _key(self) -> threading.Thread | str:
        if self._shared_across_threads:
            return _SHARED_KEY

        return threading.current_thread()

    def _arm_hook(self, key: threading.Thread) -> None:
        if self._hooks.hook is not None:
            return

        self._hooks.hook = _ThreadExitHook(key, self._release)

    def _disarm_hook(self) -> None:
        hook = self._hooks.hook
        if hook is None:
            return

        hook.cancel()
        self._hooks.hook = None

    def _release(self, key: threading.Thread) -> None:
        """Evict a dead thread's value and hand it to ``on_thread_exit``.

        The pop happens under the lock, so this races safely against
        :meth:`take_all` and :meth:`take_orphaned` -- whoever pops the value is
        the only one that disposes of it."""
        with self._lock:
            value = self._values.pop(key, None)

        if value is None or self._on_thread_exit is None:
            return

        self._on_thread_exit(value)

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
        key = self._key()
        with self._lock:
            self._values[key] = value

        # A shared value outlives every individual thread, so it must not be
        # torn down when one of them exits.
        if isinstance(key, threading.Thread):
            self._arm_hook(key)

    def discard(self) -> T | None:
        key = self._key()
        with self._lock:
            value = self._values.pop(key, None)

        if isinstance(key, threading.Thread):
            self._disarm_hook()

        return value

    def values(self) -> list[T]:
        with self._lock:
            return list(self._values.values())

    def take_all(self) -> list[T]:
        with self._lock:
            values = list(self._values.values())
            self._values.clear()

        return values

    def take_orphaned(self) -> list[T]:
        """Sweep values whose thread has finished.

        A backstop only: :class:`_ThreadExitHook` normally evicts these at the
        instant the thread exits. This still catches the cases the hook cannot
        reach -- a thread killed without running its teardown, or a value bound
        before the hook was armed."""
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
