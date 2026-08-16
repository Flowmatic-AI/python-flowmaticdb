"""Tests for ``list_tables()`` and ``describe_table()``.

The SQLite half runs against a real in-memory database, so it needs no
external service. The PostgreSQL and MySQL halves only assert on the SQL the
dialect renders — the live round-trips live in the integration modules.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest

from flowmaticdb import QueryError
from flowmaticdb.database import DB
from flowmaticdb.database._introspection import parse_columns, parse_constraints
from flowmaticdb.dialects import MySQLDialect, PostgresqlDialect, SQLDialect, SQLiteDialect
from flowmaticdb.query.ddl import TableConstraints, TableDescription
from flowmaticdb.query.enums import ReferentialActionEnum, TypeEnum


@pytest.fixture
def db() -> Iterator[DB]:
    """Yield an in-memory SQLite database holding a roles/users schema."""
    database = DB.connect_sqlite(":memory:")

    database.create_table("roles").identity("id").string("code", 10, not_null=True).execute()
    database.create_table("users") \
        .identity("id") \
        .string("name", 64, not_null=True, default="anon") \
        .string("email", 120) \
        .integer("role_id") \
        .unique_constraint(["email"]) \
        .unique_constraint(["name", "email"]) \
        .foreign_key_constraint(
            "role_id",
            "roles",
            "id",
            on_delete=ReferentialActionEnum.CASCADE,
            on_update=ReferentialActionEnum.SET_NULL,
        ) \
        .execute()

    try:
        yield database
    finally:
        database.close()


def test_describe_table_returns_a_table_description(db: DB) -> None:
    description = db.describe_table("users")

    assert isinstance(description, TableDescription)
    assert isinstance(description.constraints, TableConstraints)


def test_describe_table_columns(db: DB) -> None:
    columns = db.describe_table("users").columns

    assert [column.name for column in columns] == ["id", "name", "email", "role_id"]
    assert columns[1].type == TypeEnum.STRING
    assert columns[1].size == 64
    assert columns[1].not_null is True
    # The value the column was declared with, not the literal that spelled it.
    assert columns[1].default == "anon"
    assert columns[2].not_null is False


def test_describe_table_recovers_every_type_enum(db: DB) -> None:
    """A column declared through the builders describes back as it was declared.

    SQLite has a single float type and stores no datetime precision, so those
    two widths cannot survive the round-trip.
    """
    db.create_table("spread_types") \
        .identity("id") \
        .boolean("flag") \
        .integer("n32", 32).integer("n64", 64) \
        .float("f32", 32).float("f64", 64) \
        .string("s64", 64).string("s255").text("body") \
        .datetime("seen_at").json("payload") \
        .execute()

    columns = db.describe_table("spread_types").columns

    assert [(column.name, column.type, column.size) for column in columns] == [
        ("id", TypeEnum.INT, 64),
        ("flag", TypeEnum.BOOL, None),
        ("n32", TypeEnum.INT, 32),
        ("n64", TypeEnum.INT, 64),
        ("f32", TypeEnum.FLOAT, 64),
        ("f64", TypeEnum.FLOAT, 64),
        ("s64", TypeEnum.STRING, 64),
        ("s255", TypeEnum.STRING, 255),
        ("body", TypeEnum.STRING, sys.maxsize),
        ("seen_at", TypeEnum.DATETIME, None),
        ("payload", TypeEnum.JSON, None),
    ]


def test_describe_table_reports_auto_increment(db: DB) -> None:
    columns = db.describe_table("users").columns

    assert columns[0].auto_increment is True
    # The sequence backing the column is not a default the table declared.
    assert columns[0].default is None
    assert columns[1].auto_increment is False


def test_describe_table_unique_constraints(db: DB) -> None:
    unique = db.describe_table("users").constraints.unique

    assert [constraint.columns for constraint in unique] == [["email"], ["name", "email"]]


def test_describe_table_foreign_keys(db: DB) -> None:
    foreign_keys = db.describe_table("users").constraints.foreign_keys

    assert len(foreign_keys) == 1
    assert foreign_keys[0].columns == ["role_id"]
    assert foreign_keys[0].ref_table == "roles"
    assert foreign_keys[0].ref_columns == ["id"]
    # The enum the key was built with is the enum that comes back, not the
    # string the engine reported. `is` rather than `==`: a StrEnum compares
    # equal to its own value, so `==` would pass on a raw string too.
    assert foreign_keys[0].on_delete is ReferentialActionEnum.CASCADE
    assert foreign_keys[0].on_update is ReferentialActionEnum.SET_NULL


def test_describe_table_ignores_standalone_indexes(db: DB) -> None:
    db.create_index("users", "idx_users_name").columns("name").unique().execute()

    unique = db.describe_table("users").constraints.unique

    assert [constraint.columns for constraint in unique] == [["email"], ["name", "email"]]


def test_describe_table_without_constraints(db: DB) -> None:
    description = db.describe_table("roles")

    assert [column.name for column in description.columns] == ["id", "code"]
    assert description.constraints.unique == []
    assert description.constraints.foreign_keys == []


def test_describe_table_unknown_table_is_empty(db: DB) -> None:
    description = db.describe_table("nope")

    assert description.columns == []
    assert description.constraints.unique == []


def test_table_facade_describe(db: DB) -> None:
    assert db.table("users").describe().columns == db.describe_table("users").columns


def test_create_and_drop_index_round_trip(db: DB) -> None:
    db.create_index("users", "idx_users_email").columns("email").if_not_exists().execute()
    db.create_index("users", "idx_users_email").columns("email").if_not_exists().execute()

    db.drop_index("users", "idx_users_email").if_exists().execute()
    db.drop_index("users", "idx_users_email").if_exists().execute()


def test_create_and_drop_index_in_an_attached_schema(db: DB, tmp_path) -> None:
    db.exec(f"ATTACH DATABASE '{tmp_path / 'reporting.sqlite'}' AS reporting")
    db.create_table(["reporting", "metrics"]).identity("id").string("kind", 32, not_null=True).execute()

    db.create_index(["reporting", "metrics"], "idx_metrics_kind").columns("kind").if_not_exists().execute()
    db.create_index(["reporting", "metrics"], "idx_metrics_kind").columns("kind").if_not_exists().execute()

    indexes = db.query("SELECT name FROM reporting.sqlite_master WHERE type = 'index'").scalars()
    assert "idx_metrics_kind" in indexes

    db.drop_index(["reporting", "metrics"], "idx_metrics_kind").if_exists().execute()
    db.drop_index(["reporting", "metrics"], "idx_metrics_kind").if_exists().execute()

    indexes = db.query("SELECT name FROM reporting.sqlite_master WHERE type = 'index'").scalars()
    assert "idx_metrics_kind" not in indexes


def test_describe_table_in_an_attached_schema(db: DB, tmp_path) -> None:
    db.exec(f"ATTACH DATABASE '{tmp_path / 'reporting.sqlite'}' AS reporting")
    db.create_table(["reporting", "metrics"]).identity("id").string("kind", 32, not_null=True).execute()

    description = db.describe_table(["reporting", "metrics"])

    assert [column.name for column in description.columns] == ["id", "kind"]
    assert description.columns[0].auto_increment is True

    # An unqualified name still resolves, because SQLite searches main, then
    # temp, then every attached database. Only the AUTOINCREMENT probe is
    # narrower -- it reads main's sqlite_master and so misses the keyword.
    unqualified = db.describe_table("metrics")
    assert [column.name for column in unqualified.columns] == ["id", "kind"]
    assert unqualified.columns[0].auto_increment is False


def test_table_facade_create_and_drop_index(db: DB) -> None:
    db.table("users").create_index("idx_users_role_id", "role_id").execute()
    db.table("users").drop_index("idx_users_role_id").execute()


def test_list_tables(db: DB) -> None:
    assert db.list_tables() == ["roles", "users"]


def test_list_tables_ignores_the_schema_on_sqlite(db: DB) -> None:
    assert db.list_tables("reporting") == db.list_tables()


def test_list_tables_hides_sqlite_internals(db: DB) -> None:
    # The identity column gives SQLite a reason to keep sqlite_sequence around.
    db.insert("roles").values({"code": "admin"}).execute()

    assert "sqlite_sequence" in db.query("SELECT name FROM sqlite_master").scalars()
    assert db.list_tables() == ["roles", "users"]


def test_list_tables_skips_indexes_and_views(db: DB) -> None:
    db.create_index("users", "idx_users_email").columns("email").execute()
    db.exec('CREATE VIEW "active_users" AS SELECT * FROM "users"')

    assert db.list_tables() == ["roles", "users"]


def test_describe_table_rejects_an_over_qualified_name(sqlite_dialect: SQLiteDialect) -> None:
    with pytest.raises(QueryError):
        sqlite_dialect.describe_table_columns(["cluster", "app", "users"])


def test_pg_list_tables_defaults_to_public(pg_dialect: PostgresqlDialect) -> None:
    qwp = pg_dialect.list_tables("public")

    assert qwp.params == ["public"]
    assert "pg_class" in qwp.query


def test_pg_describe_table_resolves_through_to_regclass(pg_dialect: PostgresqlDialect) -> None:
    assert pg_dialect.describe_table_columns(["app", "users"]).params == ['"app"."users"']
    assert pg_dialect.describe_table_constraints("users").params == ['"users"']


def test_pg_describe_table_columns_skips_attidentity_before_10(pg_dialect: PostgresqlDialect) -> None:
    assert "attidentity" in pg_dialect.describe_table_columns("users").query
    assert "attidentity" not in PostgresqlDialect(version="9.6").describe_table_columns("users").query


def test_mysql_list_tables_ignores_the_schema(mysql_dialect: MySQLDialect) -> None:
    qwp = mysql_dialect.list_tables("public")

    assert qwp.params == []
    assert "DATABASE()" in qwp.query


def test_sqlite_list_tables_ignores_the_schema(sqlite_dialect: SQLiteDialect) -> None:
    qwp = sqlite_dialect.list_tables("public")

    assert qwp.params == []
    assert "sqlite_master" in qwp.query


def test_ansi_list_tables_honours_the_schema(sql_dialect: SQLDialect) -> None:
    qwp = sql_dialect.list_tables("public")

    assert qwp.params == ["public"]
    assert "information_schema.tables" in qwp.query


def test_mysql_describe_table_defaults_to_the_current_database(mysql_dialect: MySQLDialect) -> None:
    columns = mysql_dialect.describe_table_columns("users")
    constraints = mysql_dialect.describe_table_constraints("users")

    assert columns.params == ["users"]
    assert "c.TABLE_SCHEMA = DATABASE()" in columns.query
    assert constraints.params == ["users"]
    assert "tc.table_schema = DATABASE()" in constraints.query


def test_mysql_describe_table_takes_an_explicit_schema(mysql_dialect: MySQLDialect) -> None:
    qwp = mysql_dialect.describe_table_columns(["app", "users"])

    assert qwp.params == ["users", "app"]
    assert "c.TABLE_SCHEMA = ?" in qwp.query


def test_ansi_describe_table_uses_information_schema(sql_dialect: SQLDialect) -> None:
    assert "information_schema.columns" in sql_dialect.describe_table_columns("users").query
    assert "information_schema.table_constraints" in sql_dialect.describe_table_constraints("users").query


def test_parse_columns(sql_dialect: SQLDialect) -> None:
    columns = parse_columns(sql_dialect, [
        {
            "column_name": "id",
            "column_type": "bigint",
            "not_null": 1,
            "default_expression": "nextval('users_id_seq')",
            "auto_increment": 1,
        },
        {
            "column_name": "name",
            "column_type": "varchar(64)",
            "not_null": 0,
            "default_expression": None,
            "auto_increment": 0,
        },
    ])

    assert columns[0].auto_increment is True
    assert columns[0].default is None
    assert columns[0].not_null is True
    assert columns[1].type == TypeEnum.STRING
    assert columns[1].size == 64
    assert columns[1].default is None
    assert columns[1].not_null is False


def test_parse_constraints_groups_columns_by_id() -> None:
    constraints = parse_constraints([
        {
            "constraint_id": "1",
            "constraint_name": "users_pair_key",
            "constraint_type": "UNIQUE",
            "column_name": "name",
            "column_position": 1,
            "ref_table": None,
            "ref_column": None,
            "on_delete": None,
            "on_update": None,
        },
        {
            "constraint_id": "1",
            "constraint_name": "users_pair_key",
            "constraint_type": "UNIQUE",
            "column_name": "email",
            "column_position": 2,
            "ref_table": None,
            "ref_column": None,
            "on_delete": None,
            "on_update": None,
        },
        {
            "constraint_id": "2",
            "constraint_name": None,
            "constraint_type": "FOREIGN KEY",
            "column_name": "role_id",
            "column_position": 1,
            "ref_table": "roles",
            "ref_column": "id",
            "on_delete": "CASCADE",
            "on_update": "NO ACTION",
        },
    ])

    assert len(constraints.unique) == 1
    assert constraints.unique[0].columns == ["name", "email"]
    assert constraints.unique[0].name == "users_pair_key"

    assert len(constraints.foreign_keys) == 1
    assert constraints.foreign_keys[0].name is None
    assert constraints.foreign_keys[0].columns == ["role_id"]
    assert constraints.foreign_keys[0].ref_columns == ["id"]
    assert constraints.foreign_keys[0].on_delete is ReferentialActionEnum.CASCADE
    assert constraints.foreign_keys[0].on_update is ReferentialActionEnum.NO_ACTION


def test_parse_constraints_keeps_an_unlisted_referential_action_as_a_string() -> None:
    """An action the enum does not list is reported raw rather than dropped.

    SET DEFAULT is the realistic case: this library will not build one because
    InnoDB does not carry it out, but a table created elsewhere may declare it
    and describing that table must not lose the rule.
    """
    constraints = parse_constraints([
        {
            "constraint_id": "1",
            "constraint_name": "users_role_fk",
            "constraint_type": "FOREIGN KEY",
            "column_name": "role_id",
            "column_position": 1,
            "ref_table": "roles",
            "ref_column": "id",
            "on_delete": "SET DEFAULT",
            "on_update": None,
        },
    ])

    assert constraints.foreign_keys[0].on_delete == "SET DEFAULT"
    assert not isinstance(constraints.foreign_keys[0].on_delete, ReferentialActionEnum)
    assert constraints.foreign_keys[0].on_update is None


def test_parse_constraints_ignores_other_constraint_types() -> None:
    constraints = parse_constraints([
        {
            "constraint_id": "1",
            "constraint_name": "users_pkey",
            "constraint_type": "PRIMARY KEY",
            "column_name": "id",
            "column_position": 1,
            "ref_table": None,
            "ref_column": None,
            "on_delete": None,
            "on_update": None,
        },
    ])

    assert constraints.unique == []
    assert constraints.foreign_keys == []
