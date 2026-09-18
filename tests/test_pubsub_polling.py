"""Tests for the polling pubsub backend.

These run against SQLite -- ``:memory:`` is shared across threads here, and a
file database gives each thread its own connection -- so the backend that is
the default on MySQL is still exercised end to end with no server running.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from flowmaticdb import PubSubError, raw
from flowmaticdb.database import DB, DatabaseABC
from flowmaticdb.pubsub import Message, PollingPubSub

TABLE = "pubsub_messages"


@pytest.fixture
def db() -> Iterator[DatabaseABC]:
    database = DB.connect_sqlite(":memory:")
    yield database
    database.close()


@pytest.fixture
def pubsub(db: DatabaseABC) -> Iterator[PollingPubSub]:
    """A backend whose cadence the test drives, so cursor assertions are exact.

    Without this the backend's own thread would be draining the same cursor
    underneath ``poll_once()``, which makes every such assertion a race."""
    backend = PollingPubSub(db, grace_milliseconds=30, run_janitor=False, poll_in_background=False)
    backend.init()
    yield backend
    backend.close()


@pytest.fixture
def background_pubsub(db: DatabaseABC) -> Iterator[PollingPubSub]:
    """A backend polling on its own thread, the way it is deployed."""
    backend = PollingPubSub(db, poll_interval=0.01, grace_milliseconds=10, run_janitor=False)
    backend.init()
    yield backend
    backend.close()


def _insert_at(database: DatabaseABC, channel: str, payload: str, seconds_ago: float) -> None:
    """Write an outbox row with a chosen age, to drive the grace window."""
    database.insert(TABLE).values({
        "channel": channel,
        "payload": payload,
        "created_at": raw(f"strftime('%Y-%m-%d %H:%M:%f', 'now', '-{seconds_ago:.3f} seconds')"),
    }).execute()


def test_init_creates_the_outbox_and_its_index(db: DatabaseABC) -> None:
    PollingPubSub(db).init()

    assert TABLE in db.list_tables()
    description = db.describe_table(TABLE)
    assert {column.name for column in description.columns} == {"id", "channel", "payload", "created_at"}


def test_init_is_idempotent(db: DatabaseABC) -> None:
    backend = PollingPubSub(db)
    backend.init()
    backend.init()

    assert TABLE in db.list_tables()


def test_subscribing_without_init_fails_loudly(db: DatabaseABC) -> None:
    """The cursor is read on the caller's thread on purpose: a missing table has
    to surface here, not as silence plus a counter on a background thread."""
    backend = PollingPubSub(db)

    with pytest.raises(Exception, match="pubsub_messages"):
        backend.subscribe(["room_42"])


def test_publish_writes_a_row(pubsub: PollingPubSub, db: DatabaseABC) -> None:
    pubsub.publish("room_42", "hello")

    rows = db.select(TABLE).execute().fetch_dicts()
    assert len(rows) == 1
    assert rows[0]["channel"] == "room_42"
    assert rows[0]["payload"] == "hello"


def test_a_published_message_is_delivered(background_pubsub: PollingPubSub) -> None:
    subscription = background_pubsub.subscribe(["room_42"])
    background_pubsub.publish("room_42", "hello")

    assert next(subscription.messages(timeout=5.0)).payload == "hello"


def test_only_the_subscribed_channel_is_delivered(background_pubsub: PollingPubSub) -> None:
    subscription = background_pubsub.subscribe(["room_42"])

    background_pubsub.publish("room_7", "not for you")
    background_pubsub.publish("room_42", "for you")

    assert next(subscription.messages(timeout=5.0)).payload == "for you"
    assert subscription.poll() == []


def test_delivery_carries_the_row_id(background_pubsub: PollingPubSub) -> None:
    subscription = background_pubsub.subscribe(["room_42"])
    background_pubsub.publish("room_42", "hello")

    message = next(subscription.messages(timeout=5.0))
    assert message.id is not None
    assert message.id > 0


def test_the_cursor_starts_at_the_current_max_id(pubsub: PollingPubSub, db: DatabaseABC) -> None:
    """A starting gateway wants everything from now on, not the backlog."""
    _insert_at(db, "room_42", "history", 10.0)
    _insert_at(db, "room_42", "more history", 10.0)

    subscription = pubsub.subscribe(["room_42"])

    assert pubsub.cursor == 2
    assert pubsub.poll_once() == 0
    assert subscription.poll() == []


def test_history_before_subscribing_is_not_replayed(pubsub: PollingPubSub, db: DatabaseABC) -> None:
    _insert_at(db, "room_42", "old", 10.0)

    subscription = pubsub.subscribe(["room_42"])
    _insert_at(db, "room_42", "new", 1.0)
    pubsub.poll_once()

    assert [m.payload for m in subscription.poll()] == ["new"]


def test_the_cursor_advances_past_delivered_rows(pubsub: PollingPubSub, db: DatabaseABC) -> None:
    pubsub.subscribe(["room_42"])
    _insert_at(db, "room_42", "one", 1.0)
    _insert_at(db, "room_42", "two", 1.0)

    assert pubsub.poll_once() == 2
    assert pubsub.cursor == 2
    assert pubsub.poll_once() == 0


def test_messages_arrive_in_id_order(pubsub: PollingPubSub, db: DatabaseABC) -> None:
    subscription = pubsub.subscribe(["room_42"])

    for index in range(5):
        _insert_at(db, "room_42", str(index), 1.0)

    pubsub.poll_once()

    assert [m.payload for m in subscription.poll()] == ["0", "1", "2", "3", "4"]


def test_a_batch_is_capped(db: DatabaseABC) -> None:
    backend = PollingPubSub(db, batch_size=2, grace_milliseconds=0, run_janitor=False, poll_in_background=False)
    backend.init()

    try:
        backend.subscribe(["room_42"])
        for index in range(5):
            _insert_at(db, "room_42", str(index), 1.0)

        assert backend.poll_once() == 2
        assert backend.poll_once() == 2
        assert backend.poll_once() == 1
    finally:
        backend.close()


def test_retention_deletes_old_rows_only(db: DatabaseABC) -> None:
    backend = PollingPubSub(db, retention_milliseconds=5_000, run_janitor=False, poll_in_background=False)
    backend.init()

    try:
        _insert_at(db, "room_42", "ancient", 60.0)
        _insert_at(db, "room_42", "recent", 1.0)

        backend.delete_expired()

        remaining = [row["payload"] for row in db.select(TABLE).execute().fetch_dicts()]
        assert remaining == ["recent"]
    finally:
        backend.close()


def test_the_janitor_runs_on_its_interval(db: DatabaseABC) -> None:
    backend = PollingPubSub(
        db,
        poll_interval=0.01,
        grace_milliseconds=0,
        retention_milliseconds=5_000,
        run_janitor=True,
        janitor_interval=0.02,
    )
    backend.init()

    try:
        _insert_at(db, "room_42", "ancient", 60.0)
        backend.subscribe(["room_42"])

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if db.select(TABLE).execute().fetch_dicts() == []:
                break
            time.sleep(0.01)

        assert db.select(TABLE).execute().fetch_dicts() == []
    finally:
        backend.close()


def test_the_janitor_can_be_turned_off(db: DatabaseABC) -> None:
    backend = PollingPubSub(db, poll_interval=0.01, run_janitor=False, janitor_interval=0.01)
    backend.init()

    try:
        backend.subscribe(["room_42"])
        assert backend._janitor_thread is None
    finally:
        backend.close()


def test_close_stops_the_threads(background_pubsub: PollingPubSub) -> None:
    background_pubsub.subscribe(["room_42"])
    poller = background_pubsub._poller_thread
    assert poller is not None

    background_pubsub.close()
    poller.join(timeout=5.0)

    assert not poller.is_alive()


def test_a_poll_failure_is_recorded_and_the_loop_survives(db: DatabaseABC) -> None:
    """A transient outage must not kill delivery for good, so the loop records
    rather than dies -- and the counter is how that stays visible."""
    backend = PollingPubSub(db, poll_interval=0.01, grace_milliseconds=0, run_janitor=False)
    backend.init()

    try:
        backend.subscribe(["room_42"])
        db.drop_table(TABLE).execute()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and backend.error_count == 0:
            time.sleep(0.01)

        assert backend.error_count > 0
        assert backend.last_error is not None

        backend.init()
        _insert_at(db, "room_42", "recovered", 1.0)

        assert backend.poll_once() == 1
    finally:
        backend.close()


def test_the_backend_is_the_default_on_an_unknown_dialect(db: DatabaseABC) -> None:
    """Polling is the only mechanism that works without native push, which makes
    it the honest fallback for a dialect this library has never seen."""
    from flowmaticdb.dialects import SQLDialect

    database = DB.connect_sqlite(":memory:")
    database._dialect = SQLDialect()

    try:
        assert isinstance(database.pubsub, PollingPubSub)
    finally:
        database.close()


def test_a_file_database_delivers_across_threads(tmp_path: Path) -> None:
    """Each thread gets its own connection on a file database, so this is the
    shape a real gateway runs in."""
    database = DB.connect_sqlite(str(tmp_path / "pubsub.db"))
    backend = PollingPubSub(database, poll_interval=0.01, grace_milliseconds=10, run_janitor=False)
    backend.init()

    try:
        subscription = backend.subscribe(["room_42"])
        received: list[Message] = []

        def publish() -> None:
            for index in range(10):
                backend.publish("room_42", str(index))

        publisher = threading.Thread(target=publish)
        publisher.start()
        publisher.join()

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and len(received) < 10:
            received.extend(subscription.poll())
            time.sleep(0.01)

        assert [m.payload for m in received] == [str(index) for index in range(10)]
    finally:
        backend.close()
        database.close()


def test_channel_and_payload_rules_apply_to_this_backend_too(pubsub: PollingPubSub) -> None:
    with pytest.raises(PubSubError, match="invalid channel name"):
        pubsub.publish("Room_42", "hello")

    with pytest.raises(PubSubError):
        pubsub.publish("room_42", "x" * 8000)
