from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flowmaticdb.query.ddl._alter import AlterABC
from flowmaticdb.query.enums import TypeEnum


@dataclass
class AlterColumn(AlterABC):
    column: str
    sql: str | None = None
    type: TypeEnum | str | None = None
    bits: int | None = None
    default: Any = None
    not_null: bool | None = None
    drop_default: bool = False
