from __future__ import annotations

from flowmaticdb.query import Join
from flowmaticdb.query.enums import ChainEnum, JoinEnum


def test_join_creation() -> None:
    j = Join(join=JoinEnum.LEFT_JOIN, table="posts")
    assert j.join == JoinEnum.LEFT_JOIN
    assert j.table == "posts"
    assert j.conditions == []


def test_join_on_condition() -> None:
    j = Join(join=JoinEnum.INNER_JOIN, table="posts")
    j.on("users.id", "posts.user_id")
    assert len(j.conditions) == 1
    assert j.conditions[0].chain == ChainEnum.AND


def test_join_or_on_condition() -> None:
    j = Join(join=JoinEnum.LEFT_JOIN, table="posts")
    j.or_on("a", "b")
    assert j.conditions[0].chain == ChainEnum.OR


def test_multiple_join_conditions() -> None:
    j = Join(join=JoinEnum.LEFT_JOIN, table="posts")
    j.on("users.id", "posts.user_id")
    j.on("users.deleted", 0)
    assert len(j.conditions) == 2


def test_all_join_types() -> None:
    for join_type in JoinEnum:
        j = Join(join=join_type, table="t")
        assert j.join == join_type
