from __future__ import annotations

from typing import Any, ClassVar, Self

from pydantic import BaseModel, PrivateAttr

from flowmaticdb import ModelError
from flowmaticdb.orm._column import ModelColumn
from flowmaticdb.orm._meta import ModelMeta, model_meta
from flowmaticdb.orm._relation import ModelRelation


class Model(BaseModel):
    __table__: ClassVar[str] = ""

    _loaded_relations: set[str] = PrivateAttr(default_factory=set)

    @classmethod
    def orm_meta(cls) -> ModelMeta:
        return model_meta(cls)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Self:
        meta = cls.orm_meta()
        values: dict[str, Any] = {}

        for column in meta.columns:
            if column.column_name in row:
                values[column.field_name] = row[column.column_name]

        return cls.model_validate(values)

    def column_value(self, column: ModelColumn) -> Any:
        return self.__dict__[column.field_name]

    def set_column_value(self, column: ModelColumn, value: Any) -> None:
        self.__dict__[column.field_name] = value
        self.__pydantic_fields_set__.add(column.field_name)

    def column_values(self) -> dict[str, Any]:
        return {column.column_name: self.__dict__[column.field_name] for column in self.orm_meta().columns}

    def key_value(self, column_name: str) -> Any:
        return self.__dict__[self.orm_meta().column_by_name(column_name).field_name]

    def primary_key_value(self) -> Any:
        return self.column_value(self.orm_meta().primary_key)

    def require_primary_key_value(self) -> Any:
        value = self.primary_key_value()

        if value is None:
            raise ModelError(
                f"{type(self).__name__} has no {self.orm_meta().primary_key.column_name} value: it has to be "
                "inserted before it can be referenced, updated or deleted"
            )

        return value

    def relation_value(self, relation: ModelRelation) -> Any:
        return self.__dict__[relation.field_name]

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
