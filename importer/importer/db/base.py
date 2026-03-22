"""Abstract database adapter interface for the Firebase Local Console importer."""

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any


class DatabaseAdapter(ABC):
    """Base class for database adapters."""

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
    def get_last_import_time(self) -> datetime | None:
        """Get the most recent import timestamp across all datasets.

        Returns:
            The most recent updated_at value, or None if no imports have occurred.
        """

    @abstractmethod
    def insert_events(self, events: list[dict[str, Any]]) -> int:
        """Insert a batch of analytics events into the database.

        Args:
            events: List of flattened event dictionaries matching the analytics schema.

        Returns:
            Number of rows inserted.
        """

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
