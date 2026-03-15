"""ClickHouse database adapter."""

from datetime import date, datetime, timezone
from typing import Any

from clickhouse_driver import Client

from importer.config import ClickHouseConfig
from importer.db.base import DatabaseAdapter
from importer.schemas.analytics import ANALYTICS_COLUMNS


class ClickHouseAdapter(DatabaseAdapter):
    """ClickHouse implementation of the database adapter."""

    def __init__(self, config: ClickHouseConfig):
        self.config = config
        self.client: Client | None = None

    def connect(self) -> None:
        self.client = Client(
            host=self.config.host,
            port=self.config.port,
            database="default",
            user=self.config.user,
            password=self.config.password,
        )
        # Ensure the target database exists
        self.client.execute(f"CREATE DATABASE IF NOT EXISTS {self.config.database}")
        self.client.disconnect()
        self.client = Client(
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
            user=self.config.user,
            password=self.config.password,
        )

    def close(self) -> None:
        if self.client:
            self.client.disconnect()
            self.client = None

    def ensure_schema(self) -> None:
        assert self.client is not None

        # Build columns DDL from schema definition (use ClickHouse types)
        columns = ",\n    ".join(
            f"{col} {types[0]}" for col, types in ANALYTICS_COLUMNS.items()
        )

        self.client.execute(f"""
            CREATE TABLE IF NOT EXISTS analytics_events (
                {columns}
            )
            ENGINE = MergeTree()
            PARTITION BY toYYYYMM(event_date)
            ORDER BY (event_date, event_name, user_pseudo_id, event_timestamp)
        """)

        self.client.execute("""
            CREATE TABLE IF NOT EXISTS import_watermarks (
                dataset String,
                last_date Date,
                updated_at DateTime DEFAULT now()
            )
            ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY dataset
        """)

    def get_last_imported_date(self, dataset: str) -> date | None:
        assert self.client is not None
        result = self.client.execute(
            "SELECT last_date FROM import_watermarks FINAL WHERE dataset = %(ds)s",
            {"ds": dataset},
        )
        if result:
            return result[0][0]
        return None

    def set_last_imported_date(self, dataset: str, dt: date) -> None:
        assert self.client is not None
        self.client.execute(
            "INSERT INTO import_watermarks (dataset, last_date) VALUES",
            [{"dataset": dataset, "last_date": dt}],
        )

    def insert_events(self, events: list[dict[str, Any]]) -> int:
        assert self.client is not None
        if not events:
            return 0
        self.client.execute(
            "INSERT INTO analytics_events VALUES",
            events,
        )
        return len(events)
