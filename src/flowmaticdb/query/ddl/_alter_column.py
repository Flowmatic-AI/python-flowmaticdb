from __future__ import annotations

from dataclasses import dataclass

from flowmaticdb.query.ddl._alter import AlterABC


@dataclass
class AlterColumn(AlterABC):
    column: str
    sql: str
