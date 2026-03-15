"""Abstract database adapter interface for the Firebase-Grafana importer."""

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class DatabaseAdapter(ABC):
    """Base class for database adapters.

    All database backends (ClickHouse, DuckDB) must implement this interface.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the database."""

    @abstractmethod
    def close(self) -> None:
        """Close the database connection."""

    @abstractmethod
    def ensure_schema(self) -> None:
        """Create tables and schemas if they don't already exist.

        This includes:
        - Analytics events table
        - Import watermark table (tracks last imported date per dataset)
        """

    @abstractmethod
    def get_last_imported_date(self, dataset: str) -> date | None:
        """Get the last successfully imported date for a dataset.

        Args:
            dataset: The BigQuery dataset identifier (e.g., 'analytics_123456789').

        Returns:
            The last imported date, or None if no data has been imported yet.
        """

    @abstractmethod
    def set_last_imported_date(self, dataset: str, dt: date) -> None:
        """Update the import watermark for a dataset.

        Args:
            dataset: The BigQuery dataset identifier.
            dt: The date that was just successfully imported.
        """

    @abstractmethod
    def insert_events(self, events: list[dict[str, Any]]) -> int:
        """Insert a batch of analytics events into the database.

        Args:
            events: List of flattened event dictionaries matching the analytics schema.

        Returns:
            Number of rows inserted.
        """

    @abstractmethod
    def delete_events(self, dataset: str, event_date: date) -> int:
        """Delete all events for a given dataset and date.

        Used before inserting to prevent duplicates on retries or re-imports.

        Args:
            dataset: The BigQuery dataset identifier.
            event_date: The date whose events should be deleted.

        Returns:
            Number of rows deleted.
        """

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
