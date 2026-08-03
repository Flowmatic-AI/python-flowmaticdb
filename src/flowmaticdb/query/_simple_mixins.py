from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from flowmaticdb.query._on_conflict import OnConflict
from flowmaticdb.query._order_by import OrderBy
from flowmaticdb.query._union import Union
from flowmaticdb.query.enums._order_by_dir import OrderByDirectionEnum

if TYPE_CHECKING:
    from flowmaticdb.query._select import SelectQuery


class ColumnsMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._columns_list: list[Any] | None = None

    def columns(self, cols: list[Any]) -> Self:
        self._columns_list = cols
        return self

class DistinctMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._distinct: list[Any] | None = None

    def distinct(self, on: list[Any] | None = None) -> Self:
        self._distinct = on if on is not None else []
        return self

class GroupByMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._group_by_cols: list[Any] | None = None

    def group_by(self, columns: list[Any]) -> Self:
        self._group_by_cols = columns
        return self

class OrderByMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._order_by_list: list[OrderBy] | None = None

    def order_by_asc(self, column: str) -> Self:
        if self._order_by_list is None:
            self._order_by_list = []
        self._order_by_list.append(OrderBy(column=column, direction=OrderByDirectionEnum.ASC))
        return self

    def order_by_desc(self, column: str) -> Self:
        if self._order_by_list is None:
            self._order_by_list = []
        self._order_by_list.append(OrderBy(column=column, direction=OrderByDirectionEnum.DESC))
        return self

class LimitMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._limit_val: int | None = None

    def limit(self, limit: int) -> Self:
        self._limit_val = limit
        return self

class OffsetMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._offset_val: int | None = None

    def offset(self, offset: int) -> Self:
        self._offset_val = offset
        return self

class UnionMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._unions_list: list[Union] | None = None

    def union(self, select_query: SelectQuery) -> Self:
        from flowmaticdb.query.enums._union import UnionEnum
        if self._unions_list is None:
            self._unions_list = []
        self._unions_list.append(Union(union=UnionEnum.UNION, select_query=select_query))
        return self

    def union_all(self, select_query: SelectQuery) -> Self:
        from flowmaticdb.query.enums._union import UnionEnum
        if self._unions_list is None:
            self._unions_list = []
        self._unions_list.append(Union(union=UnionEnum.UNION_ALL, select_query=select_query))
        return self

class ValuesMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._values_list: list[dict[str, Any]] = []

    def values(self, *dicts: dict[str, Any]) -> Self:
        self._values_list.extend(dicts)
        return self

class UpdatesMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._updates_dict: dict[str, Any] = {}

    def updates(self, updates: dict[str, Any]) -> Self:
        self._updates_dict.update(updates)
        return self

class ReturningMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._returning_list: list[Any] | None = None

    def returning(self, columns: list[Any]) -> Self:
        self._returning_list = columns
        return self

class OnConflictMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._on_conflict: OnConflict | None = None

    def on_conflict_do_nothing(self, conflict: str | list[str]) -> Self:
        self._on_conflict = OnConflict(conflict=conflict, updates=None)
        return self

    def on_conflict_do_update(self, conflict: str | list[str], updates: dict[str, Any]) -> Self:
        self._on_conflict = OnConflict(conflict=conflict, updates=updates)
        return self

class LastInsertIdMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_insert_id_col: str | None = None

    def last_insert_id(self, column: str) -> Self:
        self._last_insert_id_col = column
        return self