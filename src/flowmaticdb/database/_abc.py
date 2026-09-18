from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self, TypeVar

from flowmaticdb._threading import ThreadLocalStore
from flowmaticdb.result import ResultABC

T = TypeVar("T")
ModelT = TypeVar("ModelT", bound="Model")

if TYPE_CHECKING:
    from flowmaticdb import QueryWithParams
    from flowmaticdb.adapters import AdapterABC
    from flowmaticdb.database._table import Table
    from flowmaticdb.dialects import DialectABC
    from flowmaticdb.orm import (
        DeleteModelQuery,
        InsertModelQuery,
        Model,
        SelectModelQuery,
        UpdateModelQuery,
    )
    from flowmaticdb.pubsub import PubSubABC, PubSubBackendEnum
    from flowmaticdb.query import (
        AlterTableQuery,
        CreateIndexQuery,
        CreateTableQuery,
        DeleteQuery,
        DropIndexQuery,
        DropTableQuery,
        InsertQuery,
        SelectQuery,
        UpdateQuery,
    )
    from flowmaticdb.query.ddl import TableDescription
    from flowmaticdb.query.expressions import Alias, SubQuery


class DatabaseABC:
    def __init__(self, adapter: AdapterABC, dialect: DialectABC, ensure_always_connected: bool = False) -> None:
        self._adapter = adapter
        self._dialect = dialect
        self._ensure_always_connected = ensure_always_connected
        self._savepoint_stacks: ThreadLocalStore[list[str]] = ThreadLocalStore()
        self._pubsub: PubSubABC | None = None
        self._pubsub_lock = threading.Lock()

    @property
    def _savepoints(self) -> list[str]:
        stack = self._savepoint_stacks.current()
        if stack is None:
            stack = []
            self._savepoint_stacks.set(stack)
        return stack

    @property
    def adapter(self) -> AdapterABC:
        return self._adapter

    @property
    def dialect(self) -> DialectABC:
        return self._dialect

    @property
    def ensure_always_connected(self) -> bool:
        return self._ensure_always_connected

    def exec(self, query: str) -> None:
        if self._ensure_always_connected:
            self.reconnect_if_disconnected()

        return self._adapter.exec(query)

    def query(self, query: str) -> ResultABC:
        if self._ensure_always_connected:
            self.reconnect_if_disconnected()

        return self._adapter.query(query)

    def prepared(self, query: str, params: list[Any] | None = None, emulate: bool = False) -> ResultABC:
        from flowmaticdb._query_with_params import QueryWithParams
        qwp = QueryWithParams(query=query, params=params or [])
        return self.query_with_params(qwp, emulate)

    def query_with_params(self, qwp: QueryWithParams, emulate: bool = False) -> ResultABC:
        if self._ensure_always_connected:
            self.reconnect_if_disconnected()

        if len(qwp.params) > 0:
            return self._adapter.query_with_params(self._dialect, qwp, emulate)
        return self._adapter.query(qwp.query)

    def begin_transaction(self, name: str | None = None) -> None:
        if not self.in_transaction:
            qwp = self._dialect.begin_transaction(name)
            self._adapter.begin_transaction(qwp.query)
            return

        name = name or f"savepoint_{len(self._savepoints) + 1}"
        self._savepoints.append(name)
        qwp = self._dialect.begin_savepoint(name)
        self._adapter.begin_savepoint(qwp.query)

    def commit_transaction(self, release_savepoints: bool = False, name: str | None = None) -> None:
        if not self.in_transaction:
            return

        if release_savepoints or len(self._savepoints) == 0:
            self._savepoints.clear()
            qwp = self._dialect.commit_transaction(name)
            self._adapter.commit_transaction(qwp.query)
            return

        qwp = self._dialect.commit_savepoint(self._savepoints.pop())
        self._adapter.commit_savepoint(qwp.query)

    def rollback_transaction(self, release_savepoints: bool = False, name: str | None = None) -> None:
        if not self.in_transaction:
            return

        if release_savepoints or len(self._savepoints) == 0:
            self._savepoints.clear()
            qwp = self._dialect.rollback_transaction(name)
            self._adapter.rollback_transaction(qwp.query)
            return

        qwp = self._dialect.rollback_savepoint(self._savepoints.pop())
        self._adapter.rollback_savepoint(qwp.query)

    @property
    def in_transaction(self) -> bool:
        return self._adapter.in_transaction

    def transaction(self, callback: Callable[[Self], T], release_savepoints: bool = False, name: str | None = None) -> T:
        self.begin_transaction(name=name)
        try:
            result = callback(self)
            self.commit_transaction(release_savepoints=release_savepoints, name=name)
            return result
        except Exception:
            self.rollback_transaction(release_savepoints=release_savepoints, name=name)
            raise

    def last_insert_id(self, name: str | None = None) -> int | str | None:
        return self._adapter.last_insert_id(name)

    def select(self, table: str | list[str] | Alias | SubQuery) -> SelectQuery:
        from flowmaticdb.query import SelectQuery
        return SelectQuery(self._dialect, table, database=self)

    def select_table(self, table: str | list[str], alias: str | None = None) -> SelectQuery:
        if alias:
            from flowmaticdb.query.expressions import Alias
            return self.select(Alias(table, alias))

        return self.select(table)

    def select_sub_query(self, sub_query: Any, alias: str) -> SelectQuery:
        from flowmaticdb.query.expressions import SubQuery
        return self.select(SubQuery(sub_query, alias))

    def select_models(self, model: type[ModelT]) -> SelectModelQuery[ModelT]:
        from flowmaticdb.orm import SelectModelQuery
        return SelectModelQuery(self._dialect, self, model)

    def insert_models(self, models: list[ModelT]) -> InsertModelQuery[ModelT]:
        from flowmaticdb.orm import InsertModelQuery
        return InsertModelQuery(self._dialect, self, models)

    def insert_model(self, model: ModelT) -> InsertModelQuery[ModelT]:
        return self.insert_models([model])

    def update_models(self, models: list[ModelT]) -> UpdateModelQuery[ModelT]:
        from flowmaticdb.orm import UpdateModelQuery
        return UpdateModelQuery(self._dialect, self, models)

    def update_model(self, model: ModelT) -> UpdateModelQuery[ModelT]:
        return self.update_models([model])

    def delete_models(self, models: list[ModelT]) -> DeleteModelQuery[ModelT]:
        from flowmaticdb.orm import DeleteModelQuery
        return DeleteModelQuery(self._dialect, self, models)

    def delete_model(self, model: ModelT) -> DeleteModelQuery[ModelT]:
        return self.delete_models([model])

    def insert(self, table: str | list[str]) -> InsertQuery:
        from flowmaticdb.query import InsertQuery
        return InsertQuery(self._dialect, table, database=self)

    def update(self, table: str | list[str]) -> UpdateQuery:
        from flowmaticdb.query import UpdateQuery
        return UpdateQuery(self._dialect, table, database=self)

    def delete(self, table: str | list[str]) -> DeleteQuery:
        from flowmaticdb.query import DeleteQuery
        return DeleteQuery(self._dialect, table, database=self)

    def create_table(self, table: str | list[str]) -> CreateTableQuery:
        from flowmaticdb.query import CreateTableQuery
        return CreateTableQuery(self._dialect, table, database=self)

    def alter_table(self, table: str | list[str]) -> AlterTableQuery:
        from flowmaticdb.query import AlterTableQuery
        return AlterTableQuery(self._dialect, table, database=self)

    def drop_table(self, table: str | list[str]) -> DropTableQuery:
        from flowmaticdb.query import DropTableQuery
        return DropTableQuery(self._dialect, table, database=self)

    def create_index(self, table: str | list[str], name: str) -> CreateIndexQuery:
        from flowmaticdb.query import CreateIndexQuery
        return CreateIndexQuery(self._dialect, table, database=self, name=name)

    def drop_index(self, table: str | list[str], name: str) -> DropIndexQuery:
        from flowmaticdb.query import DropIndexQuery
        return DropIndexQuery(self._dialect, table, database=self, name=name)

    def list_tables(self, schema: str = "public") -> list[str]:
        return self.query_with_params(self._dialect.list_tables(schema)).scalars()

    def describe_table(self, table: str | list[str]) -> TableDescription:
        from flowmaticdb.database._introspection import describe_table
        return describe_table(self, self._dialect, table)

    def table(self, table: str | list[str]) -> Table:
        from flowmaticdb.database._table import Table
        return Table(self, self._dialect, table)

    @property
    def pubsub(self) -> PubSubABC:
        """Publish/subscribe over this database, built once and cached.

        A property rather than a method on purpose. Returning a fresh instance
        per call would invite two unconnected brokers in one process --
        ``db.pubsub().publish(...)`` into one and ``db.pubsub().subscribe(...)``
        on another, with no error and no delivery. PubSub owns threads, a
        connection and a subscription registry and has to be closed, which makes
        it a collaborator of the database like ``adapter`` and ``dialect``, not a
        builder like ``select()``.

        Building is cheap: no thread starts and no connection opens until the
        first :meth:`subscribe`. On the polling backend the outbox table still
        has to be created explicitly with ``init()``, as migrations are."""
        if self._pubsub is not None:
            return self._pubsub

        # Connections here are thread-local, so two request threads touching
        # this for the first time at once is ordinary rather than exotic --
        # unguarded, it would build two instances and cause the very split this
        # property exists to prevent.
        with self._pubsub_lock:
            if self._pubsub is None:
                self._pubsub = self._create_pubsub()

            return self._pubsub

    def _create_pubsub(self) -> PubSubABC:
        from flowmaticdb.pubsub import MemoryPubSub, PollingPubSub, PostgresPubSub, PubSubBackendEnum

        backend = self._pubsub_backend()
        max_queued_messages = int(self._dialect.option("pubsub_max_queued_messages", 1000))

        if backend is PubSubBackendEnum.POSTGRES:
            return PostgresPubSub(
                self,
                reconnect_interval=float(self._dialect.option("pubsub_reconnect_interval", 1.0)),
                max_queued_messages=max_queued_messages,
            )

        if backend is PubSubBackendEnum.MEMORY:
            return MemoryPubSub(max_queued_messages=max_queued_messages)

        return PollingPubSub(
            self,
            table=str(self._dialect.option("pubsub_table", "pubsub_messages")),
            poll_interval=float(self._dialect.option("pubsub_poll_interval", 0.1)),
            grace_milliseconds=int(self._dialect.option("pubsub_grace_milliseconds", 50)),
            retention_milliseconds=int(self._dialect.option("pubsub_retention_milliseconds", 300_000)),
            run_janitor=bool(self._dialect.option("pubsub_run_janitor", True)),
            janitor_interval=float(self._dialect.option("pubsub_janitor_interval", 30.0)),
            max_queued_messages=max_queued_messages,
        )

    def _pubsub_backend(self) -> PubSubBackendEnum:
        """The configured backend, or the one this dialect implies."""
        from flowmaticdb import PubSubError
        from flowmaticdb.dialects import PostgresqlDialect, SQLiteDialect
        from flowmaticdb.pubsub import PubSubBackendEnum

        configured = self._dialect.option("pubsub_backend")

        if configured is not None:
            try:
                return PubSubBackendEnum(configured)
            except ValueError:
                # A misspelled backend has to be refused here. Falling back to
                # the default would hand back a working object that delivers
                # somewhere other than where it was asked to.
                valid = ", ".join(member.value for member in PubSubBackendEnum)
                raise PubSubError(f"unknown pubsub_backend {configured!r}; valid values are {valid}") from None

        if isinstance(self._dialect, PostgresqlDialect):
            return PubSubBackendEnum.POSTGRES

        if isinstance(self._dialect, SQLiteDialect):
            return PubSubBackendEnum.MEMORY

        # MySQL/MariaDB, and any dialect this library has never seen: polling is
        # the only mechanism that works between processes without native push,
        # and it fails loudly rather than quietly when a dialect cannot express
        # its SQL. A custom dialect that wants the in-process broker instead
        # asks for it by name.
        return PubSubBackendEnum.POLLING

    def copy_from(self, source: DatabaseABC, include_data: bool = True, row_batch_size: int = 100) -> int:
        """Copy every table from source into this database."""
        from flowmaticdb.database._copy import copy_database
        return copy_database(source, self, include_data, row_batch_size)

    def copy_to(self, destination: DatabaseABC, include_data: bool = True, row_batch_size: int = 100) -> int:
        """Copy every table from this database into destination."""
        from flowmaticdb.database._copy import copy_database
        return copy_database(self, destination, include_data, row_batch_size)

    def close(self) -> None:
        # Threads and a dedicated listener connection outliving the database
        # that owns them is exactly the leak the pubsub property's ownership
        # claim obliges this to handle.
        with self._pubsub_lock:
            pubsub = self._pubsub
            self._pubsub = None

        if pubsub is not None:
            pubsub.close()

        self.adapter.close()
    
    def is_connected(self) -> bool:
        return self.adapter.is_connected()

    def reconnect(self) -> None:
        self._savepoints.clear()
        self.adapter.reconnect()

    def reconnect_if_disconnected(self) -> bool:
        if self.adapter.is_connected():
            return False

        self.reconnect()
        return True

    def get_connection(self) -> Any:
        return self.adapter.get_connection()
