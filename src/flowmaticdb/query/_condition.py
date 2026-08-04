from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flowmaticdb.query.enums import ChainEnum, ConditionEnum


@dataclass
class Condition:
    condition: ConditionEnum | str
    identifier: str | list[str] | None = None
    value: Any = None
    chain: ChainEnum = ChainEnum.AND
    cast: bool = False
    case_insensitive: bool = False
    flags: str | None = None
