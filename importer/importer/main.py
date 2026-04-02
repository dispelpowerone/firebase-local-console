"""Firebase Local Console Importer — main entry point.

Imports Firebase Analytics data from BigQuery into ClickHouse.
Runs continuously with a sleep interval between import cycles,
checking the last successful import time to respect the configured cooldown.
"""

import logging
import signal
import sys
import threading
import time
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
        next_import = last_import + timedelta(hours=interval_hours)
        remaining = next_import - datetime.now(tz=timezone.utc)
        total_seconds = int(remaining.total_seconds())
        hours, remainder = divmod(max(total_seconds, 0), 3600)
        minutes = remainder // 60
        logger.info(
            "Last import was at %s (<%dh ago) — skipping, next import in %dh %dm (at %s)",
            last_import.isoformat(),
            interval_hours,
            hours,
            minutes,
            next_import.isoformat(),
        )
        return True
    return False


def import_app(
    app: AppConfig,
    import_settings: ImportConfig,
    db: DatabaseAdapter,
) -> None:
    """Run a single import cycle for one app using its own BQ credentials.

    Uses a two-phase approach:
    1. Plan — discover dates to import and record them as pending tasks.
    2. Execute — fetch and insert data for each pending task, marking it complete.

    On resume after interruption, pending tasks are read directly from the
    database without needing to query BigQuery again.
    """
    # Phase 1: Check for pending tasks from a previous interrupted run
    pending = db.get_pending_tasks(app.dataset)
    if pending:
        logger.info(
            "[%s] Resuming %d pending task(s) from previous run: %s → %s",
            app.name,
            len(pending),
            pending[0],
            pending[-1],
        )
    else:
        # No pending tasks — query BigQuery for new dates
        last_completed = db.get_last_completed_date(app.dataset)
        if last_completed:
            logger.info("[%s] Last completed date: %s", app.name, last_completed)
        else:
            logger.info("[%s] No previous import — will backfill", app.name)

        with BigQueryClient(app, import_settings) as bq_client:
            new_dates = bq_client.get_dates_to_import(last_completed)

        if not new_dates:
            logger.info("[%s] No new data to import", app.name)
            return

        created = db.create_import_tasks(app.dataset, new_dates)
        logger.info("[%s] Planned %d new import task(s)", app.name, created)
        pending = db.get_pending_tasks(app.dataset)

    if not pending:
        logger.info("[%s] Nothing to import", app.name)
        return

    logger.info(
        "[%s] Importing %d day(s): %s → %s",
        app.name,
        len(pending),
        pending[0],
        pending[-1],
    )

    # Phase 2: Execute pending tasks
    with BigQueryClient(app, import_settings) as bq_client:
        for event_date in pending:
            try:
                events = bq_client.fetch_events(event_date)

                if events:
                    count = db.insert_events(events)
                    logger.info(
                        "[%s] Inserted %d events for %s", app.name, count, event_date
                    )
                else:
                    logger.info("[%s] No events for %s", app.name, event_date)

                db.complete_import_task(app.dataset, event_date)
            except Exception:
                logger.exception("[%s] Failed to import %s", app.name, event_date)
                break


def _run_once(config: Config, db: DatabaseAdapter) -> None:
    """Run a single import cycle."""
    if should_skip_import(db, config.import_settings.interval_hours):
        return

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
