"""Tests for the native LISTEN/NOTIFY pubsub backend.

These require a PostgreSQL service on ``localhost:5432``::

    docker compose up -d postgres

Every test is skipped when it is unreachable, so the suite stays green without
it. Both drivers are covered: asyncpg listens on the adapter's own event loop,
psycopg on a thread of this package's, and the point of the parametrisation is
that a caller cannot tell which one delivered.
"""
from __future__ import annotations

import socket
import time
from collections.abc import Iterator

import pytest

from flowmaticdb import PubSubError
from flowmaticdb.database import DB, DatabaseABC
from flowmaticdb.pubsub import PostgresPubSub

PG_HOST = "localhost"
PG_PORT = 5432
PG_DBNAME = "postgres"
PG_USER = "postgres"
PG_PASSWORD = ""


def _postgres_reachable(timeout: float = 1.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((PG_HOST, PG_PORT))
        return True
    except OSError:
        return False
    finally:
        sock.close()


pytestmark = pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable on localhost:5432")


@pytest.fixture(params=["asyncpg", "psycopg"])
def db(request: pytest.FixtureRequest) -> Iterator[DatabaseABC]:
    database = DB.connect_postgresql(
        PG_DBNAME,
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        asyncpg_adapter=request.param == "asyncpg",
    )
    yield database
    database.close()


@pytest.fixture
def pubsub(db: DatabaseABC) -> Iterator[PostgresPubSub]:
    backend = PostgresPubSub(db, reconnect_interval=0.05)
    yield backend
    backend.close()


def _await_delivery(subscription: object, count: int, timeout: float = 10.0) -> list[str]:
    from flowmaticdb.pubsub import Subscription

    assert isinstance(subscription, Subscription)
    payloads: list[str] = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline and len(payloads) < count:
        payloads.extend(message.payload for message in subscription.poll())
        time.sleep(0.01)

    return payloads


def test_postgresql_selects_the_native_backend(db: DatabaseABC) -> None:
    assert isinstance(db.pubsub, PostgresPubSub)


def test_a_published_message_is_delivered(pubsub: PostgresPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    time.sleep(0.2)

    pubsub.publish("room_42", "hello")

    assert _await_delivery(subscription, 1) == ["hello"]


def test_publishing_needs_no_table(pubsub: PostgresPubSub, db: DatabaseABC) -> None:
    """The native backend keeps nothing: there is no outbox to create or clean."""
    subscription = pubsub.subscribe(["room_42"])
    time.sleep(0.2)

    pubsub.publish("room_42", "hello")
    _await_delivery(subscription, 1)

    assert "pubsub_messages" not in db.list_tables()


def test_other_channels_are_not_delivered(pubsub: PostgresPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    time.sleep(0.2)

    pubsub.publish("room_7", "not for you")
    pubsub.publish("room_42", "for you")

    assert _await_delivery(subscription, 1) == ["for you"]


def test_fanout_reaches_every_subscriber(pubsub: PostgresPubSub) -> None:
    first = pubsub.subscribe(["room_42"])
    second = pubsub.subscribe(["room_42"])
    time.sleep(0.3)

    pubsub.publish("room_42", "hello")

    assert _await_delivery(first, 1) == ["hello"]
    assert _await_delivery(second, 1) == ["hello"]


def test_messages_keep_their_order(pubsub: PostgresPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    time.sleep(0.2)

    for index in range(20):
        pubsub.publish("room_42", str(index))

    assert _await_delivery(subscription, 20) == [str(index) for index in range(20)]


def test_a_payload_at_the_limit_survives_the_round_trip(pubsub: PostgresPubSub) -> None:
    """7999 bytes is the cap this library enforces on every backend; it exists
    because of this server's 8000-byte NOTIFY limit, so the boundary has to be
    proven against the real thing."""
    subscription = pubsub.subscribe(["room_42"])
    time.sleep(0.2)
    payload = "x" * 7999

    pubsub.publish("room_42", payload)

    assert _await_delivery(subscription, 1) == [payload]


def test_a_payload_over_the_limit_never_reaches_the_server(pubsub: PostgresPubSub) -> None:
    with pytest.raises(PubSubError):
        pubsub.publish("room_42", "x" * 8000)


def test_a_multi_byte_payload_survives(pubsub: PostgresPubSub) -> None:
    subscription = pubsub.subscribe(["room_42"])
    time.sleep(0.2)
    payload = "café € 你好"

    pubsub.publish("room_42", payload)

    assert _await_delivery(subscription, 1) == [payload]


def test_a_payload_that_would_break_naive_quoting_survives(pubsub: PostgresPubSub) -> None:
    """Publishing goes through pg_notify(?, ?) rather than NOTIFY channel,
    'payload' precisely so this is a value and not something to escape."""
    subscription = pubsub.subscribe(["room_42"])
    time.sleep(0.2)
    payload = "it's \"quoted\"; DROP TABLE users; --"

    pubsub.publish("room_42", payload)

    assert _await_delivery(subscription, 1) == [payload]


def test_a_new_channel_is_picked_up(pubsub: PostgresPubSub) -> None:
    first = pubsub.subscribe(["room_42"])
    time.sleep(0.2)
    second = pubsub.subscribe(["room_7"])
    time.sleep(0.3)

    pubsub.publish("room_7", "hello")

    assert _await_delivery(second, 1) == ["hello"]
    assert first.poll() == []


def test_close_stops_the_listener(pubsub: PostgresPubSub) -> None:
    pubsub.subscribe(["room_42"])
    time.sleep(0.2)
    thread = pubsub._listener_thread
    assert thread is not None

    pubsub.close()
    thread.join(timeout=10.0)

    assert not thread.is_alive()


def test_a_dropped_connection_reconnects_and_is_counted(pubsub: PostgresPubSub, db: DatabaseABC) -> None:
    """Every reconnect is a gap -- NOTIFY does not queue for absent listeners --
    so it has to be visible rather than swallowed, or a gateway has no way to
    know its clients need to resync."""
    subscription = pubsub.subscribe(["room_42"])
    time.sleep(0.3)

    db.prepared(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE application_name <> ? AND pid <> pg_backend_pid() AND query LIKE ?",
        ["excluded", "LISTEN%"],
    ).fetch_dicts()

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and subscription.reconnect_count == 0:
        time.sleep(0.05)

    assert subscription.reconnect_count > 0

    time.sleep(0.5)
    pubsub.publish("room_42", "after the gap")

    assert _await_delivery(subscription, 1) == ["after the gap"]


def test_the_listener_connection_is_outside_the_query_pool(db: DatabaseABC) -> None:
    """A listener that claimed a slot against max_concurrent_connections would
    deadlock a saturated pool, and one borrowed from a thread would die with it."""
    from flowmaticdb.adapters import AsyncpgAdapter, PsycopgAdapter

    adapter = db.adapter
    assert isinstance(adapter, AsyncpgAdapter | PsycopgAdapter)

    before = adapter.connection_count()
    connection = adapter.open_listener_connection()

    try:
        assert adapter.connection_count() == before
    finally:
        if isinstance(adapter, AsyncpgAdapter):
            adapter.close_listener_connection(connection)
        else:
            connection.close()
