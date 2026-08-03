from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from flowmaticdb.query._condition import Condition
from flowmaticdb.query._condition_group import ConditionGroupABC, WhereGroup
from flowmaticdb.query.enums._chain import ChainEnum
from flowmaticdb.query.enums._condition import ConditionEnum

if TYPE_CHECKING:
    from flowmaticdb.query._select import SelectQuery


def _escape_like_chars(string: str, escape_backslash: bool = False) -> str:
    result = string.replace("%", "\\%").replace("_", "\\_")
    if escape_backslash:
        result = result.replace("\\", "\\\\")
    return result

class ConditionMixin:
    def _equals(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, cast: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.EQUALS, column, value, chain, cast=cast)

    def _not_equals(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, cast: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_EQUALS, column, value, chain, cast=cast)

    def _is_null(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.EQUALS, column, None, chain)

    def _is_not_null(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_EQUALS, column, None, chain)

    def _like(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, case_insensitive: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.LIKE, column, value, chain)

    def _not_like(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, case_insensitive: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_LIKE, column, value, chain)

    def _starts_with(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, case_insensitive: bool = False, escape_backslash: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        val = _escape_like_chars(str(value), escape_backslash)
        return self._add_condition(conditions, ConditionEnum.LIKE, column, f"{val}%", chain)

    def _ends_with(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, case_insensitive: bool = False, escape_backslash: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        val = _escape_like_chars(str(value), escape_backslash)
        return self._add_condition(conditions, ConditionEnum.LIKE, column, f"%{val}", chain)

    def _contains(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, case_insensitive: bool = False, escape_backslash: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        val = _escape_like_chars(str(value), escape_backslash)
        return self._add_condition(conditions, ConditionEnum.LIKE, column, f"%{val}%", chain)

    def _not_contains(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, case_insensitive: bool = False, escape_backslash: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        val = _escape_like_chars(str(value), escape_backslash)
        return self._add_condition(conditions, ConditionEnum.NOT_LIKE, column, f"%{val}%", chain)

    def _glob(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, case_insensitive: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.GLOB, column, value, chain)

    def _not_glob(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, case_insensitive: bool = False, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_GLOB, column, value, chain)

    def _in(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, values: list[Any], chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.IN, column, values, chain)

    def _not_in(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, values: list[Any], chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_IN, column, values, chain)

    def _less_than(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.LESS_THAN, column, value, chain)

    def _less_than_or_equals(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.LESS_THAN_OR_EQUALS, column, value, chain)

    def _greater_than(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.GREATER_THAN, column, value, chain)

    def _greater_than_or_equals(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, value: Any, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.GREATER_THAN_OR_EQUALS, column, value, chain)

    def _between(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, min_val: Any, max_val: Any, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.BETWEEN, column, [min_val, max_val], chain)

    def _not_between(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, min_val: Any, max_val: Any, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_BETWEEN, column, [min_val, max_val], chain)

    def _empty(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.EQUALS, column, "", chain)

    def _not_empty(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_EQUALS, column, "", chain)

    def _regex(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, pattern: Any, flags: Any = None, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.REGEX, column, pattern, chain)

    def _not_regex(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, pattern: Any, flags: Any = None, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_REGEX, column, pattern, chain)

    def _exists(self, conditions: list[Condition | ConditionGroupABC], select_query: SelectQuery, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.EXISTS, None, select_query, chain)

    def _not_exists(self, conditions: list[Condition | ConditionGroupABC], select_query: SelectQuery, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, ConditionEnum.NOT_EXISTS, None, select_query, chain)

    def _group(self, conditions: list[Condition | ConditionGroupABC], callback: Callable[..., Any], not_: bool = False, group_class: type[ConditionGroupABC] | None = None, chain: ChainEnum = ChainEnum.AND) -> ConditionGroupABC:
        if group_class is None:
            group_class = WhereGroup
        group = group_class(chain=chain, not_=not_)  # type: ignore[call-arg]
        result = callback(group)
        if result is not None:
            group = result
        self._add_condition_group(conditions, group)
        return group

    def _operator(self, conditions: list[Condition | ConditionGroupABC], column: str | list[str] | None, operator: str, value: Any, chain: ChainEnum = ChainEnum.AND) -> Condition:
        return self._add_condition(conditions, operator, column, value, chain)

    def _add_condition(self, conditions: list[Condition | ConditionGroupABC], condition: Any, identifier: str | list[str] | None, value: Any, chain: ChainEnum = ChainEnum.AND, cast: bool = False) -> Condition:
        cond = Condition(condition=condition, identifier=identifier, value=value, chain=chain, cast=cast)
        conditions.append(cond)
        return cond

    def _add_condition_group(self, conditions: list[Condition | ConditionGroupABC], group: Any) -> None:
        conditions.append(group)

    def _add_raw_condition(self, conditions: list[Condition | ConditionGroupABC], sql: str, values: list[Any] | None = None, chain: ChainEnum = ChainEnum.AND) -> Condition:
        from flowmaticdb.query.expressions._expression import Expression
        if values:
            cond = Condition(condition=ConditionEnum.RAW, identifier=None, value=Expression(sql, values), chain=chain)
        else:
            from flowmaticdb.query.expressions._raw import Raw
            cond = Condition(condition=ConditionEnum.RAW, identifier=None, value=Raw(sql), chain=chain)
        conditions.append(cond)
        return cond


