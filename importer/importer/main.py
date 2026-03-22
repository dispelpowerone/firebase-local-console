"""Firebase-Grafana Importer — main entry point.

Periodically imports Firebase Analytics data from BigQuery into a local database.
"""

import logging
import sys
import time
from datetime import date

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
                # Stop this app's import on failure; next cycle will retry from this date
                break


def run_import_cycle(config: Config) -> None:
    """Run one full import cycle for all configured apps."""
    logger.info("Starting import cycle")

    with create_db_adapter(config) as db:
        db.ensure_schema()

        for app in config.apps:
            try:
                import_app(app, config.import_settings, db)
            except Exception:
                logger.exception("Failed to import app: %s", app.name)

    logger.info("Import cycle complete")


def main() -> None:
    """Main entry point — runs the import loop on a schedule."""
    config = load_config()

    if not config.apps:
        logger.error("No apps configured. Add apps to config.yaml.")
        sys.exit(1)

    logger.info("Firebase-Grafana Importer starting")
    logger.info("Import interval: %d hours", config.import_settings.interval_hours)
    logger.info("Configured apps: %s", ", ".join(a.name for a in config.apps))

    # Run first import immediately
    run_import_cycle(config)

    # Then loop on schedule
    interval_seconds = config.import_settings.interval_hours * 3600
    while True:
        logger.info("Next import in %d hours", config.import_settings.interval_hours)
        time.sleep(interval_seconds)
        run_import_cycle(config)


if __name__ == "__main__":
    main()
