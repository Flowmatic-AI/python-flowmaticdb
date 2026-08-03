from __future__ import annotations

from dataclasses import dataclass

from flowmaticdb.query.enums._order_by_dir import OrderByDirectionEnum


@dataclass
class OrderBy:
    column: str
    direction: OrderByDirectionEnum = OrderByDirectionEnum.ASC
