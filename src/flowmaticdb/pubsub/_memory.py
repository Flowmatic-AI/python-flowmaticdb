from __future__ import annotations

import os

from flowmaticdb import PubSubError
from flowmaticdb.pubsub._abc import DEFAULT_MAX_QUEUED_MESSAGES, PubSubABC
from flowmaticdb.pubsub._message import Message
from flowmaticdb.pubsub._subscription import Subscription


class MemoryPubSub(PubSubABC):
    """In-process fanout. The default on SQLite.

    No database is involved at all: delivery is a dict lookup and a queue put,
    which makes this the fastest of the three backends by a wide margin.

    It is correct only while publisher and subscriber share a process, which is
    the case SQLite is deployed in here. That assumption is invisible in code
    and breaks silently under ``uvicorn --workers N`` or gunicorn, where each
    worker would get its own broker and cross-worker messages would vanish with
    no error at all. So the pid is recorded at construction and checked on every
    publish and subscribe, turning a silent delivery hole into an immediate one.

    Anyone who genuinely wants pubsub across processes on SQLite constructs
    :class:`PollingPubSub` explicitly and accepts its latency."""

    def __init__(self, max_queued_messages: int = DEFAULT_MAX_QUEUED_MESSAGES) -> None:
        super().__init__(max_queued_messages)
        self._pid = os.getpid()

    def _ensure_same_process(self) -> None:
        current = os.getpid()
        if current != self._pid:
            raise PubSubError(
                f"this pubsub was created in process {self._pid} and is being used from "
                f"process {current}; the in-process backend cannot deliver across a fork. "
                "Run a single worker, or use PollingPubSub."
            )

    def _publish(self, channel: str, payload: str) -> None:
        self._ensure_same_process()
        self._dispatch(Message(channel, payload, None))

    def _on_subscribe(self, subscription: Subscription) -> None:
        self._ensure_same_process()

    def _stop(self) -> None:
        pass
