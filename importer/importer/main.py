"""Firebase Local Console Importer — main entry point.

Imports Firebase Analytics data from BigQuery into ClickHouse.
Runs continuously with a sleep interval between import cycles.
Each date-task has its own cooldown so that a single successful import
does not block other dates from being processed.
"""

import logging
import signal
import sys
import threading
import time
from datetime import date, timedelta

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


def _backfill_date_range(backfill_days: int) -> list[date]:
    """Return all dates in the backfill window [today - N, yesterday]."""
    today = date.today()
    start = today - timedelta(days=backfill_days)
    return [start + timedelta(days=i) for i in range(backfill_days)]


def import_app(
    app: AppConfig,
    import_settings: ImportConfig,
    db: DatabaseAdapter,
) -> None:
    """Run a single import cycle for one app.

    1. Ensure task records exist for every date in the backfill window.
    2. Process eligible tasks — fetch events from BigQuery and insert into ClickHouse.
    """
    # Phase 1: Ensure tasks exist for every date in the backfill window
    backfill_dates = _backfill_date_range(import_settings.backfill_days)
    created = db.create_import_tasks(app.dataset, backfill_dates)
    if created:
        logger.info("[%s] Created %d new import task(s)", app.name, created)

    # Phase 2: Process eligible tasks (incomplete + not recently attempted)
    eligible = db.get_eligible_tasks(app.dataset, import_settings.interval_hours)
    if not eligible:
        logger.info("[%s] No eligible tasks (all completed or recently attempted)", app.name)
        return

    logger.info(
        "[%s] Processing %d eligible task(s): %s → %s",
        app.name,
        len(eligible),
        eligible[0],
        eligible[-1],
    )

    with BigQueryClient(app, import_settings) as bq_client:
        for event_date in eligible:
            try:
                events = bq_client.fetch_events(event_date)

                if events:
                    count = db.insert_events(events)
                    logger.info(
                        "[%s] Inserted %d events for %s", app.name, count, event_date
                    )
                    db.complete_import_task(app.dataset, event_date)
                else:
                    logger.info(
                        "[%s] No events for %s (will retry after cooldown)",
                        app.name,
                        event_date,
                    )
                    db.mark_task_attempted(app.dataset, event_date)
            except Exception:
                logger.exception("[%s] Failed to import %s", app.name, event_date)
                db.mark_task_attempted(app.dataset, event_date)


def _run_once(config: Config, db: DatabaseAdapter) -> None:
    """Run a single import cycle."""
    logger.info("Starting import cycle")
    for app in config.apps:
        try:
            import_app(app, config.import_settings, db)
        except Exception:
            logger.exception("Failed to import app: %s", app.name)

    logger.info("Import cycle complete")


def main() -> None:
    """Main entry point — runs import cycles in a loop."""
    config = load_config()

    if not config.apps:
        logger.error("No apps configured. Add apps to config.yaml.")
        sys.exit(1)

    shutdown_event = threading.Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        logger.info("Received signal %s — shutting down after current cycle", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    poll_seconds = config.import_settings.poll_interval_minutes * 60

    logger.info("Firebase Local Console Importer starting")
    logger.info("Configured apps: %s", ", ".join(a.name for a in config.apps))
    logger.info("Poll interval: %d minutes", config.import_settings.poll_interval_minutes)

    with create_db_adapter(config) as db:
        db.ensure_schema()

        while not shutdown_event.is_set():
            try:
                _run_once(config, db)
            except Exception:
                logger.exception("Unexpected error during import cycle")

            if shutdown_event.is_set():
                break

            logger.info("Sleeping %d seconds until next check", poll_seconds)
            shutdown_event.wait(poll_seconds)

    logger.info("Importer stopped")


if __name__ == "__main__":
    main()
