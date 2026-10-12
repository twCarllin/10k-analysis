"""Dedicated SQLite v1 storage; collection IDs are unique within each collection."""

import json
from pathlib import Path
import sqlite3

from .model import COLLECTIONS, snapshot

APPLICATION_ID = 0x494D4150


def _check_database(connection):
    """Check ownership and version before any mutation of an existing database."""
    if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ValueError("not an industry-map database")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("unsupported database schema_version")
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    if tables != [("items",)]:
        raise ValueError("invalid industry-map database schema")
    columns = connection.execute("PRAGMA table_info(items)").fetchall()
    if [(row[1], row[2], row[3], row[5]) for row in columns] != [
        ("collection", "TEXT", 1, 1),
        ("id", "TEXT", 1, 2),
        ("payload", "TEXT", 1, 0),
    ]:
        raise ValueError("invalid industry-map database schema")


def save(fragment, sqlite):
    """save(fragment: dict, sqlite: path) -> None; upsert IDs, retaining old periods.

    New databases contain an items(collection, id, payload) table, a composite
    primary key, application_id=0x494D4150, and user_version=1. JSON stores nulls
    and record fields without interpretation. Existing foreign databases fail.
    """
    if fragment.get("schema_version") != 1:
        raise ValueError("unsupported snapshot schema_version")
    rows = [
        (name, item["id"], json.dumps(item, ensure_ascii=False, allow_nan=False))
        for name in COLLECTIONS
        for item in fragment[name]
    ]
    path = Path(sqlite)
    existed = path.exists()
    connection = sqlite3.connect(path)
    try:
        if existed:
            _check_database(connection)
        with connection:
            if not existed:
                connection.execute(
                    "CREATE TABLE items (collection TEXT NOT NULL, id TEXT NOT NULL, "
                    "payload TEXT NOT NULL, PRIMARY KEY (collection, id))"
                )
                connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                connection.execute("PRAGMA user_version=1")
            connection.executemany(
                "INSERT INTO items VALUES (?, ?, ?) ON CONFLICT(collection, id) "
                "DO UPDATE SET payload=excluded.payload",
                rows,
            )
    finally:
        connection.close()


def load(sqlite):
    """load(sqlite: path) -> dict; read a dedicated v1 database without writes."""
    uri = Path(sqlite).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        _check_database(connection)
        collections = {name: [] for name in COLLECTIONS}
        for name, payload in connection.execute(
            "SELECT collection, payload FROM items ORDER BY rowid"
        ):
            collections[name].append(json.loads(payload))
        return snapshot(**collections)
    finally:
        connection.close()
