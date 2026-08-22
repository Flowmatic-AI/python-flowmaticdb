from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic, Self, TypeVar

from flowmaticdb import ModelError
from flowmaticdb.orm._mapper import model_mapper
from flowmaticdb.orm._model import Model
from flowmaticdb.orm._tree import RelationTree
from flowmaticdb.orm.enums import RelationEnum

if TYPE_CHECKING:
    from flowmaticdb.database import DatabaseABC
    from flowmaticdb.dialects import DialectABC
    from flowmaticdb.orm._column import ModelColumn
    from flowmaticdb.orm._mapper import ModelMapper
    from flowmaticdb.orm._meta import ModelMeta
    from flowmaticdb.orm._relation import ModelRelation
    from flowmaticdb.orm._tree import RelationNode
    from flowmaticdb.result import ResultABC


ModelT = TypeVar("ModelT", bound=Model)


class InsertModelQuery(Generic[ModelT]):
    def __init__(self, dialect: DialectABC, database: DatabaseABC, models: list[ModelT]) -> None:
        self._dialect = dialect
        self._database = database
        self._models = models
        self._fill_primary_keys = True

        model_class: type[Model] | None = None

        for model in models:
            if model_class is None:
                model_class = type(model)
            elif type(model) is not model_class:
                raise ModelError(
                    f"insert_models requires models of the same class, got {model_class.__name__} and "
                    f"{type(model).__name__}"
                )

        self._tree: RelationTree | None = RelationTree(model_class) if model_class is not None else None

    def relation(self, path: str) -> Self:
        if self._tree is not None:
            self._tree.add(path)

        return self

    def fill_primary_keys(self, enabled: bool = True) -> Self:
        self._fill_primary_keys = enabled

        return self

    def execute(self, emulate_prepare: bool = False) -> list[ModelT]:
        if len(self._models) == 0:
            return []

        assert self._tree is not None

        self._cascade_insert(self._models, self._tree.nodes, emulate_prepare)

        return self._models

    def _cascade_insert(self, models: Sequence[Model], nodes: dict[str, RelationNode], emulate_prepare: bool) -> None:
        if len(models) == 0:
            return

        for node in nodes.values():
            if node.relation.relation == RelationEnum.BELONGS_TO:
                self._cascade_belongs_to(models, node, emulate_prepare)

        self._insert_rows(models, emulate_prepare)

        for node in nodes.values():
            if node.relation.relation in (RelationEnum.HAS_ONE, RelationEnum.HAS_MANY):
                self._cascade_has(models, node, emulate_prepare)

        for node in nodes.values():
            if node.relation.relation == RelationEnum.MANY_TO_MANY:
                self._cascade_many_to_many(models, node, emulate_prepare)

    def _cascade_belongs_to(self, parents: Sequence[Model], node: RelationNode, emulate_prepare: bool) -> None:
        relation = node.relation
        targets = self._collect_related(parents, relation)
        pending = [target for target in targets if model_mapper(type(target)).primary_key_value(target) is None]

        if len(pending) > 0:
            self._cascade_insert(pending, node.children, emulate_prepare)

        for parent in parents:
            mapper = model_mapper(type(parent))
            related = mapper.related_models(parent, relation)

            if len(related) == 0:
                continue

            target = related[0]
            owner_column = mapper.meta.column_by_name(relation.owner_column)
            target_value = model_mapper(type(target)).key_value(target, relation.target_column)
            mapper.set_column_value(parent, owner_column, target_value)

    def _cascade_has(self, parents: Sequence[Model], node: RelationNode, emulate_prepare: bool) -> None:
        relation = node.relation
        seen: set[int] = set()
        children: list[Model] = []

        for parent in parents:
            mapper = model_mapper(type(parent))
            related = mapper.related_models(parent, relation)

            if len(related) == 0:
                continue

            owner_value = mapper.key_value(parent, relation.owner_column)

            for child in related:
                child_mapper = model_mapper(type(child))
                target_column = child_mapper.meta.column_by_name(relation.target_column)
                child_mapper.set_column_value(child, target_column, owner_value)

                if id(child) not in seen:
                    seen.add(id(child))
                    children.append(child)

        if len(children) > 0:
            self._cascade_insert(children, node.children, emulate_prepare)

    def _cascade_many_to_many(self, parents: Sequence[Model], node: RelationNode, emulate_prepare: bool) -> None:
        relation = node.relation
        targets = self._collect_related(parents, relation)
        pending = [target for target in targets if model_mapper(type(target)).primary_key_value(target) is None]

        if len(pending) > 0:
            self._cascade_insert(pending, node.children, emulate_prepare)

        rows: list[dict[str, Any]] = []

        for parent in parents:
            mapper = model_mapper(type(parent))
            owner_value = mapper.key_value(parent, relation.owner_column)

            for target in mapper.related_models(parent, relation):
                target_mapper = model_mapper(type(target))
                rows.append(
                    {
                        relation.through_owner_column: owner_value,
                        relation.through_target_column: target_mapper.key_value(target, relation.target_column),
                    }
                )

        if len(rows) > 0:
            self._database.insert(relation.through).values(*rows).execute(emulate_prepare)

    def _collect_related(self, parents: Sequence[Model], relation: ModelRelation) -> list[Model]:
        seen: set[int] = set()
        collected: list[Model] = []

        for parent in parents:
            for related in model_mapper(type(parent)).related_models(parent, relation):
                if id(related) in seen:
                    continue

                seen.add(id(related))
                collected.append(related)

        return collected

    def _insert_rows(self, models: Sequence[Model], emulate_prepare: bool) -> None:
        if len(models) == 0:
            return

        mapper = model_mapper(type(models[0]))
        primary_key = self._resolve_auto_increment_primary_key(mapper.meta) if self._fill_primary_keys else None

        if primary_key is not None:
            for model in models:
                self._insert_returning(mapper, model, primary_key, emulate_prepare)

            return

        if self._fill_primary_keys:
            for model in models:
                self._insert_plain(mapper, model, emulate_prepare)

            return

        self._insert_batch(mapper, models, emulate_prepare)

    def _resolve_auto_increment_primary_key(self, meta: ModelMeta) -> ModelColumn | None:
        try:
            primary_keys = meta.primary_keys
        except ModelError:
            return None

        if len(primary_keys) != 1 or not primary_keys[0].auto_increment:
            return None

        return primary_keys[0]

    def _insert_values(self, mapper: ModelMapper[Model], model: Model) -> dict[str, Any]:
        values = mapper.to_row(model)

        for column in mapper.meta.columns:
            if column.auto_increment and values[column.column_name] is None:
                del values[column.column_name]

        return values

    def _insert_returning(
        self,
        mapper: ModelMapper[Model],
        model: Model,
        primary_key: ModelColumn,
        emulate_prepare: bool,
    ) -> None:
        meta = mapper.meta
        result = (
            self._database.insert(meta.table)
            .values(self._insert_values(mapper, model))
            .returning([])
            .last_insert_id(primary_key.column_name)
            .execute(emulate_prepare)
        )

        row = self._single_result(result).fetch_dict()

        if row is None:
            raise ModelError(f"insert into {meta.table!r} returned no row")

        known_columns = {column.column_name for column in meta.columns}

        for column_name, value in row.items():
            if column_name in known_columns:
                mapper.set_column_value(model, meta.column_by_name(column_name), value)

    def _insert_plain(self, mapper: ModelMapper[Model], model: Model, emulate_prepare: bool) -> None:
        table = mapper.meta.table
        self._database.insert(table).values(self._insert_values(mapper, model)).execute(emulate_prepare)

    def _insert_batch(self, mapper: ModelMapper[Model], models: Sequence[Model], emulate_prepare: bool) -> None:
        batches: dict[frozenset[str], list[dict[str, Any]]] = {}

        for model in models:
            values = self._insert_values(mapper, model)
            batches.setdefault(frozenset(values), []).append(values)

        for batch in batches.values():
            self._database.insert(mapper.meta.table).values(*batch).execute(emulate_prepare)

    def _single_result(self, result: ResultABC | list[ResultABC]) -> ResultABC:
        if isinstance(result, list):
            if len(result) != 1:
                raise ModelError(f"expected a single insert result, got {len(result)}")

            return result[0]

        return result
