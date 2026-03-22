"""Firebase Local Console Importer — main entry point.

Imports Firebase Analytics data from BigQuery into ClickHouse.
Designed to be invoked on a schedule by Ofelia. Each run checks the
last successful import time and skips if within the configured cooldown.
"""

import logging
import sys
from datetime import datetime, timedelta, timezone

from importer.bigquery_client import BigQueryClient
from importer.config import AppConfig, Config, ImportConfig, load_config
from importer.db.base import DatabaseAdapter
from importer.db.clickhouse import ClickHouseAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("importer")


def create_db_adapter(config: Config) -> DatabaseAdapter:
    """Create the database adapter based on configuration."""
    if config.database.type != "clickhouse":
        raise ValueError(f"Unsupported database type: {config.database.type}")
    return ClickHouseAdapter(config.database.clickhouse)


def should_skip_import(db: DatabaseAdapter, interval_hours: int) -> bool:
    """Check if we should skip this run based on the last import time."""
    last_import = db.get_last_import_time()
    if last_import is None:
        return False

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=interval_hours)
    if last_import > cutoff:
        logger.info(
            "Last import was at %s (<%dh ago) — skipping",
            last_import.isoformat(),
            interval_hours,
        )
        return True
    return False


def import_app(
    app: AppConfig,
    import_settings: ImportConfig,
    db: DatabaseAdapter,
) -> None:
    """Run a single import cycle for one app using its own BQ credentials."""
    last_imported = db.get_last_imported_date(app.dataset)
    if last_imported:
        logger.info("[%s] Last imported date: %s", app.name, last_imported)
    else:
        logger.info("[%s] No previous import — will backfill", app.name)

    with BigQueryClient(app, import_settings) as bq_client:
        dates_to_import = bq_client.get_dates_to_import(last_imported)
        if not dates_to_import:
            logger.info("[%s] No new data to import", app.name)
            return

        logger.info(
            "[%s] Importing %d day(s): %s → %s",
            app.name,
            len(dates_to_import),
            dates_to_import[0],
            dates_to_import[-1],
        )

        for event_date in dates_to_import:
            try:
                events = bq_client.fetch_events(event_date)

                if events:
                    count = db.insert_events(events)
                    logger.info(
                        "[%s] Inserted %d events for %s", app.name, count, event_date
                    )
                else:
                    logger.info("[%s] No events for %s", app.name, event_date)

                db.set_last_imported_date(app.dataset, event_date)
            except Exception:
                logger.exception("[%s] Failed to import %s", app.name, event_date)
                break


def main() -> None:
    """Main entry point — runs a single import cycle then exits."""
    config = load_config()

    if not config.apps:
        logger.error("No apps configured. Add apps to config.yaml.")
        sys.exit(1)

    logger.info("Firebase Local Console Importer starting")
    logger.info("Configured apps: %s", ", ".join(a.name for a in config.apps))

    with create_db_adapter(config) as db:
        db.ensure_schema()

        if should_skip_import(db, config.import_settings.interval_hours):
            return

        logger.info("Starting import cycle")
        for app in config.apps:
            try:
                import_app(app, config.import_settings, db)
            except Exception:
                logger.exception("Failed to import app: %s", app.name)

    logger.info("Import cycle complete")


if __name__ == "__main__":
    main()
