from __future__ import annotations

import re
import threading
from abc import ABC, abstractmethod

from flowmaticdb import PubSubError
from flowmaticdb.pubsub._message import Message
from flowmaticdb.pubsub._subscription import Subscription

CHANNEL_PATTERN = re.compile(r"^[a-z0-9_]{1,63}$")

MAX_PAYLOAD_BYTES = 7999

DEFAULT_MAX_QUEUED_MESSAGES = 1000


class PubSubABC(ABC):
    """Fanout publish/subscribe with the same observable behaviour on every engine.

    The limits enforced here are PostgreSQL's: channel names are identifiers
    capped at 63 bytes and ``NOTIFY`` payloads at 8000. They are applied on
    every backend on purpose -- a payload that works on SQLite has to work on
    PostgreSQL, and finding out otherwise in production is the failure this
    class exists to prevent.

    Delivery is at-most-once and fire-and-forget. A subscriber that was not
    connected does not get history."""

    def __init__(self, max_queued_messages: int = DEFAULT_MAX_QUEUED_MESSAGES) -> None:
        if max_queued_messages < 1:
            raise PubSubError("max_queued_messages must be at least 1")

        self._max_queued_messages = max_queued_messages
        self._subscriptions: list[Subscription] = []
        self._subscriptions_lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @staticmethod
    def validate_channel(channel: str) -> None:
        if not CHANNEL_PATTERN.match(channel):
            raise PubSubError(
                f"invalid channel name {channel!r}; channels are 1-63 characters of "
                "lowercase letters, digits and underscores"
            )

    @staticmethod
    def validate_payload(payload: str) -> None:
        size = len(payload.encode("utf-8"))
        if size > MAX_PAYLOAD_BYTES:
            raise PubSubError(
                f"payload is {size} bytes; the limit is {MAX_PAYLOAD_BYTES} bytes on every backend"
            )

    def publish(self, channel: str, payload: str) -> None:
        self._ensure_not_closed()
        self.validate_channel(channel)
        self.validate_payload(payload)
        self._publish(channel, payload)

    def subscribe(self, channels: list[str]) -> Subscription:
        self._ensure_not_closed()

        if not channels:
            raise PubSubError("subscribe() needs at least one channel")

        for channel in channels:
            self.validate_channel(channel)

        subscription = Subscription(channels, self._max_queued_messages)

        with self._subscriptions_lock:
            self._subscriptions.append(subscription)

        try:
            self._on_subscribe(subscription)
        except Exception:
            self.unsubscribe(subscription)
            raise

        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._subscriptions_lock:
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)

        subscription.close()

    def close(self) -> None:
        if self._closed:
            return

        self._closed = True

        with self._subscriptions_lock:
            subscriptions = list(self._subscriptions)
            self._subscriptions.clear()

        for subscription in subscriptions:
            subscription.close()

        self._stop()

    def _ensure_not_closed(self) -> None:
        if self._closed:
            raise PubSubError("this pubsub is closed")

    def _subscribed_channels(self) -> set[str]:
        with self._subscriptions_lock:
            channels: set[str] = set()
            for subscription in self._subscriptions:
                channels.update(subscription.channels)
            return channels

    def _dispatch(self, message: Message) -> None:
        """Fan one message out to every subscription listening on its channel."""
        with self._subscriptions_lock:
            subscriptions = list(self._subscriptions)

        for subscription in subscriptions:
            if message.channel in subscription.channels:
                subscription.deliver(message)

    def _dispatch_reconnect(self) -> None:
        with self._subscriptions_lock:
            subscriptions = list(self._subscriptions)

        for subscription in subscriptions:
            subscription.note_reconnect()

    @abstractmethod
    def _publish(self, channel: str, payload: str) -> None:
        ...

    @abstractmethod
    def _on_subscribe(self, subscription: Subscription) -> None:
        """Start whatever machinery delivery needs.

        Called on *every* subscribe, so implementations make starting idempotent
        rather than relying on being called once. That is also what lets a
        backend re-check a precondition -- the in-process broker checks it is
        still in the process it was built in."""

    @abstractmethod
    def _stop(self) -> None:
        """Tear down threads and connections. Called once, from :meth:`close`."""
