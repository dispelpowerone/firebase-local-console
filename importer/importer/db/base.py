"""Abstract database adapter interface for the Firebase Local Console importer."""

from abc import ABC, abstractmethod
from datetime import date
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
    def create_import_tasks(self, dataset: str, dates: list[date]) -> int:
        """Create import task records for the given dates.

        Only creates tasks for dates that don't already have a pending or completed
        record. Each task starts with completed_at and updated_at unset.

        Args:
            dataset: The BigQuery dataset identifier.
            dates: List of event dates to plan for import.

        Returns:
            Number of new task records created.
        """

    @abstractmethod
    def get_eligible_tasks(self, dataset: str, interval_hours: int) -> list[date]:
        """Get incomplete tasks eligible for processing.

        Returns tasks that are not yet completed AND have not been attempted
        within the last ``interval_hours`` hours (or have never been attempted).

        Args:
            dataset: The BigQuery dataset identifier.
            interval_hours: Cooldown period in hours per task.

        Returns:
            List of event dates eligible for import, in chronological order.
        """

    @abstractmethod
    def complete_import_task(self, dataset: str, event_date: date) -> None:
        """Mark an import task as completed.

        Sets both completed_at and updated_at to the current time.

        Args:
            dataset: The BigQuery dataset identifier.
            event_date: The date that was just successfully imported.
        """

    @abstractmethod
    def mark_task_attempted(self, dataset: str, event_date: date) -> None:
        """Record an import attempt without marking the task complete.

        Sets updated_at to the current time so the task is not retried
        until the cooldown period elapses.

        Args:
            dataset: The BigQuery dataset identifier.
            event_date: The date that was attempted.
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
