from __future__ import annotations

import datetime
import time
from pprint import pprint

from flowmaticdb.database import DB
from flowmaticdb.query.enums import ReferentialActionEnum
from flowmaticdb import raw


def debug_callback(query: str, starttime: float, error: str | None):
    elapsed = (time.time() * 10000) - starttime

    print(f"[SQL] {query}")
    print(f"[TIME] {elapsed:.4f}s")

    if error:
        print(f"[ERROR] {error}")

db = DB.connect_sqlite(":memory:", debug_callback=debug_callback, max_concurrent_connections=1, acquire_connection_timeout=60)
# db = DB.connect_postgresql("postgres", host="localhost", user="postgres", debug_callback=debug_callback, asyncpg_adapter=True)
# db = DB.connect_postgresql("postgres", host="localhost", user="postgres", debug_callback=debug_callback, asyncpg_adapter=False)
# db = DB.connect_mysql("flowmaticdb", host="localhost", user="root", password="", debug_callback=debug_callback)

db.create_table("users").if_not_exists().identity("id").string("name", not_null=True).integer("age").current_timestamp("updated_at").datetime('created_at').text("always filled in text", True, "no way").column("test_columm", "VECTOR", default=raw('CURRENT_TIMESTAMP')).unique_constraint(["id"], "test_unique").boolean("always_false", default=False).execute()

db.create_table("posts").if_not_exists().identity("id").string("title", not_null=True).text("body").integer("user_id").foreign_key_constraint("user_id", "users", "id", on_delete=ReferentialActionEnum.CASCADE).execute()

db.alter_table("users").add_string("email", size=255).execute()

db.select("users")\
    .columns([
        ['users', 'id'],
        ['users', 'name'],
    ])\
    .where_raw("id = ? AND id = %s", [1, 2])\
    .execute()

try:
    db.alter_table("users").add_unique_constraint(["email"], name="uq_users_email").execute()
except Exception as e:
    print(f"\n[Expected] SQLite limitation: {e}")

db.insert("users").values(
    {"name": datetime.datetime.now(), "age": 24},
    {"name": "Bob",   "age": 25},
).execute()

print("Inserted 2 users.")

subquery = db.select("users").columns(['id'])
result = db.select("users").where_exists(subquery).execute()
users: list[dict] = result.fetch_dicts()
print("\nAll users after insert:")
for u in users:
    print(f"  {u}")

db.update("users").updates({"age": 26}).where_equals("name", "Bob").where_group(lambda group: group.where_not_equals('name', 'Alice')).execute()
print("\nUpdated Bob's age to 26.")

result = db.select("users")\
    .where_equals("name", "Bob")\
    .left_join(
        "posts",
        lambda join: join.on(
            ["users", "id"], 
            ["posts", "user_id"]
            )
        )\
    .execute()

print("\nBob after update:", result.fetch_dict())

db.delete("users").where_equals("name", "Alice").execute()
print("\nDeleted Alice.")

result = db.select("users").execute()
print("\nFinal users in table:")
for u in result.fetch_dicts():
    print(f"  {u}")

print("\n" + "=" * 70)
print("GIANT SELECT — every condition type + joins + group/having + unions")
print("=" * 70)

subq_active = db.select("users").columns(["id"]).where_equals("active", 1)
subq_young  = db.select("users").columns(["id"]).where_less_than("age", 30)

result = db.select("users").columns(["id", "name", "email", "age", "created_at", "score"])

bigQuery = db.select("users").columns(["id", "name", "email", "age", "created_at", "score"])

subq_active = db.select("users").columns(["id"]).where_equals("active", 1)
subq_young  = db.select("users").columns(["id"]).where_less_than("age", 30)

bigQuery.distinct()

bigQuery.inner_join_table(
    "posts",
    lambda join: join.on(["users", "id"], ["p", "user_id"]),
    "p",
)
bigQuery.left_join_table(
    "comments",
    lambda join: join.on(["p", "id"], ["c", "post_id"]).where_between(["c", "id"], 0, 999),
    "c",
)
bigQuery.cross_join("sessions")

bigQuery = (
    bigQuery
    .where_equals("active", True)
    .or_where_equals("status", "pending")
    .where_not_equals("role", "banned")
    .or_where_not_equals("role", "archived")
    .where_is_null("deleted_at")
    .or_where_is_null("suspended_at")
    .where_is_not_null("email")
    .or_where_is_not_null("phone")
    .where_like("name", "Alice%")
    .or_where_like("email", "%@example.com")
    .where_not_like("name", "test%")
    .or_where_not_like("email", "%@spam.com")
    .where_starts_with("username", "admin")
    .or_where_starts_with("username", "mod")
    .where_ends_with("filename", ".pdf")
    .or_where_ends_with("filename", ".docx")
    .where_contains("bio", "engineer")
    .or_where_contains("bio", "developer")
    .where_not_contains("bio", "script kiddie")
    .or_where_not_contains("bio", "spammer")
    .where_in("id", [1, 2, 3])
    .or_where_in("id", [10, 20, 30, 40])
    .where_not_in("id", [999, 888])
    .or_where_not_in("id", [777])
    .where_less_than("age", 18)
    .or_where_less_than("age", 13)
    .where_less_than_or_equals("age", 65)
    .or_where_less_than_or_equals("age", 0)
    .where_greater_than("score", 100)
    .or_where_greater_than("score", 999)
    .where_greater_than_or_equals("score", 0)
    .or_where_greater_than_or_equals("score", 1000)
    .where_between("age", 18, 65)
    .or_where_between("age", 1, 17)
    .where_not_between("age", 0, 17)
    .or_where_not_between("age", 66, 120)
    .where_empty("middle_name")
    .or_where_empty("nickname")
    .where_not_empty("full_name")
    .or_where_not_empty("display_name")
    .where_regex("email", r"^[a-z]+@")
    .or_where_regex("phone", r"^\+?1-")
    .where_not_regex("email", r"^test@")
    .or_where_not_regex("email", r"spam@")
    .where_exists(subq_active)
    .or_where_exists(subq_young)
    .where_not_exists(subq_active)
    .or_where_not_exists(subq_young)

    .where_group(
        lambda g: (
            g
            .where_equals("plan", "premium")
            .or_where_group(
                lambda g2: (
                    g2
                    .where_equals("plan", "free")
                    .where_group(
                        lambda g3: (
                            g3
                            .where_greater_than("trial_days", 0)
                            .or_where_is_null("trial_ends")
                        )
                    )
                )
            )
        )
    )
    .or_where_not_group(
        lambda g: g.where_equals("role", "internal")
    )

    .where_raw("EXTRACT(YEAR FROM created_at) = ?", [2026])
    .or_where_raw("last_login IS NOT NULL")

    .where_operator("json_data", "@>", '{"vip": true}')
    .or_where_operator("point", "<@", "circle(0,0,100)")

    .group_by(["plan", "status"])

    .having_equals("plan", "enterprise")
    .or_having_equals("plan", "startup")
    .having_not_equals("status", "archived")
    .or_having_not_equals("status", "deleted")
    .having_greater_than("score", 500)
    .or_having_greater_than("score", 1000)
    .having_less_than("score", 99999)
    .having_between("age", 0, 150)
    .or_having_between("age", 18, 35)
    .having_not_between("age", 0, 17)
    .or_having_not_between("age", 100, 200)
    .having_is_null("deleted_at")
    .or_having_is_null("suspended_at")
    .having_is_not_null("email")
    .or_having_is_not_null("phone")
    .having_like("email", "%@corp.com")
    .or_having_like("email", "%@org")
    .having_not_like("email", "%@spam.com")
    .or_having_not_like("email", "%@temp")
    .having_starts_with("domain", "internal")
    .or_having_starts_with("domain", "corp")
    .having_ends_with("filename", ".csv")
    .or_having_ends_with("filename", ".xlsx")
    .having_contains("description", "urgent")
    .or_having_contains("description", "priority")
    .having_not_contains("description", "obsolete")
    .or_having_not_contains("description", "deprecated")
    .having_in("region", ["US", "EU", "APAC"])
    .or_having_in("region", ["LATAM"])
    .having_not_in("region", ["ANON"])
    .or_having_not_in("region", ["BLOCKED"])
    .having_empty("middle_name")
    .or_having_empty("nickname")
    .having_not_empty("full_name")
    .or_having_not_empty("display_name")
    .having_regex("email", r"\.com$")
    .or_having_regex("email", r"\.org$")
    .having_not_regex("email", r"\.test$")
    .or_having_not_regex("email", r"\.local$")
    .having_exists(subq_active)
    .or_having_exists(subq_young)
    .having_not_exists(subq_active)
    .or_having_not_exists(subq_young)

    .having_group(
        lambda g: (
            g
            .having_greater_than("score", 1000)
            .or_having_group(
                lambda g2: g2
                .having_equals("vip", True)
                .having_in("tier", ["gold", "platinum"])
            )
        )
    )
    .or_having_not_group(
        lambda g: g.having_equals("status", "internal")
    )
    .having_raw("AVG(rating) >= ?", [4.5])
    .or_having_raw("MAX(logins) > 100")
    .having_raw("json_meta @> '{\"premium\": true}'")
    .or_having_raw("tsvector @@ to_tsquery('urgent')")

    .order_by_asc("plan")
    .order_by_desc("score")

    .limit(50)
    .offset(10)

    .union(
        db.select("archived_users")
        .columns(["id", "name", "email", "age", "archived_at", "score"])
        .where_greater_than("score", 500)
    )
    .union_all(
        db.select("legacy_users")
        .columns(["id", "name", "email", "age", "created_at", "score"])
        .where_equals("migrated", False)
    )
)
print(f"\n{'-' * 70}")
print(f"GENERATED SQL:")
print(bigQuery.to_sql())
print(f"{'-' * 70}\n")

pprint(db.describe_table("users"))
pprint(db.describe_table("posts"))

print("\n" + "=" * 70)
print("INDEXES — create_index / drop_index")
print("=" * 70)

# The simplest form: one column, named explicitly.
db.create_index("users", "idx_users_name").columns("name").execute()

# Several columns, in the order they should be indexed in.
db.create_index("users", "idx_users_name_age").columns(["name", "age"]).execute()

# column() adds one at a time, for when the list is built up rather than known.
db.create_index("posts", "idx_posts_user_title").column("user_id").column("title").execute()

# unique() makes it a UNIQUE INDEX — a constraint SQLite will happily enforce
# even though it refuses to ALTER one onto an existing table.
db.create_index("users", "idx_users_email_unique").columns("email").unique().execute()

# if_not_exists() where the engine supports it. PostgreSQL needs 9.5+, SQLite
# always has it, and MySQL only offers it on MariaDB 10.1.4+ -- it raises a
# QueryError elsewhere rather than emitting SQL the server would reject.
db.create_index("users", "idx_users_age").columns("age").if_not_exists().execute()

# The table facade carries the table name for you, so the index is one call.
db.table("users").create_index("idx_users_updated", "updated_at").execute()

# to_sql() renders without running, which is what the migration tooling wants.
print("\nRendered without executing:")
print("  " + db.create_index("posts", "idx_posts_body").columns("body").unique().to_sql())

# Indexes are not part of describe_table() -- it reports the constraints a table
# declares, and a standalone index is not one of them. So idx_users_email_unique
# is absent below even though it is a UNIQUE index: only the table's own
# unique_constraint() shows up.
print("\nUnique constraints on 'users' (note: no idx_users_email_unique):")
for unique in db.describe_table("users").constraints.unique:
    print(f"  {unique.name} {unique.columns}")

# Dropping. if_exists() keeps a migration re-runnable.
db.drop_index("users", "idx_users_name_age").if_exists().execute()
db.table("users").drop_index("idx_users_updated").execute()

# An index this dialect never created: without if_exists() the engine objects.
try:
    db.drop_index("users", "idx_that_was_never_there").execute()
except Exception as e:
    print(f"\n[Expected] Dropping a missing index: {e}")

print("\nDropping 'posts' table...")
db.drop_table("posts").if_exists().execute()

print("\nDropping 'users' table...")
db.drop_table("users").if_exists().execute()

try:
    result = db.select("users").execute()
    print("\nUsers after drop:")
    for u in result.fetch_dicts():
        print(f"  {u}")
except Exception as e:
    print(f"\n[Expected] Table 'users' no longer exists: {e}")
