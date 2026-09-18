"""The cursor-skew hazard the polling backend's grace window exists to close.

``id > cursor`` is unsafe under concurrent writers on every engine. Transaction
A takes id 100 and B takes 101; B commits first; a reader sitting at 99 sees
101, advances past it, and only then does 100 become visible -- skipped forever.
It is silent, and it only shows up under load.

These tests reproduce that interleaving deterministically by inserting explicit
ids out of order, which is exactly what concurrent transactions do to the reader.
The first test asserts the loss *happens* without a window, so that the rest is
demonstrably guarding against something real rather than against a theory.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from flowmaticdb import raw
from flowmaticdb.database import DB, DatabaseABC
from flowmaticdb.pubsub import Message, PollingPubSub

TABLE = "pubsub_messages"


@pytest.fixture
def db() -> Iterator[DatabaseABC]:
    database = DB.connect_sqlite(":memory:")
    yield database
    database.close()


def _insert_with_id(database: DatabaseABC, row_id: int, payload: str, seconds_ago: float) -> None:
    database.insert(TABLE).values({
        "id": row_id,
        "channel": "room_42",
        "payload": payload,
        "created_at": raw(f"strftime('%Y-%m-%d %H:%M:%f', 'now', '-{seconds_ago:.3f} seconds')"),
    }).execute()


def test_without_a_grace_window_a_late_row_is_skipped(db: DatabaseABC) -> None:
    """The bug, reproduced. This is what the window buys, and what regressing it
    would cost: a message accepted by publish() that no subscriber ever sees."""
    backend = PollingPubSub(db, grace_milliseconds=0, run_janitor=False, poll_in_background=False)
    backend.init()

    try:
        subscription = backend.subscribe(["room_42"])

        # The later transaction commits first.
        _insert_with_id(db, 2, "committed first", 1.0)
        assert backend.poll_once() == 1
        assert backend.cursor == 2

        # The earlier one lands afterwards, below the cursor.
        _insert_with_id(db, 1, "committed second", 1.0)

        assert backend.poll_once() == 0
        assert [m.payload for m in subscription.poll()] == ["committed first"]
    finally:
        backend.close()


def test_the_grace_window_holds_a_row_back_until_it_is_safe(db: DatabaseABC) -> None:
    backend = PollingPubSub(db, grace_milliseconds=300, run_janitor=False, poll_in_background=False)
    backend.init()

    try:
        backend.subscribe(["room_42"])
        _insert_with_id(db, 1, "fresh", 0.0)

        assert backend.poll_once() == 0
        assert backend.cursor == 0

        time.sleep(0.35)

        assert backend.poll_once() == 1
        assert backend.cursor == 1
    finally:
        backend.close()


def test_the_grace_window_prevents_the_skip(db: DatabaseABC) -> None:
    """Same interleaving as the first test, with the window in place: the
    out-of-order row is still too recent to be read, so the cursor never
    advances past the id that has not arrived yet."""
    backend = PollingPubSub(db, grace_milliseconds=300, run_janitor=False, poll_in_background=False)
    backend.init()

    try:
        subscription = backend.subscribe(["room_42"])

        _insert_with_id(db, 2, "committed first", 0.0)
        assert backend.poll_once() == 0
        assert backend.cursor == 0

        _insert_with_id(db, 1, "committed second", 0.0)

        time.sleep(0.35)

        assert backend.poll_once() == 2
        assert [m.payload for m in subscription.poll()] == ["committed second", "committed first"]
    finally:
        backend.close()


def test_the_window_is_measured_against_database_time(db: DatabaseABC) -> None:
    """The comparison has to come from the database, not from Python, or clock
    skew between application servers reintroduces the very skip above."""
    cutoff = db.dialect.timestamp_minus_milliseconds(50)

    assert "now" in cutoff.sql(db.dialect)
    assert "?" not in cutoff.sql(db.dialect)


@pytest.mark.parametrize("grace_milliseconds", [0, 50, 300])
def test_no_message_is_ever_delivered_twice(db: DatabaseABC, grace_milliseconds: int) -> None:
    backend = PollingPubSub(db, grace_milliseconds=grace_milliseconds, run_janitor=False, poll_in_background=False)
    backend.init()

    try:
        subscription = backend.subscribe(["room_42"])

        for index in range(20):
            _insert_with_id(db, index + 1, str(index), 1.0)

        for _ in range(5):
            backend.poll_once()

        assert [m.payload for m in subscription.poll()] == [str(index) for index in range(20)]
    finally:
        backend.close()


def test_concurrent_publishers_lose_nothing(tmp_path: Path) -> None:
    """The load-shaped version: real concurrent writers on a file database, each
    taking its own id. Every message published has to arrive, exactly once, in
    ascending id order."""
    database = DB.connect_sqlite(str(tmp_path / "skew.db"))
    backend = PollingPubSub(database, poll_interval=0.01, grace_milliseconds=100, run_janitor=False)
    backend.init()

    publishers = 4
    per_publisher = 25
    expected = publishers * per_publisher

    try:
        subscription = backend.subscribe(["room_42"])
        start = threading.Barrier(publishers)

        def publish(worker: int) -> None:
            start.wait()
            for index in range(per_publisher):
                backend.publish("room_42", f"{worker}-{index}")

        threads = [threading.Thread(target=publish, args=(worker,)) for worker in range(publishers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        received: list[Message] = []
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and len(received) < expected:
            received.extend(subscription.poll())
            time.sleep(0.02)

        payloads = [m.payload for m in received]
        ids = [m.id for m in received]

        assert len(payloads) == expected
        assert len(set(payloads)) == expected
        assert ids == sorted(ids)
        assert subscription.dropped_count == 0
    finally:
        backend.close()
        database.close()
