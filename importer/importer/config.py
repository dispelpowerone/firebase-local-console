"""Configuration loader for the Firebase Local Console importer."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class AppConfig:
    name: str
    project_id: str
    credentials_file: str
    dataset: str
    table_prefix: str = "events_"


@dataclass
class ClickHouseConfig:
    host: str = "clickhouse"
    port: int = 9000
    http_port: int = 8123
    database: str = "firebase"
    user: str = "default"
    password: str = ""


@dataclass
class DatabaseConfig:
    type: str = "clickhouse"
    clickhouse: ClickHouseConfig = field(default_factory=ClickHouseConfig)


@dataclass
class ImportConfig:
    interval_hours: int = 6
    backfill_days: int = 30
    batch_size: int = 10000
    poll_interval_minutes: int = 10


@dataclass
class Config:
    apps: list[AppConfig] = field(default_factory=list)
    import_settings: ImportConfig = field(default_factory=ImportConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)


def load_config(path: Optional[str] = None) -> Config:
    """Load configuration from YAML file with environment variable overrides."""
    config_path = path or os.environ.get("CONFIG_PATH", "/app/config/config.yaml")

    data = {}
    if Path(config_path).exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    apps = [
        AppConfig(
            name=app["name"],
            project_id=app["project_id"],
            credentials_file=app["credentials_file"],
            dataset=app["dataset"],
            table_prefix=app.get("table_prefix", "events_"),
        )
        for app in data.get("apps", [])
    ]

    import_data = data.get("import", {})
    import_settings = ImportConfig(
        interval_hours=int(
            os.environ.get(
                "IMPORT_INTERVAL_HOURS", import_data.get("interval_hours", 6)
            )
        ),
        backfill_days=import_data.get("backfill_days", 30),
        batch_size=import_data.get("batch_size", 10000),
        poll_interval_minutes=int(
            os.environ.get(
                "POLL_INTERVAL_MINUTES",
                import_data.get("poll_interval_minutes", 10),
            )
        ),
    )

    db_data = data.get("database", {})
    ch_data = db_data.get("clickhouse", {})

    database = DatabaseConfig(
        type=os.environ.get("DB_TYPE", db_data.get("type", "clickhouse")),
        clickhouse=ClickHouseConfig(
            host=os.environ.get("CLICKHOUSE_HOST", ch_data.get("host", "clickhouse")),
            port=int(os.environ.get("CLICKHOUSE_PORT", ch_data.get("port", 9000))),
            http_port=int(ch_data.get("http_port", 8123)),
            database=os.environ.get(
                "CLICKHOUSE_DATABASE", ch_data.get("database", "firebase")
            ),
            user=os.environ.get("CLICKHOUSE_USER", ch_data.get("user", "default")),
            password=os.environ.get("CLICKHOUSE_PASSWORD", ch_data.get("password", "")),
        ),
    )

    return Config(
        apps=apps,
        import_settings=import_settings,
        database=database,
    )
