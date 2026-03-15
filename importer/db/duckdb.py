"""DuckDB database adapter."""

import json
from datetime import date, datetime, timezone
from typing import Any

import duckdb

from importer.config import DuckDBConfig
from importer.db.base import DatabaseAdapter
from importer.schemas.analytics import ANALYTICS_COLUMNS


class DuckDBAdapter(DatabaseAdapter):
    """DuckDB implementation of the database adapter.

    DuckDB is an embedded database, so no separate server is needed.
    Data is persisted to a file on a shared volume.
    """

    def __init__(self, config: DuckDBConfig):
        self.config = config
        self.conn: duckdb.DuckDBPyConnection | None = None

    def connect(self) -> None:
        self.conn = duckdb.connect(self.config.path)

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def ensure_schema(self) -> None:
        assert self.conn is not None

        # Build columns DDL from schema definition (use DuckDB types)
        columns = ",\n    ".join(
            f"{col} {types[1]}" for col, types in ANALYTICS_COLUMNS.items()
        )

        self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS analytics_events (
                {columns}
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS import_watermarks (
                dataset VARCHAR PRIMARY KEY,
                last_date DATE NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def get_last_imported_date(self, dataset: str) -> date | None:
        assert self.conn is not None
        result = self.conn.execute(
            "SELECT last_date FROM import_watermarks WHERE dataset = ?",
            [dataset],
        ).fetchone()
        if result:
            return result[0]
        return None

    def set_last_imported_date(self, dataset: str, dt: date) -> None:
        assert self.conn is not None
        self.conn.execute(
            """
            INSERT INTO import_watermarks (dataset, last_date, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (dataset) DO UPDATE SET
                last_date = EXCLUDED.last_date,
                updated_at = CURRENT_TIMESTAMP
            """,
            [dataset, dt],
        )

    def insert_events(self, events: list[dict[str, Any]]) -> int:
        assert self.conn is not None
        if not events:
            return 0

        columns = list(ANALYTICS_COLUMNS.keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)

        rows = []
        for event in events:
            rows.append(tuple(event.get(col) for col in columns))

        self.conn.executemany(
            f"INSERT INTO analytics_events ({col_names}) VALUES ({placeholders})",
            rows,
        )
        return len(events)
