"""Unit tests for the in-process pubsub backend and the shared core.

No database is involved: ``MemoryPubSub`` is the SQLite default precisely
because it never touches one. The validation, fanout, queue-overflow and
lifecycle rules asserted here are enforced on ``PubSubABC`` itself, so they hold
for every backend.
"""
from __future__ import annotations

import os
import threading
from typing import Any
from unittest import mock

import pytest

from flowmaticdb import PubSubError
from flowmaticdb.database import DB
from flowmaticdb.pubsub import MemoryPubSub, Message, PollingPubSub, PostgresPubSub, PubSubBackendEnum


@pytest.fixture
def pubsub() -> MemoryPubSub:
    return MemoryPubSub()


def test_publish_reaches_a_subscriber_on_the_same_channel(pubsub: MemoryPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    pubsub.publish("room_42", "hello")

    assert subscription.poll() == [Message("room_42", "hello", None)]


def test_publish_fans_out_to_every_subscriber(pubsub: MemoryPubSub) -> None:
    first = pubsub.subscribe(["room_42"])
    second = pubsub.subscribe(["room_42"])

    pubsub.publish("room_42", "hello")

    assert [m.payload for m in first.poll()] == ["hello"]
    assert [m.payload for m in second.poll()] == ["hello"]


def test_other_channels_are_not_delivered(pubsub: MemoryPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    pubsub.publish("room_7", "not for you")

    assert subscription.poll() == []


def test_a_subscription_can_span_channels(pubsub: MemoryPubSub) -> None:
    subscription = pubsub.subscribe(["room_42", "room_7"])

    pubsub.publish("room_7", "b")
    pubsub.publish("room_42", "a")

    assert [m.payload for m in subscription.poll()] == ["b", "a"]


def test_publishing_with_no_subscriber_is_not_an_error(pubsub: MemoryPubSub) -> None:
    pubsub.publish("room_42", "into the void")


def test_messages_blocks_until_one_arrives(pubsub: MemoryPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])

    def publish_soon() -> None:
        pubsub.publish("room_42", "late")

    threading.Timer(0.05, publish_soon).start()

    assert next(subscription.messages(timeout=5.0)).payload == "late"


def test_messages_stops_on_timeout(pubsub: MemoryPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])

    assert list(subscription.messages(timeout=0.01)) == []


def test_messages_stops_when_the_subscription_closes(pubsub: MemoryPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    received: list[Message] = []

    def consume() -> None:
        received.extend(subscription.messages())

    consumer = threading.Thread(target=consume)
    consumer.start()

    pubsub.publish("room_42", "one")
    subscription.close()
    consumer.join(timeout=5.0)

    assert not consumer.is_alive()
    assert [m.payload for m in received] == ["one"]


@pytest.mark.parametrize(
    "channel",
    ["", "Room_42", "room-42", "room 42", "room.42", "a" * 64, "rooms;DROP TABLE x"],
)
def test_invalid_channel_names_are_refused(pubsub: MemoryPubSub, channel: str) -> None:
    with pytest.raises(PubSubError, match="invalid channel name"):
        pubsub.publish(channel, "payload")

    with pytest.raises(PubSubError, match="invalid channel name"):
        pubsub.subscribe([channel])


@pytest.mark.parametrize("channel", ["a", "room_42", "r7", "a" * 63])
def test_valid_channel_names_are_accepted(pubsub: MemoryPubSub, channel: str) -> None:
    pubsub.publish(channel, "payload")


def test_payload_at_the_limit_is_accepted(pubsub: MemoryPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    payload = "x" * 7999

    pubsub.publish("room_42", payload)

    assert subscription.poll()[0].payload == payload


def test_payload_over_the_limit_is_refused(pubsub: MemoryPubSub) -> None:
    with pytest.raises(PubSubError, match="8000 bytes|7999 bytes"):
        pubsub.publish("room_42", "x" * 8000)


def test_the_payload_limit_counts_bytes_not_characters(pubsub: MemoryPubSub) -> None:
    """The cap is PostgreSQL's, which counts bytes -- so multi-byte characters
    have to be measured encoded, or a payload that passes here would be refused
    by the server."""
    payload = "€" * 2667  # 3 bytes each -> 8001

    with pytest.raises(PubSubError):
        pubsub.publish("room_42", payload)


def test_subscribe_needs_a_channel(pubsub: MemoryPubSub) -> None:
    with pytest.raises(PubSubError, match="at least one channel"):
        pubsub.subscribe([])


def test_a_slow_consumer_drops_the_oldest_messages() -> None:
    pubsub = MemoryPubSub(max_queued_messages=3)
    subscription = pubsub.subscribe(["room_42"])

    for index in range(6):
        pubsub.publish("room_42", str(index))

    assert [m.payload for m in subscription.poll()] == ["3", "4", "5"]
    assert subscription.dropped_count == 3


def test_a_slow_consumer_does_not_block_the_publisher() -> None:
    """The point of dropping rather than blocking: one stalled subscriber must
    not stop delivery to the others, because they share a producing thread."""
    pubsub = MemoryPubSub(max_queued_messages=1)
    stalled = pubsub.subscribe(["room_42"])
    healthy = pubsub.subscribe(["room_42"])

    for index in range(10):
        pubsub.publish("room_42", str(index))
        healthy.poll()

    assert stalled.dropped_count == 9
    assert healthy.dropped_count == 0


def test_max_queued_messages_must_be_positive() -> None:
    with pytest.raises(PubSubError, match="at least 1"):
        MemoryPubSub(max_queued_messages=0)


def test_unsubscribe_stops_delivery(pubsub: MemoryPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    pubsub.unsubscribe(subscription)

    pubsub.publish("room_42", "hello")

    assert subscription.poll() == []
    assert subscription.closed


def test_close_ends_every_subscription(pubsub: MemoryPubSub) -> None:
    first = pubsub.subscribe(["room_42"])
    second = pubsub.subscribe(["room_7"])

    pubsub.close()

    assert pubsub.closed
    assert first.closed
    assert second.closed


def test_close_is_idempotent(pubsub: MemoryPubSub) -> None:
    pubsub.close()
    pubsub.close()


def test_publishing_after_close_is_refused(pubsub: MemoryPubSub) -> None:
    pubsub.close()

    with pytest.raises(PubSubError, match="closed"):
        pubsub.publish("room_42", "hello")


def test_subscribing_after_close_is_refused(pubsub: MemoryPubSub) -> None:
    pubsub.close()

    with pytest.raises(PubSubError, match="closed"):
        pubsub.subscribe(["room_42"])


def test_a_fork_is_refused_on_publish(pubsub: MemoryPubSub) -> None:
    """The failure this guard exists for: under ``uvicorn --workers N`` each
    worker gets its own broker, so a publish in one is invisible in another.
    Without the check that is silent; with it, it is immediate."""
    with (
        mock.patch.object(os, "getpid", return_value=os.getpid() + 1),
        pytest.raises(PubSubError, match="cannot deliver across a fork"),
    ):
        pubsub.publish("room_42", "hello")


def test_a_fork_is_refused_on_subscribe(pubsub: MemoryPubSub) -> None:
    with (
        mock.patch.object(os, "getpid", return_value=os.getpid() + 1),
        pytest.raises(PubSubError, match="cannot deliver across a fork"),
    ):
        pubsub.subscribe(["room_42"])


def test_the_fork_guard_names_both_processes(pubsub: MemoryPubSub) -> None:
    own_pid = os.getpid()

    with (
        mock.patch.object(os, "getpid", return_value=own_pid + 1),
        pytest.raises(PubSubError) as raised,
    ):
        pubsub.publish("room_42", "hello")

    assert str(own_pid) in str(raised.value)
    assert str(own_pid + 1) in str(raised.value)


def test_sqlite_selects_the_in_process_backend() -> None:
    db = DB.connect_sqlite(":memory:")
    try:
        assert isinstance(db.pubsub, MemoryPubSub)
    finally:
        db.close()


def test_the_pubsub_property_is_cached() -> None:
    db = DB.connect_sqlite(":memory:")
    try:
        assert db.pubsub is db.pubsub
    finally:
        db.close()


def test_racing_threads_get_one_instance() -> None:
    """Connections are thread-local here, so two request threads touching this
    for the first time at once is ordinary. Two instances would be two
    unconnected brokers -- the exact split the property exists to prevent."""
    db = DB.connect_sqlite(":memory:")
    seen: list[Any] = []
    start = threading.Barrier(8)

    def touch() -> None:
        start.wait()
        seen.append(db.pubsub)

    threads = [threading.Thread(target=touch) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len(seen) == 8
        assert all(instance is seen[0] for instance in seen)
    finally:
        db.close()


def test_closing_the_database_closes_the_pubsub() -> None:
    db = DB.connect_sqlite(":memory:")
    pubsub = db.pubsub
    subscription = pubsub.subscribe(["room_42"])

    db.close()

    assert pubsub.closed
    assert subscription.closed


def test_the_database_only_builds_a_pubsub_when_asked() -> None:
    """Construction has to be cheap and lazy -- the property must not start a
    thread or open a connection just because something touched it."""
    db = DB.connect_sqlite(":memory:")
    try:
        assert db._pubsub is None
    finally:
        db.close()


def test_options_tune_the_queue_size() -> None:
    db = DB.connect_sqlite(":memory:", options={"pubsub_max_queued_messages": 2})
    try:
        subscription = db.pubsub.subscribe(["room_42"])
        for index in range(5):
            db.pubsub.publish("room_42", str(index))

        assert [m.payload for m in subscription.poll()] == ["3", "4"]
    finally:
        db.close()




def test_the_backend_enum_accepts_its_own_members() -> None:
    db = DB.connect_sqlite(":memory:", options={"pubsub_backend": PubSubBackendEnum.POLLING})
    try:
        assert isinstance(db.pubsub, PollingPubSub)
    finally:
        db.close()


def test_the_backend_enum_accepts_plain_strings() -> None:
    """Options often arrive from configuration, where a member is a string."""
    db = DB.connect_sqlite(":memory:", options={"pubsub_backend": "polling"})
    try:
        assert isinstance(db.pubsub, PollingPubSub)
    finally:
        db.close()


def test_a_custom_dialect_can_ask_for_the_in_process_broker() -> None:
    """The case this exists for: a dialect the library has never seen, whose
    owner knows their deployment is single-process."""
    from flowmaticdb.dialects import SQLDialect

    db = DB.connect_sqlite(":memory:", options={"pubsub_backend": "memory"})
    db._dialect = SQLDialect(options={"pubsub_backend": "memory"})

    try:
        assert isinstance(db.pubsub, MemoryPubSub)
    finally:
        db.close()


def test_an_unknown_dialect_defaults_to_polling_not_memory() -> None:
    """Polling is the honest default for an unknown engine: it delivers between
    processes, and it fails loudly rather than silently when a dialect cannot
    express its SQL. Memory would never fail and never cross a process."""
    from flowmaticdb.dialects import SQLDialect

    db = DB.connect_sqlite(":memory:")
    db._dialect = SQLDialect()

    try:
        assert isinstance(db.pubsub, PollingPubSub)
    finally:
        db.close()


def test_a_misspelled_backend_is_refused() -> None:
    """Falling back to the default would hand back a working object that
    delivers somewhere other than where it was asked to."""
    db = DB.connect_sqlite(":memory:", options={"pubsub_backend": "momory"})

    try:
        with pytest.raises(PubSubError, match="unknown pubsub_backend"):
            _ = db.pubsub
    finally:
        db.close()


def test_the_refusal_lists_the_valid_backends() -> None:
    db = DB.connect_sqlite(":memory:", options={"pubsub_backend": "redis"})

    try:
        with pytest.raises(PubSubError) as raised:
            _ = db.pubsub
    finally:
        db.close()

    for member in PubSubBackendEnum:
        assert member.value in str(raised.value)


def test_every_backend_can_be_named_explicitly() -> None:
    expected = {
        PubSubBackendEnum.MEMORY: MemoryPubSub,
        PubSubBackendEnum.POLLING: PollingPubSub,
        PubSubBackendEnum.POSTGRES: PostgresPubSub,
    }

    for backend, backend_class in expected.items():
        db = DB.connect_sqlite(":memory:", options={"pubsub_backend": backend})
        try:
            assert isinstance(db.pubsub, backend_class)
        finally:
            db.close()
