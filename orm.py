from __future__ import annotations

from typing import Annotated

from pydantic import ValidationError

from flowmaticdb import ModelError
from flowmaticdb.database import DB
from flowmaticdb.orm import (
    AutoIncrement,
    BelongsTo,
    HasMany,
    HasOne,
    ManyToMany,
    Model,
    PrimaryKey,
    belongs_to,
    column,
    has_many,
    has_one,
    many_to_many,
)

show_sql = False


def debug_callback(query: str, starttime: float, error: str | None) -> None:
    if show_sql:
        print(f"    [SQL] {query}")

    if error:
        print(f"    [ERROR] {error}")


class Country(Model):
    __table__ = "countries"

    code: PrimaryKey[str]
    name: str


class Profile(Model):
    __table__ = "profiles"

    id: AutoIncrement = None
    user_id: int
    bio: str


class Comment(Model):
    __table__ = "comments"

    id: AutoIncrement = None
    post_id: int
    body: str


class Tag(Model):
    __table__ = "tags"

    id: AutoIncrement = None
    slug: str

    posts: ManyToMany[Post] = many_to_many("post_tags")


class Post(Model):
    __table__ = "posts"

    id: AutoIncrement = None
    user_id: int
    title: str

    author: BelongsTo[User] = belongs_to()
    comments: HasMany[Comment] = has_many()
    tags: ManyToMany[Tag] = many_to_many("post_tags")


class User(Model):
    __table__ = "users"

    id: AutoIncrement = None
    name: str
    email: Annotated[str, column(column_name="email_address")]
    country_code: str | None = None

    country: BelongsTo[Country] = belongs_to()
    profile: HasOne[Profile] = has_one()
    posts: HasMany[Post] = has_many()


def create_schema(db: DB) -> None:
    (
        db.create_table("countries")
        .if_not_exists()
        .string("code", not_null=True)
        .string("name")
        .primary_keys(["code"])
        .execute()
    )

    (
        db.create_table("users")
        .if_not_exists()
        .identity("id")
        .string("name", not_null=True)
        .string("email_address")
        .string("country_code")
        .execute()
    )

    (
        db.create_table("profiles")
        .if_not_exists()
        .identity("id")
        .integer("user_id")
        .text("bio")
        .execute()
    )

    (
        db.create_table("posts")
        .if_not_exists()
        .identity("id")
        .integer("user_id")
        .string("title", not_null=True)
        .execute()
    )

    (
        db.create_table("comments")
        .if_not_exists()
        .identity("id")
        .integer("post_id")
        .text("body")
        .execute()
    )

    (
        db.create_table("tags")
        .if_not_exists()
        .identity("id")
        .string("slug", not_null=True)
        .execute()
    )

    (
        db.create_table("post_tags")
        .if_not_exists()
        .integer("post_id")
        .integer("tag_id")
        .execute()
    )


def heading(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def table_counts(db: DB) -> str:
    tables = ["users", "posts", "comments", "post_tags", "tags"]

    return " ".join(f"{table}={db.select(table).count()}" for table in tables)


db = DB.connect_sqlite(":memory:", debug_callback=debug_callback)
# db = DB.connect_postgresql("postgres", host="localhost", user="postgres", debug_callback=debug_callback)
# db = DB.connect_mysql("flowmaticdb", host="localhost", user="root", password="", debug_callback=debug_callback)

create_schema(db)

heading("Model metadata")

meta = User.orm_meta()
print(f"table            {meta.table}")
print(f"columns          {[c.column_name for c in meta.columns]}")
print(f"primary key      {meta.primary_key.column_name} (auto increment: {meta.primary_key.auto_increment})")
print(f"renamed field    email -> {meta.column_by_field('email').column_name}")
print(f"relations        {sorted(meta.relations)}")

for name in ["country", "profile", "posts"]:
    relation = meta.relation(name)
    print(
        f"  {name:<8} {relation.relation.value:<14} {meta.table}.{relation.owner_column} = "
        f"{relation.target.orm_meta().table}.{relation.target_column}"
    )

tags = Post.orm_meta().relation("tags")
print(
    f"  {'tags':<8} {tags.relation.value:<14} posts.{tags.owner_column} = {tags.through}.{tags.through_owner_column}"
    f", {tags.through}.{tags.through_target_column} = tags.{tags.target_column}"
)

heading("INSERT with cascades")

(
    db.insert_models([
        Country(code="nl", name="Netherlands"),
        Country(code="be", name="Belgium"),
    ])
    .execute()
)

sql_tag = Tag(slug="sql")

alice = User(
    name="Alice",
    email="alice@example.com",
    country_code="nl",
    profile=Profile(user_id=0, bio="Writes about databases"),
    posts=[
        Post(
            user_id=0,
            title="Joins are not scary",
            comments=[
                Comment(post_id=0, body="Great read"),
                Comment(post_id=0, body="More of this please"),
            ],
            tags=[sql_tag, Tag(slug="beginner")],
        ),
        Post(
            user_id=0,
            title="Indexes in practice",
            tags=[sql_tag],
        ),
    ],
)

(
    db.insert_model(alice)
    .relation("profile")
    .relation("posts.comments")
    .relation("posts.tags")
    .execute()
)

join_rows = (
    db.select("post_tags")
    .execute()
    .fetch_dicts()
)

print(f"alice.id             {alice.id}")
print(f"profile.user_id      {alice.profile.user_id if alice.profile else None}")
print(f"post ids             {[p.id for p in alice.posts]}")
print(f"post.user_id         {[p.user_id for p in alice.posts]}")
print(f"comment.post_id      {[c.post_id for p in alice.posts for c in p.comments]}")
print(f"tag ids              {[t.id for p in alice.posts for t in p.tags]} (the shared tag is inserted once)")
print(f"post_tags rows       {join_rows}")

bob = User(
    name="Bob",
    email="bob@example.com",
    country_code="be",
    posts=[Post(user_id=0, title="Why I like SQLite")],
)

(
    db.insert_model(bob)
    .relation("posts")
    .execute()
)

print(f"bob.id               {bob.id}")

heading("SELECT with relations")

show_sql = True
users = (
    db.select_models(User)
    .relation("country")
    .relation("profile")
    .relation("posts.comments")
    .relation("posts.tags")
    .order_by_asc("id")
    .fetch_models()
)
show_sql = False

print("\nqueries above: 1 for users + 1 per relation node, no matter how many rows\n")

for user in users:
    country = user.country.name if user.country else "-"
    bio = user.profile.bio if user.profile else "-"
    print(f"{user.name} <{user.email}> from {country}")
    print(f"  profile: {bio}")

    for post in user.posts:
        print(f"  post {post.title!r} tags={[t.slug for t in post.tags]} comments={[c.body for c in post.comments]}")

heading("SELECT: the query builder surface is inherited")

total = (
    db.select_models(User)
    .count()
)

found = (
    db.select_models(User)
    .where_equals("name", "Bob")
    .fetch_model()
)

missing = (
    db.select_models(User)
    .where_equals("name", "Nobody")
    .fetch_model()
)

matching = (
    db.select_models(User)
    .where_contains("email_address", "example.com")
    .limit(1)
    .fetch_models()
)

rendered = (
    db.select_models(User)
    .where_equals("id", 1)
    .to_sql()
)

print(f"count                {total}")
print(f"where + fetch_model  {found}")
print(f"no match             {missing}")
print(f"like + limit         {[u.name for u in matching]}")
print(f"to_sql               {rendered}")

ascending = (
    db.select_models(User)
    .relation("posts", lambda query: query.order_by_asc("title"))
)

descending = (
    db.select_models(User)
    .relation("posts", lambda query: query.order_by_desc("title"))
)

for label, query in [("asc", ascending), ("desc", descending)]:
    customized = (
        query
        .where_equals("id", alice.id)
        .fetch_model()
    )
    print(f"relation {label:<4}        {[p.title for p in customized.posts] if customized else None}")

heading("Relation loading state")

partial = (
    db.select_models(User)
    .relation("posts")
    .where_equals("id", alice.id)
    .fetch_model()
)

assert partial is not None
print(f"posts loaded         {partial.is_relation_loaded('posts')}")
print(f"profile loaded       {partial.is_relation_loaded('profile')}")

heading("UPDATE")

alice.name = "Alice Cooper"
alice.posts[0].title = "Joins are still not scary"

(
    db.update_model(alice)
    .relation("posts")
    .execute()
)

updated_name = (
    db.select("users")
    .columns(["name"])
    .where_equals("id", alice.id)
    .execute()
    .scalar()
)

updated_title = (
    db.select("posts")
    .columns(["title"])
    .where_equals("id", alice.posts[0].id)
    .execute()
    .scalar()
)

print(f"cascaded             {updated_name!r} / {updated_title!r}")

bob.name = "Bobby"
bob.email = "not-written@example.com"

(
    db.update_model(bob)
    .columns(["name"])
    .execute()
)

row = (
    db.select("users")
    .columns(["name", "email_address"])
    .where_equals("id", bob.id)
    .execute()
    .fetch_dict()
)

print(f"columns([\"name\"])    {row}")

heading("DELETE")

print(f"before               {table_counts(db)}")

target = (
    db.select_models(User)
    .where_equals("id", alice.id)
    .fetch_model()
)

assert target is not None

(
    db.delete_model(target)
    .relation("profile")
    .relation("posts.comments")
    .relation("posts.tags")
    .execute()
)

print(f"after                {table_counts(db)}")
print("many to many removed the join rows and left the tags table alone")

heading("Errors")

try:
    (
        db.update_model(User(name="Ghost", email="ghost@example.com"))
        .execute()
    )
except ModelError as error:
    print(f"no primary key       {error}")

try:
    (
        db.update_model(bob)
        .columns(["nickname"])
        .execute()
    )
except ModelError as error:
    print(f"unknown column       {error}")

try:
    (
        db.select_models(User)
        .relation("posts.nonsense")
        .fetch_models()
    )
except ModelError as error:
    print(f"unknown relation     {error}")

try:
    (
        db.delete_model(bob)
        .relation("posts.tags.posts")
        .execute()
    )
except ModelError as error:
    print(f"delete past join     {error}")

try:
    User.model_validate({"name": "No Email"})
except ValidationError as error:
    print(f"pydantic validation  {error.error_count()} error: {error.errors()[0]['loc']} {error.errors()[0]['msg']}")

db.close()
