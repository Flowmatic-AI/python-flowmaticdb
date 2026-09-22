from __future__ import annotations

from flowmaticdb import alias, expression, raw
from flowmaticdb.database import DB


def test_order_by_accepts_a_qualified_list_a_raw_fragment_and_an_expression() -> None:
    db = DB.connect_sqlite(":memory:")

    query = (
        db.select_table("posts", "p")
        .columns([["p", "id"]])
        .inner_join(alias("users", "u"), lambda j: j.on(["u", "id"], ["p", "user_id"]))
        .order_by_desc(["p", "created_at"])
        .order_by_asc(raw('coalesce("p"."published_at", "p"."created_at")'))
        .order_by_asc(expression('abs("p"."score" - ?)', [5]))
        .order_by_asc("id")
    )

    assert query.to_sql() == (
        'SELECT "p"."id" FROM "posts" AS "p" INNER JOIN "users" AS "u" ON "u"."id" = "p"."user_id" '
        'ORDER BY "p"."created_at" DESC, coalesce("p"."published_at", "p"."created_at") ASC, '
        'abs("p"."score" - 5) ASC, "id" ASC'
    )
