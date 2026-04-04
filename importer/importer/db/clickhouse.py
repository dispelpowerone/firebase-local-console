"""ClickHouse database adapter."""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from clickhouse_driver import Client

from importer.config import ClickHouseConfig
from importer.db.base import DatabaseAdapter
from importer.schemas.analytics import ANALYTICS_COLUMNS

logger = logging.getLogger(__name__)


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
            CREATE TABLE IF NOT EXISTS import_tasks (
                dataset String,
                event_date Date,
                created_at DateTime DEFAULT now(),
                completed_at Nullable(DateTime) DEFAULT NULL,
                updated_at Nullable(DateTime) DEFAULT NULL
            )
            ENGINE = ReplacingMergeTree(created_at)
            ORDER BY (dataset, event_date)
        """)

        self._migrate_from_watermarks()
        self._migrate_add_ga_session_id()
        self._migrate_add_updated_at()
        self._migrate_drop_app_info_id()

    def _migrate_from_watermarks(self) -> None:
        """Migrate data from the legacy import_watermarks table into import_tasks.

        For each dataset that has a watermark, creates completed task records for
        every distinct event_date found in analytics_events up to (and including)
        the watermark date. Drops the old table after migration.
        """
        assert self.client is not None

        # Check if the legacy table exists
        tables = self.client.execute(
            "SELECT name FROM system.tables "
            "WHERE database = %(db)s AND name = 'import_watermarks'",
            {"db": self.config.database},
        )
        if not tables:
            return

        # Only migrate if import_tasks is empty (first run after upgrade)
        task_count = self.client.execute("SELECT count() FROM import_tasks")
        if task_count and task_count[0][0] > 0:
            # Already migrated or has data — just drop the old table
            self.client.execute("DROP TABLE IF EXISTS import_watermarks")
            return

        watermarks = self.client.execute(
            "SELECT dataset, last_date FROM import_watermarks FINAL"
        )
        if not watermarks:
            self.client.execute("DROP TABLE IF EXISTS import_watermarks")
            return

        logger.info("Migrating %d dataset(s) from import_watermarks to import_tasks", len(watermarks))

        for dataset, last_date in watermarks:
            # Get all distinct dates already imported for this dataset
            imported_dates = self.client.execute(
                "SELECT DISTINCT event_date FROM analytics_events "
                "WHERE import_dataset = %(ds)s AND event_date <= %(ld)s "
                "ORDER BY event_date",
                {"ds": dataset, "ld": last_date},
            )
            if imported_dates:
                rows = [
                    {"dataset": dataset, "event_date": row[0],
                     "completed_at": datetime.now(tz=timezone.utc)}
                    for row in imported_dates
                ]
                self.client.execute(
                    "INSERT INTO import_tasks (dataset, event_date, completed_at) VALUES",
                    rows,
                )
                logger.info(
                    "Migrated %d completed task(s) for dataset %s",
                    len(rows), dataset,
                )

        self.client.execute("DROP TABLE IF EXISTS import_watermarks")
        logger.info("Dropped legacy import_watermarks table")

    def _migrate_add_ga_session_id(self) -> None:
        """Add param_ga_session_id column and backfill from event_params_json."""
        assert self.client is not None

        cols = self.client.execute(
            "SELECT name FROM system.columns "
            "WHERE database = %(db)s AND table = 'analytics_events' "
            "AND name = 'param_ga_session_id'",
            {"db": self.config.database},
        )
        if cols:
            return

        logger.info("Adding param_ga_session_id column to analytics_events")
        self.client.execute(
            "ALTER TABLE analytics_events "
            "ADD COLUMN IF NOT EXISTS param_ga_session_id Nullable(Int64) "
            "AFTER param_engagement_time_msec"
        )
        self.client.execute(
            "ALTER TABLE analytics_events UPDATE "
            "param_ga_session_id = JSONExtractInt(event_params_json, 'ga_session_id') "
            "WHERE param_ga_session_id IS NULL AND event_params_json IS NOT NULL"
        )
        logger.info("Backfilled param_ga_session_id from event_params_json")

    def _migrate_add_updated_at(self) -> None:
        """Add updated_at column to import_tasks for per-task cooldown tracking."""
        assert self.client is not None

        cols = self.client.execute(
            "SELECT name FROM system.columns "
            "WHERE database = %(db)s AND table = 'import_tasks' "
            "AND name = 'updated_at'",
            {"db": self.config.database},
        )
        if cols:
            return

        logger.info("Adding updated_at column to import_tasks")
        self.client.execute(
            "ALTER TABLE import_tasks "
            "ADD COLUMN IF NOT EXISTS updated_at Nullable(DateTime) DEFAULT NULL"
        )

    def _migrate_drop_app_info_id(self) -> None:
        """Drop app_info_id column from analytics_events if present."""
        assert self.client is not None

        cols = self.client.execute(
            "SELECT name FROM system.columns "
            "WHERE database = %(db)s AND table = 'analytics_events' "
            "AND name = 'app_info_id'",
            {"db": self.config.database},
        )
        if not cols:
            return

        logger.info("Dropping app_info_id column from analytics_events")
        self.client.execute(
            "ALTER TABLE analytics_events DROP COLUMN app_info_id"
        )

    def get_eligible_tasks(self, dataset: str, interval_hours: int) -> list[date]:
        assert self.client is not None
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=interval_hours)
        result = self.client.execute(
            "SELECT event_date FROM import_tasks FINAL "
            "WHERE dataset = %(ds)s AND completed_at IS NULL "
            "AND (updated_at IS NULL OR updated_at < %(cutoff)s) "
            "ORDER BY event_date",
            {"ds": dataset, "cutoff": cutoff},
        )
        return [row[0] for row in result]

    def create_import_tasks(self, dataset: str, dates: list[date]) -> int:
        assert self.client is not None
        if not dates:
            return 0

        # Find dates that already have a task record (pending or completed)
        existing = self.client.execute(
            "SELECT event_date FROM import_tasks FINAL WHERE dataset = %(ds)s",
            {"ds": dataset},
        )
        existing_dates = {row[0] for row in existing}

        new_tasks = [
            {"dataset": dataset, "event_date": d}
            for d in dates
            if d not in existing_dates
        ]
        if not new_tasks:
            return 0

        self.client.execute(
            "INSERT INTO import_tasks (dataset, event_date) VALUES",
            new_tasks,
        )
        return len(new_tasks)

    def complete_import_task(self, dataset: str, event_date: date) -> None:
        assert self.client is not None
        now = datetime.now(tz=timezone.utc)
        self.client.execute(
            "INSERT INTO import_tasks (dataset, event_date, completed_at, updated_at) VALUES",
            [{"dataset": dataset, "event_date": event_date,
              "completed_at": now, "updated_at": now}],
        )

    def mark_task_attempted(self, dataset: str, event_date: date) -> None:
        assert self.client is not None
        self.client.execute(
            "INSERT INTO import_tasks (dataset, event_date, updated_at) VALUES",
            [{"dataset": dataset, "event_date": event_date,
              "updated_at": datetime.now(tz=timezone.utc)}],
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
