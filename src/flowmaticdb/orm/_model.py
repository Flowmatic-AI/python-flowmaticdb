from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Self

from pydantic import BaseModel, PrivateAttr

from flowmaticdb.orm._meta import model_meta

if TYPE_CHECKING:
    from flowmaticdb.database import DatabaseABC
    from flowmaticdb.orm._column import ModelColumn
    from flowmaticdb.orm._relation import ModelRelation
    from flowmaticdb.query.ddl import TableDescription


class Model(BaseModel):
    __table__: ClassVar[str] = ""

    _loaded_relations: set[str] = PrivateAttr(default_factory=set)

    @classmethod
    def describe_table(cls, database: DatabaseABC) -> TableDescription:
        return database.describe_table(model_meta(cls).table)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Self:
        values: dict[str, Any] = {}

        for column in model_meta(cls).columns:
            if column.column_name in row:
                values[column.field_name] = row[column.column_name]

        return cls.model_validate(values)

    def column_value(self, column: ModelColumn) -> Any:
        return self.__dict__[column.field_name]

    def set_column_value(self, column: ModelColumn, value: Any) -> None:
        self.__dict__[column.field_name] = value
        self.__pydantic_fields_set__.add(column.field_name)

    def column_values(self) -> dict[str, Any]:
        return {column.column_name: self.__dict__[column.field_name] for column in model_meta(type(self)).columns}

    def key_value(self, column_name: str) -> Any:
        return self.__dict__[model_meta(type(self)).column_by_name(column_name).field_name]

    def primary_key_value(self) -> Any:
        return self.column_value(model_meta(type(self)).primary_key)

    def related_models(self, relation: ModelRelation) -> list[Model]:
        value = self.__dict__[relation.field_name]

        if value is None:
            return []

        if isinstance(value, Model):
            return [value]

        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, Model)]

        return []

    def set_relation(self, relation: ModelRelation, value: Any) -> None:
        self.__dict__[relation.field_name] = value
        self.__pydantic_fields_set__.add(relation.field_name)
        self._loaded_relations.add(relation.field_name)

    def is_relation_loaded(self, field_name: str) -> bool:
        return field_name in self._loaded_relations
