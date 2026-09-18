from __future__ import annotations

import queue
import threading
from collections.abc import Iterator

from flowmaticdb.pubsub._message import Message


class Subscription:
    """A consumer's end of a channel set.

    Every backend -- the in-process broker, the PostgreSQL listener thread, the
    polling thread -- ends at the same place: it calls :meth:`deliver` and the
    message lands in this queue. That is what keeps one API over three very
    different mechanisms from leaking which one it got.

    The queue is bounded and drops the *oldest* message when it overflows. A
    slow consumer must never be able to block the thread feeding it, because
    that thread is shared with every other subscription on the same backend."""

    def __init__(self, channels: list[str], max_queued_messages: int) -> None:
        self._channels = frozenset(channels)
        self._queue: queue.Queue[Message | None] = queue.Queue(maxsize=max_queued_messages)
        self._lock = threading.Lock()
        self._dropped_count = 0
        self._reconnect_count = 0
        self._closed = False

    @property
    def channels(self) -> frozenset[str]:
        return self._channels

    @property
    def dropped_count(self) -> int:
        """Messages discarded because this consumer fell behind."""
        with self._lock:
            return self._dropped_count

    @property
    def reconnect_count(self) -> int:
        """Times the backend's connection dropped and came back.

        Each one is a gap: messages published while the listener was away are
        gone. A gateway watching this is what lets clients be told to resync."""
        with self._lock:
            return self._reconnect_count

    @property
    def closed(self) -> bool:
        return self._closed

    def deliver(self, message: Message) -> None:
        """Enqueue a message, dropping the oldest one when full.

        Called from the backend's thread, never from the consumer's. The lock
        serializes producers so the drop-and-retry below cannot spin: consumers
        take from the queue under its own lock, so there is no lock ordering to
        get wrong here."""
        with self._lock:
            if self._closed:
                return

            try:
                self._queue.put_nowait(message)
                return
            except queue.Full:
                pass

            try:
                self._queue.get_nowait()
                self._dropped_count += 1
            except queue.Empty:
                # A consumer drained it between the put and the get, so there is
                # room again and nothing had to be dropped.
                pass

            try:
                self._queue.put_nowait(message)
            except queue.Full:
                self._dropped_count += 1

    def note_reconnect(self) -> None:
        with self._lock:
            self._reconnect_count += 1

    def poll(self) -> list[Message]:
        """Take everything waiting, without blocking.

        This is the hook for an asyncio consumer that would rather drain on its
        own schedule than park a thread in :meth:`messages`."""
        messages: list[Message] = []

        while True:
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                return messages

            if message is not None:
                messages.append(message)

    def messages(self, timeout: float | None = None) -> Iterator[Message]:
        """Yield messages as they arrive.

        Ends when the subscription is closed, or -- with a ``timeout`` -- when
        nothing arrives within it. Without one it blocks until close."""
        while True:
            if self._closed:
                return

            try:
                message = self._queue.get(timeout=timeout)
            except queue.Empty:
                return

            if message is None:
                return

            yield message

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True

        # Wakes a consumer parked in messages() with no timeout. put_nowait can
        # fail on a full queue, and that is fine: a full queue means the
        # consumer is not parked, so it will see _closed on its next pass.
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
