from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from flowmaticdb.pubsub._abc import DEFAULT_MAX_QUEUED_MESSAGES, PubSubABC
from flowmaticdb.pubsub._message import Message
from flowmaticdb.pubsub._subscription import Subscription
from flowmaticdb.pubsub._table import DEFAULT_TABLE_NAME, create_outbox_table, delete_expired_messages

if TYPE_CHECKING:
    from flowmaticdb.database import DatabaseABC

DEFAULT_POLL_INTERVAL = 0.1

DEFAULT_GRACE_MILLISECONDS = 50

DEFAULT_RETENTION_MILLISECONDS = 300_000

DEFAULT_JANITOR_INTERVAL = 30.0

DEFAULT_BATCH_SIZE = 500


class PollingPubSub(PubSubABC):
    """An outbox table read by a polling thread. The default on MySQL/MariaDB.

    Latency is ``poll_interval / 2 + grace``, so roughly 75-150ms at the
    defaults, and the load is ``processes / poll_interval`` queries per second
    whether or not any message is ever published. Both are why this is not the
    default on PostgreSQL, which pushes instead.

    **The grace window is not optional.** ``id > cursor`` is unsafe under
    concurrent writers on every engine: transaction A takes id 100, B takes 101
    and commits first, and a reader at 99 sees 101, advances past it, and then
    100 becomes visible and is skipped forever. Reading only rows older than
    ``grace_milliseconds`` closes that hole, as long as the window is wider than
    the gap between a publisher taking an id and committing. Publishing is a
    single autocommit insert issued after the caller's own transaction, so that
    gap is around a millisecond and 50ms of grace is ample. Publishing from
    inside a long transaction instead would need the window widened to match.

    Cursors live in memory, not in a table. A starting gateway wants everything
    from now on, not the backlog, so the cursor begins at the current ``MAX(id)``
    and one cursor serves every channel the process subscribes to."""

    def __init__(
        self,
        database: DatabaseABC,
        table: str = DEFAULT_TABLE_NAME,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        grace_milliseconds: int = DEFAULT_GRACE_MILLISECONDS,
        retention_milliseconds: int = DEFAULT_RETENTION_MILLISECONDS,
        run_janitor: bool = True,
        janitor_interval: float = DEFAULT_JANITOR_INTERVAL,
        batch_size: int = DEFAULT_BATCH_SIZE,
        poll_in_background: bool = True,
        max_queued_messages: int = DEFAULT_MAX_QUEUED_MESSAGES,
    ) -> None:
        super().__init__(max_queued_messages)

        self._database = database
        self._table = table
        self._poll_interval = poll_interval
        self._grace_milliseconds = grace_milliseconds
        self._retention_milliseconds = retention_milliseconds
        self._run_janitor = run_janitor
        self._janitor_interval = janitor_interval
        self._batch_size = batch_size
        self._poll_in_background = poll_in_background

        self._cursor = 0
        self._start_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._poller_thread: threading.Thread | None = None
        self._janitor_thread: threading.Thread | None = None
        self._started = False
        self._error_count = 0
        self._last_error: str | None = None
        self._error_lock = threading.Lock()

    @property
    def table(self) -> str:
        return self._table

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def error_count(self) -> int:
        """Polls that raised. The loop keeps going, so this is how a transient
        outage shows up rather than as a crashed thread."""
        with self._error_lock:
            return self._error_count

    @property
    def last_error(self) -> str | None:
        with self._error_lock:
            return self._last_error

    def init(self) -> None:
        """Create the outbox table and its index.

        Explicit, like :meth:`Migrator.init`, rather than implicit on first use."""
        create_outbox_table(self._database, self._table)

    def _publish(self, channel: str, payload: str) -> None:
        self._database.insert(self._table).values({
            "channel": channel,
            "payload": payload,
            "created_at": self._database.dialect.current_timestamp_precise(),
        }).execute()

    def _on_subscribe(self, subscription: Subscription) -> None:
        with self._start_lock:
            if self._started:
                return

            # Reading the cursor here rather than on the poller thread is what
            # makes a missing table surface as an error out of subscribe(), on
            # the caller's own thread, instead of as silence plus a counter.
            self._cursor = self._read_max_id()
            self._started = True

            if self._poll_in_background:
                self._poller_thread = threading.Thread(
                    target=self._run_poller,
                    name="flowmaticdb-pubsub-poller",
                    daemon=True,
                )
                self._poller_thread.start()

            if self._run_janitor:
                self._janitor_thread = threading.Thread(
                    target=self._run_janitor_loop,
                    name="flowmaticdb-pubsub-janitor",
                    daemon=True,
                )
                self._janitor_thread.start()

    def _stop(self) -> None:
        self._stop_event.set()

        for thread in (self._poller_thread, self._janitor_thread):
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=self._poll_interval + 5.0)

        self._poller_thread = None
        self._janitor_thread = None
        self._started = False

    def _read_max_id(self) -> int:
        rows = self._database.select(self._table) \
            .columns(["id"]) \
            .order_by_desc("id") \
            .limit(1) \
            .execute() \
            .fetch_dicts()

        if not rows:
            return 0

        return int(rows[0]["id"])

    def _record_error(self, error: Exception) -> None:
        with self._error_lock:
            self._error_count += 1
            self._last_error = f"{type(error).__name__}: {error}"

    def _run_poller(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as error:  # noqa: BLE001 - a dead poller stops delivery for good
                # The database may be briefly unreachable. Dying here would stop
                # delivery for good, so the loop records and carries on.
                self._record_error(error)

            self._stop_event.wait(self._poll_interval)

    def poll_once(self) -> int:
        """Read one batch and dispatch it. Returns how many messages went out.

        Public because a caller that would rather drive the cadence itself --
        or a test that wants determinism -- needs a way in that does not
        involve waiting on a thread. Pair it with ``poll_in_background=False``,
        or the backend's own thread will be draining the same cursor."""
        cutoff = self._database.dialect.timestamp_minus_milliseconds(self._grace_milliseconds)

        rows = self._database.select(self._table) \
            .columns(["id", "channel", "payload"]) \
            .where_greater_than("id", self._cursor) \
            .where_less_than("created_at", cutoff) \
            .order_by_asc("id") \
            .limit(self._batch_size) \
            .execute() \
            .fetch_dicts()

        for row in rows:
            row_id = int(row["id"])
            self._cursor = row_id
            self._dispatch(Message(str(row["channel"]), str(row["payload"]), row_id))

        return len(rows)

    def _run_janitor_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._janitor_interval)

            if self._stop_event.is_set():
                return

            try:
                self.delete_expired()
            except Exception as error:  # noqa: BLE001 - retention is best-effort, never fatal
                self._record_error(error)

    def delete_expired(self) -> None:
        delete_expired_messages(self._database, self._table, self._retention_milliseconds)
