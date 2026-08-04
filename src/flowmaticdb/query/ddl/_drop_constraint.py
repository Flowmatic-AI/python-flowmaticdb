from __future__ import annotations

from dataclasses import dataclass

from flowmaticdb.query.ddl._alter import AlterABC


@dataclass
class DropConstraint(AlterABC):
    name: str
