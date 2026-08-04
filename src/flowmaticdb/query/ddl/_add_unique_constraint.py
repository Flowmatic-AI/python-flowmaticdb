from __future__ import annotations

from dataclasses import dataclass

from flowmaticdb.query.ddl._alter import AlterABC
from flowmaticdb.query.ddl._unique_constraint import UniqueConstraint


@dataclass
class AddUniqueConstraint(UniqueConstraint, AlterABC):
    pass
