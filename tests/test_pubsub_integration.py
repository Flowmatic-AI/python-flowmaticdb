"""Cross-engine pubsub tests: the same behaviour on all three backends.

Every test runs against SQLite, PostgreSQL and MySQL through ``db.pubsub``,
whichever backend that resolves to. SQLite always runs; the other two are
skipped when their server is unreachable. Bring both up with::

    docker compose up -d

The point of this suite is the portability contract. A caller writes one thing
and gets the same observable behaviour whether it is delivered by an in-process
dict, by LISTEN/NOTIFY, or by a polled table -- so what is asserted here is only
what every backend promises, never one backend's extras.
"""
from __future__ import annotations

import socket
import time
from collections.abc import Iterator

import pytest

from flowmaticdb import PubSubError
from flowmaticdb.database import DB, DatabaseABC
from flowmaticdb.pubsub import MemoryPubSub, PollingPubSub, PostgresPubSub, Subscription

PG_HOST: str = "localhost"
PG_PORT: int = 5432
PG_DBNAME: str = "postgres"
PG_USER: str = "postgres"

MYSQL_HOST: str = "localhost"
MYSQL_PORT: int = 3306
MYSQL_USER: str = "root"
MYSQL_PASSWORD: str = ""
MYSQL_DATABASE: str = "flowmaticdb"

PUBSUB_TABLE: str = "pubsub_messages"


def _port_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _mysql_database() -> bool:
    import mysql.connector

    try:
        connection = mysql.connector.connect(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD
        )
    except Exception:  # noqa: BLE001 - any driver failure means "no server"
        return False

    try:
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}`")
        connection.commit()
        cursor.close()
    finally:
        connection.close()

    return True


@pytest.fixture(params=["sqlite", "postgres", "mysql"])
def pubsub_db(request: pytest.FixtureRequest) -> Iterator[DatabaseABC]:
    engine: str = request.param

    if engine == "sqlite":
        db: DatabaseABC = DB.connect_sqlite(":memory:")
    elif engine == "postgres":
        if not _port_reachable(PG_HOST, PG_PORT):
            pytest.skip("PostgreSQL is not reachable on localhost:5432")

        db = DB.connect_postgresql(PG_DBNAME, host=PG_HOST, port=PG_PORT, user=PG_USER)
    else:
        if not _port_reachable(MYSQL_HOST, MYSQL_PORT) or not _mysql_database():
            pytest.skip("MySQL is not reachable on localhost:3306")

        db = DB.connect_mysql(
            MYSQL_DATABASE,
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            options={"pubsub_poll_interval": 0.02, "pubsub_grace_milliseconds": 20, "pubsub_run_janitor": False},
        )

    pubsub = db.pubsub

    if isinstance(pubsub, PollingPubSub):
        db.drop_table(PUBSUB_TABLE).if_exists().execute()
        pubsub.init()

    try:
        yield db
    finally:
        db.close()

        if isinstance(pubsub, PollingPubSub):
            cleanup = DB.connect_mysql(
                MYSQL_DATABASE, host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASSWORD
            )
            cleanup.drop_table(PUBSUB_TABLE).if_exists().execute()
            cleanup.close()


def _settle(db: DatabaseABC) -> None:
    """Give a backend that delivers off-thread a moment to be listening."""
    if not isinstance(db.pubsub, MemoryPubSub):
        time.sleep(0.3)


def _await_delivery(subscription: Subscription, count: int, timeout: float = 15.0) -> list[str]:
    payloads: list[str] = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline and len(payloads) < count:
        payloads.extend(message.payload for message in subscription.poll())
        time.sleep(0.01)

    return payloads


def test_each_engine_gets_its_intended_backend(pubsub_db: DatabaseABC) -> None:
    from flowmaticdb.dialects import MySQLDialect, PostgresqlDialect, SQLiteDialect

    dialect = pubsub_db.dialect
    pubsub = pubsub_db.pubsub

    if isinstance(dialect, PostgresqlDialect):
        assert isinstance(pubsub, PostgresPubSub)
    elif isinstance(dialect, SQLiteDialect):
        assert isinstance(pubsub, MemoryPubSub)
    else:
        assert isinstance(dialect, MySQLDialect)
        assert isinstance(pubsub, PollingPubSub)


def test_the_property_is_cached_on_every_engine(pubsub_db: DatabaseABC) -> None:
    assert pubsub_db.pubsub is pubsub_db.pubsub


def test_a_published_message_is_delivered(pubsub_db: DatabaseABC) -> None:
    subscription = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)

    pubsub_db.pubsub.publish("room_42", "hello")

    assert _await_delivery(subscription, 1) == ["hello"]


def test_fanout_reaches_every_subscriber(pubsub_db: DatabaseABC) -> None:
    first = pubsub_db.pubsub.subscribe(["room_42"])
    second = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)

    pubsub_db.pubsub.publish("room_42", "hello")

    assert _await_delivery(first, 1) == ["hello"]
    assert _await_delivery(second, 1) == ["hello"]


def test_other_channels_are_not_delivered(pubsub_db: DatabaseABC) -> None:
    subscription = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)

    pubsub_db.pubsub.publish("room_7", "not for you")
    pubsub_db.pubsub.publish("room_42", "for you")

    assert _await_delivery(subscription, 1) == ["for you"]


def test_a_subscription_can_span_channels(pubsub_db: DatabaseABC) -> None:
    subscription = pubsub_db.pubsub.subscribe(["room_42", "room_7"])
    _settle(pubsub_db)

    pubsub_db.pubsub.publish("room_42", "a")
    pubsub_db.pubsub.publish("room_7", "b")

    assert sorted(_await_delivery(subscription, 2)) == ["a", "b"]


def test_order_is_kept_within_a_channel(pubsub_db: DatabaseABC) -> None:
    subscription = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)

    for index in range(15):
        pubsub_db.pubsub.publish("room_42", str(index))

    assert _await_delivery(subscription, 15) == [str(index) for index in range(15)]


def test_publishing_with_no_subscriber_is_not_an_error(pubsub_db: DatabaseABC) -> None:
    pubsub_db.pubsub.publish("room_42", "into the void")


def test_history_before_subscribing_is_not_replayed(pubsub_db: DatabaseABC) -> None:
    """At-most-once and no replay, on every backend: a websocket client resyncs
    on reconnect, so this is the contract rather than a shortfall."""
    pubsub_db.pubsub.publish("room_42", "before")

    subscription = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)
    pubsub_db.pubsub.publish("room_42", "after")

    assert _await_delivery(subscription, 1) == ["after"]


@pytest.mark.parametrize("channel", ["Room_42", "room-42", "", "a" * 64])
def test_channel_rules_are_identical_everywhere(pubsub_db: DatabaseABC, channel: str) -> None:
    with pytest.raises(PubSubError, match="invalid channel name"):
        pubsub_db.pubsub.publish(channel, "payload")


def test_the_payload_limit_is_identical_everywhere(pubsub_db: DatabaseABC) -> None:
    """Enforced on SQLite and MySQL too, though neither needs it: a payload that
    works in development has to work in production."""
    subscription = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)

    pubsub_db.pubsub.publish("room_42", "x" * 7999)
    assert _await_delivery(subscription, 1) == ["x" * 7999]

    with pytest.raises(PubSubError):
        pubsub_db.pubsub.publish("room_42", "x" * 8000)


def test_a_multi_byte_payload_survives(pubsub_db: DatabaseABC) -> None:
    subscription = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)
    payload = "café € 你好"

    pubsub_db.pubsub.publish("room_42", payload)

    assert _await_delivery(subscription, 1) == [payload]


def test_a_payload_that_would_break_naive_quoting_survives(pubsub_db: DatabaseABC) -> None:
    subscription = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)
    payload = "it's \"quoted\"; DROP TABLE users; --"

    pubsub_db.pubsub.publish("room_42", payload)

    assert _await_delivery(subscription, 1) == [payload]


def test_unsubscribe_stops_delivery(pubsub_db: DatabaseABC) -> None:
    subscription = pubsub_db.pubsub.subscribe(["room_42"])
    _settle(pubsub_db)

    pubsub_db.pubsub.unsubscribe(subscription)
    pubsub_db.pubsub.publish("room_42", "hello")
    time.sleep(0.3)

    assert subscription.poll() == []
    assert subscription.closed


def test_closing_the_database_closes_the_pubsub(pubsub_db: DatabaseABC) -> None:
    pubsub = pubsub_db.pubsub
    subscription = pubsub.subscribe(["room_42"])
    _settle(pubsub_db)

    pubsub_db.close()

    assert pubsub.closed
    assert subscription.closed
