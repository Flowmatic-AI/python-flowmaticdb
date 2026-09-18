from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flowmaticdb.database import DatabaseABC

DEFAULT_TABLE_NAME = "pubsub_messages"


def create_outbox_table(database: DatabaseABC, table: str) -> None:
    """Create the outbox and the one index it needs.

    There is deliberately no index on ``channel``. A gateway holding thousands
    of rooms cannot afford a query per channel, so it polls ``id > ?`` for
    everything on the primary key and routes in memory -- one query per interval
    regardless of how many channels are live. The ``created_at`` index is for
    the retention delete, which is the only thing that filters on it."""
    database.create_table(table) \
        .if_not_exists() \
        .identity("id") \
        .string("channel", size=63, not_null=True) \
        .text("payload", not_null=True) \
        .datetime("created_at", not_null=True) \
        .execute()

    index_name = f"{table}_created_at"

    # MySQL has no CREATE INDEX IF NOT EXISTS, and asking for one there raises,
    # so on those dialects existence is checked instead -- init() is documented
    # as idempotent and a second call must not fail.
    if database.dialect.index_if_not_exists:
        database.create_index(table, index_name).if_not_exists().columns(["created_at"]).execute()
        return

    if any(index.name == index_name for index in database.describe_table(table).indexes):
        return

    database.create_index(table, index_name).columns(["created_at"]).execute()


def drop_outbox_table(database: DatabaseABC, table: str) -> None:
    database.drop_table(table).if_exists().execute()


def delete_expired_messages(database: DatabaseABC, table: str, retention_milliseconds: int) -> None:
    cutoff = database.dialect.timestamp_minus_milliseconds(retention_milliseconds)
    database.delete(table).where_less_than("created_at", cutoff).execute()
