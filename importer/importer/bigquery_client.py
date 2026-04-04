"""BigQuery client for fetching Firebase Analytics data."""

import logging
from datetime import date
from typing import Any

from google.cloud import bigquery
from google.oauth2 import service_account

from importer.config import AppConfig, ImportConfig
from importer.schemas.analytics import flatten_event, get_bigquery_sql

logger = logging.getLogger(__name__)


class BigQueryClient:
    """Client for reading Firebase Analytics data from BigQuery.

    Each instance is scoped to a single app/project with its own credentials.
    """

    def __init__(self, app: AppConfig, import_settings: ImportConfig):
        self.app = app
        self.import_settings = import_settings
        self.client: bigquery.Client | None = None

    def connect(self) -> None:
        """Initialize the BigQuery client with the app's service account credentials."""
        if self.app.credentials_file:
            credentials = service_account.Credentials.from_service_account_file(
                self.app.credentials_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self.client = bigquery.Client(
                project=self.app.project_id,
                credentials=credentials,
            )
        else:
            self.client = bigquery.Client(project=self.app.project_id)

    def close(self) -> None:
        if self.client:
            self.client.close()
            self.client = None

    def list_available_dates(self) -> list[date]:
        """List all available date-sharded tables in the app's dataset.

        Returns:
            Sorted list of dates for which tables exist.
        """
        assert self.client is not None
        dataset_ref = f"{self.app.project_id}.{self.app.dataset}"
        prefix = self.app.table_prefix

        tables = self.client.list_tables(dataset_ref)
        dates = []
        for table in tables:
            if table.table_id.startswith(prefix):
                date_str = table.table_id[len(prefix) :]
                try:
                    dt = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
                    dates.append(dt)
                except (ValueError, IndexError):
                    continue
        return sorted(dates)

    def fetch_events(self, event_date: date) -> list[dict[str, Any]]:
        """Fetch and flatten all events for a specific date.

        Args:
            event_date: The date to fetch events for.

        Returns:
            List of flattened event dictionaries.
        """
        assert self.client is not None
        date_str = event_date.strftime("%Y%m%d")
        table_ref = (
            f"{self.app.project_id}.{self.app.dataset}"
            f".{self.app.table_prefix}{date_str}"
        )

        query = get_bigquery_sql(table_ref)
        logger.info("Fetching events from %s", table_ref)

        job = self.client.query(query)
        results = job.result(page_size=self.import_settings.batch_size)

        events = []
        for row in results:
            flat = flatten_event(dict(row), self.app.dataset)
            events.append(flat)

        logger.info("Fetched %d events from %s", len(events), table_ref)
        return events

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
