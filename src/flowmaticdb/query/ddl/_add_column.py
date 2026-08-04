from __future__ import annotations

from dataclasses import dataclass

from flowmaticdb.query.ddl._alter import AlterABC
from flowmaticdb.query.ddl._column import Column


@dataclass
class AddColumn(Column, AlterABC):
    pass
