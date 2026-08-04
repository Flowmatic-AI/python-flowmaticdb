from __future__ import annotations

from dataclasses import dataclass

from flowmaticdb.query.ddl._constraint import ConstraintABC


@dataclass
class RawConstraint(ConstraintABC):
    sql: str
