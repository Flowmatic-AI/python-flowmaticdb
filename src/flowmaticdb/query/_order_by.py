from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from flowmaticdb.query.enums import OrderByDirectionEnum

if TYPE_CHECKING:
    from flowmaticdb.query.expressions import SqlABC


@dataclass
class OrderBy:
    column: str | list[str] | SqlABC
    direction: OrderByDirectionEnum = OrderByDirectionEnum.ASC
