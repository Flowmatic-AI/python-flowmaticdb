from __future__ import annotations

import datetime
from datetime import datetime
from pprint import pprint

from flowmaticdb.database import DB


def debug_callback(query: str, time: float, error: str | None):
    print(f"[SQL] {query}")
    print(f"[TIME] {time:.4f}s")

    if error:
        print(f"[ERROR] {error}")

db = DB.connect_sqlite("database.sqlite", debug_callback=debug_callback)
# db = DB.connect_postgresql("postgres", host="localhost", user="postgres", debug_callback=debug_callback, asyncpg_adapter=False)
# db = DB.connect_postgresql("postgres", host="localhost", user="postgres", debug_callback=debug_callback, asyncpg_adapter=True)
# db = DB.connect_mysql("flowmaticdb", host="localhost", user="root", password="", debug_callback=debug_callback)

db.drop_table("users")\
    .if_exists()\
    .execute()

db.create_table("users")\
    .if_not_exists()\
    .auto_increment("id")\
    .json("json_column")\
    .datetime("datetime_column")\
    .execute()

db.insert("users")\
    .values({
        "json_column": {"key1": "value1", "key2": 25},
        "datetime_column": datetime.now()
    })\
    .execute()

db.insert("users")\
    .values({
        "json_column": [1, 2, 3, 4],
        "datetime_column": datetime.now()
    })\
    .execute()

pprint(db.select("users").execute().fetch_dicts())

db.drop_table("users")\
    .if_exists()\
    .execute()
