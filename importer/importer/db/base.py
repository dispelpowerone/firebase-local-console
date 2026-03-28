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
        - Import tasks table (tracks planned and completed imports per dataset/date)
        """

    @abstractmethod
    def get_pending_tasks(self, dataset: str) -> list[date]:
        """Get dates that were planned but not yet completed for a dataset.

        Args:
            dataset: The BigQuery dataset identifier (e.g., 'analytics_123456789').

        Returns:
            List of event dates with no completion timestamp, in chronological order.
        """

    @abstractmethod
    def create_import_tasks(self, dataset: str, dates: list[date]) -> int:
        """Create import task records for the given dates.

        Only creates tasks for dates that don't already have a pending or completed
        record. Each task starts with completed_at unset.

        Args:
            dataset: The BigQuery dataset identifier.
            dates: List of event dates to plan for import.

        Returns:
            Number of new task records created.
        """

    @abstractmethod
    def complete_import_task(self, dataset: str, event_date: date) -> None:
        """Mark an import task as completed by setting its completion timestamp.

        Args:
            dataset: The BigQuery dataset identifier.
            event_date: The date that was just successfully imported.
        """

    @abstractmethod
    def get_last_completed_date(self, dataset: str) -> date | None:
        """Get the most recently completed import date for a dataset.

        Args:
            dataset: The BigQuery dataset identifier.

        Returns:
            The latest event_date with a completion timestamp, or None.
        """

    @abstractmethod
    def get_last_import_time(self) -> datetime | None:
        """Get the most recent completion timestamp across all datasets.

        Returns:
            The most recent completed_at value, or None if no imports have completed.
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
