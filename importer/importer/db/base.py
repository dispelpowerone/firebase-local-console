"""Abstract database adapter interface for the Firebase Local Console importer."""

import logging
import time
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Retry settings — sensible defaults for a long-running service.
MAX_CONNECT_RETRIES = 12  # ~5 min total with exponential backoff
RETRY_BASE_DELAY = 5  # seconds
RETRY_MAX_DELAY = 60  # seconds
QUERY_RETRIES = 3


class DatabaseAdapter(ABC):
    """Base class for database adapters."""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def _connect(self) -> None:
        """Establish connection to the database (implementation)."""

    def connect(self) -> None:
        """Connect to the database, retrying with exponential backoff."""
        for attempt in range(1, MAX_CONNECT_RETRIES + 1):
            try:
                self._connect()
                return
            except Exception:
                if attempt == MAX_CONNECT_RETRIES:
                    raise
                delay = min(
                    RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY
                )
                logger.warning(
                    "Database connection failed (attempt %d/%d), retrying in %ds",
                    attempt,
                    MAX_CONNECT_RETRIES,
                    delay,
                )
                time.sleep(delay)

    @abstractmethod
    def close(self) -> None:
        """Close the database connection."""

    # ------------------------------------------------------------------
    # Transient-error retry
    # ------------------------------------------------------------------

    def _is_transient(self, exc: Exception) -> bool:
        """Return True if *exc* is a transient connection/network error.

        Subclasses should override to include adapter-specific error types.
        """
        return isinstance(exc, (ConnectionError, OSError))

    def _retry(self, fn: Callable[[], T]) -> T:
        """Execute *fn()* with automatic reconnection on transient errors."""
        for attempt in range(1, QUERY_RETRIES + 1):
            try:
                return fn()
            except Exception as exc:
                if not self._is_transient(exc) or attempt == QUERY_RETRIES:
                    raise
                logger.warning(
                    "Transient database error (attempt %d/%d), reconnecting: %s",
                    attempt,
                    QUERY_RETRIES,
                    exc,
                )
                try:
                    self.close()
                except Exception:
                    pass
                self._connect()
        raise RuntimeError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    @abstractmethod
    def ensure_schema(self) -> None:
        """Create tables and schemas if they don't already exist.

        This includes:
        - Analytics events table
        - Import tasks table (tracks planned and completed imports per dataset/date)
        """

    # ------------------------------------------------------------------
    # Import tasks
    # ------------------------------------------------------------------

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
    def get_pending_tasks(
        self, dataset: str
    ) -> list[tuple[date, datetime | None]]:
        """Get all pending (incomplete) tasks with their last attempt time.

        Args:
            dataset: The BigQuery dataset identifier.

        Returns:
            List of (event_date, updated_at) tuples for incomplete tasks,
            ordered by event_date.
        """

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @abstractmethod
    def insert_events(self, events: list[dict[str, Any]]) -> int:
        """Insert a batch of analytics events into the database.

        Args:
            events: List of flattened event dictionaries matching the analytics schema.

        Returns:
            Number of rows inserted.
        """

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
