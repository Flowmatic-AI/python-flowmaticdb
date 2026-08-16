from __future__ import annotations

from dataclasses import dataclass, field

from flowmaticdb.query.ddl._column import Column
from flowmaticdb.query.ddl._foreign_key_constraint import ForeignKeyConstraint
from flowmaticdb.query.ddl._unique_constraint import UniqueConstraint


@dataclass
class TableConstraints:
    unique: list[UniqueConstraint] = field(default_factory=list)
    foreign_keys: list[ForeignKeyConstraint] = field(default_factory=list)


@dataclass
class TableDescription:
    columns: list[Column] = field(default_factory=list)
    constraints: TableConstraints = field(default_factory=TableConstraints)
