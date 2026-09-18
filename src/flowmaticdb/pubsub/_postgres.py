from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from flowmaticdb import PubSubError
from flowmaticdb.pubsub._abc import DEFAULT_MAX_QUEUED_MESSAGES, PubSubABC
from flowmaticdb.pubsub._message import Message
from flowmaticdb.pubsub._subscription import Subscription

if TYPE_CHECKING:
    from flowmaticdb.adapters import AsyncpgAdapter, PsycopgAdapter
    from flowmaticdb.database import DatabaseABC

DEFAULT_RECONNECT_INTERVAL = 1.0


class PostgresPubSub(PubSubABC):
    """Native ``LISTEN``/``NOTIFY``. The default on PostgreSQL.

    Sub-millisecond, with no table and no polling load. ``NOTIFY``'s two
    weaknesses do not apply to this use: it has no durability, and it drops
    messages when nobody is listening -- but a gateway with no listeners has no
    clients to deliver to, and a reconnecting client resyncs anyway.

    Publishing goes through ``pg_notify(?, ?)`` rather than ``NOTIFY channel,
    'payload'``. The function takes the channel as a *value*, which sidesteps
    identifier quoting and payload escaping entirely.

    Listening needs its own connection. Connections in this library are
    thread-local and die with the thread that opened them, so a listener that
    borrowed one would go silent the moment that thread exited. The adapter
    hands out a dedicated one instead, and this class owns and closes it."""

    def __init__(
        self,
        database: DatabaseABC,
        reconnect_interval: float = DEFAULT_RECONNECT_INTERVAL,
        max_queued_messages: int = DEFAULT_MAX_QUEUED_MESSAGES,
    ) -> None:
        super().__init__(max_queued_messages)

        self._database = database
        self._reconnect_interval = reconnect_interval
        self._start_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._listener_thread: threading.Thread | None = None
        self._listening: set[str] = set()
        self._error_count = 0
        self._last_error: str | None = None
        self._error_lock = threading.Lock()

    @property
    def error_count(self) -> int:
        with self._error_lock:
            return self._error_count

    @property
    def last_error(self) -> str | None:
        with self._error_lock:
            return self._last_error

    def _record_error(self, error: Exception) -> None:
        with self._error_lock:
            self._error_count += 1
            self._last_error = f"{type(error).__name__}: {error}"

    def _publish(self, channel: str, payload: str) -> None:
        self._database.prepared("SELECT pg_notify(?, ?)", [channel, payload]).fetch_dict()

    def _on_subscribe(self, subscription: Subscription) -> None:
        with self._start_lock:
            if self._listener_thread is None:
                self._listener_thread = threading.Thread(
                    target=self._run_listener,
                    name="flowmaticdb-pubsub-listener",
                    daemon=True,
                )
                self._listener_thread.start()

    def _stop(self) -> None:
        self._stop_event.set()

        thread = self._listener_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=self._reconnect_interval + 5.0)

        self._listener_thread = None

    def _run_listener(self) -> None:
        """Keep a listening connection up until close.

        Every reconnect is a gap -- whatever was published while the connection
        was down is gone, because NOTIFY does not queue for absent listeners.
        That is why it is counted on each subscription rather than swallowed:
        a gateway watching ``reconnect_count`` is what lets clients be told to
        resync."""
        first_attempt = True

        while not self._stop_event.is_set():
            try:
                if not first_attempt:
                    self._dispatch_reconnect()

                first_attempt = False
                self._listen_until_closed()
            except Exception as error:  # noqa: BLE001 - reconnecting is the whole point of this loop
                self._record_error(error)

            if not self._stop_event.is_set():
                self._stop_event.wait(self._reconnect_interval)

    def _listen_until_closed(self) -> None:
        from flowmaticdb.adapters import AsyncpgAdapter, PsycopgAdapter

        adapter = self._database.adapter

        # isinstance rather than a capability probe: getattr-based sniffing is
        # out, and a listener connection is not something every adapter can be
        # asked for -- only these two know how to open one.
        if isinstance(adapter, AsyncpgAdapter):
            self._listen_asyncpg(adapter)
        elif isinstance(adapter, PsycopgAdapter):
            self._listen_psycopg(adapter)
        else:
            raise PubSubError(
                f"{type(adapter).__name__} cannot open a listener connection; "
                "PostgresPubSub needs AsyncpgAdapter or PsycopgAdapter"
            )

    def _channels_to_listen(self) -> list[str]:
        return sorted(self._subscribed_channels())

    def _listen_psycopg(self, adapter: PsycopgAdapter) -> None:
        connection = adapter.open_listener_connection()

        try:
            channels = self._channels_to_listen()

            for channel in channels:
                # Channels are validated against [a-z0-9_]{1,63} long before
                # they reach here, so this identifier cannot carry a quote.
                connection.execute(f'LISTEN "{channel}"')

            self._listening = set(channels)

            while not self._stop_event.is_set():
                # The generator ends when the timeout elapses, which is what
                # gives this loop a chance to notice a close or a new channel.
                for notify in connection.notifies(timeout=self._reconnect_interval):
                    self._dispatch(Message(notify.channel, notify.payload, None))

                    if self._stop_event.is_set():
                        return

                if connection.closed:
                    raise PubSubError("the listener connection was closed")

                if self._channels_to_listen() != sorted(self._listening):
                    return
        finally:
            self._listening = set()
            connection.close()

    def _listen_asyncpg(self, adapter: AsyncpgAdapter) -> None:
        connection = adapter.open_listener_connection()

        def on_notify(_connection: Any, _pid: int, channel: str, payload: str) -> None:
            # Fires on the adapter's own loop thread.
            self._dispatch(Message(channel, payload, None))

        try:
            channels = self._channels_to_listen()

            for channel in channels:
                adapter.run_on_loop(connection.add_listener(channel, on_notify))

            self._listening = set(channels)

            while not self._stop_event.is_set():
                self._stop_event.wait(self._reconnect_interval)

                if connection.is_closed():
                    raise PubSubError("the listener connection was closed")

                if self._channels_to_listen() != sorted(self._listening):
                    return
        finally:
            self._listening = set()
            adapter.close_listener_connection(connection)
