from __future__ import annotations

from dataclasses import dataclass

from flowmaticdb.query.ddl._constraint import ConstraintABC


@dataclass
class ForeignKeyConstraint(ConstraintABC):
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    name: str | None = None
    on_delete: str | None = None
    on_update: str | None = None
