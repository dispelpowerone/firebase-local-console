from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from importer.bigquery_client import BigQueryClient
from importer.config import AppConfig, Config, ImportConfig
from importer.main import _run_once


class _TimeoutJob:
    def __init__(self) -> None:
        self.page_size: int | None = None
        self.result_timeout: int | None = None
        self.cancel_timeout: int | None = None

    def result(self, *, page_size: int, timeout: int) -> list[object]:
        self.page_size = page_size
        self.result_timeout = timeout
        raise FuturesTimeoutError()

    def cancel(self, *, timeout: int) -> bool:
        self.cancel_timeout = timeout
        return True


class _QueryClient:
    def __init__(self, job: _TimeoutJob) -> None:
        self.job = job
        self.query_timeout: int | None = None

    def query(self, query: str, *, timeout: int) -> _TimeoutJob:
        self.query_timeout = timeout
        return self.job


class _Database:
    def __init__(self, eligible_by_dataset: dict[str, list[date]]) -> None:
        self.eligible_by_dataset = eligible_by_dataset
        self.attempted: list[tuple[str, date]] = []
        self.completed: list[tuple[str, date]] = []

    def create_import_tasks(self, dataset: str, dates: list[date]) -> int:
        return 0

    def get_pending_tasks(self, dataset: str) -> list[tuple[date, object]]:
        return []

    def get_eligible_tasks(self, dataset: str, interval_hours: int) -> list[date]:
        return self.eligible_by_dataset[dataset]

    def insert_events(self, events: list[object]) -> int:
        return len(events)

    def complete_import_task(self, dataset: str, event_date: date) -> None:
        self.completed.append((dataset, event_date))

    def mark_task_attempted(self, dataset: str, event_date: date) -> None:
        self.attempted.append((dataset, event_date))


class _PerAppBigQueryClient:
    def __init__(self, app: AppConfig, import_settings: ImportConfig) -> None:
        self.app = app

    def __enter__(self) -> "_PerAppBigQueryClient":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> bool:
        return False

    def fetch_events(self, event_date: date) -> list[object]:
        if self.app.name == "blocked":
            raise FuturesTimeoutError()
        return [{}]


def _app(name: str, dataset: str) -> AppConfig:
    return AppConfig(
        name=name,
        project_id="project",
        credentials_file="credentials.json",
        dataset=dataset,
    )


class BigQueryTimeoutTests(TestCase):
    def test_fetch_events_times_out_and_cancels_the_query_job(self) -> None:
        settings = ImportConfig(batch_size=123, bigquery_timeout_seconds=17)
        client = BigQueryClient(_app("app", "analytics_1"), settings)
        job = _TimeoutJob()
        query_client = _QueryClient(job)
        client.client = query_client

        with self.assertRaises(FuturesTimeoutError):
            client.fetch_events(date(2026, 8, 27))

        self.assertEqual(query_client.query_timeout, 17)
        self.assertEqual(job.page_size, 123)
        self.assertEqual(job.result_timeout, 17)
        self.assertEqual(job.cancel_timeout, 17)

    def test_timeout_for_one_app_does_not_prevent_a_later_app_from_completing(
        self,
    ) -> None:
        blocked = _app("blocked", "analytics_blocked")
        healthy = _app("healthy", "analytics_healthy")
        event_date = date(2026, 8, 27)
        database = _Database(
            {
                blocked.dataset: [event_date],
                healthy.dataset: [event_date],
            }
        )
        config = Config(
            apps=[blocked, healthy],
            import_settings=ImportConfig(bigquery_timeout_seconds=17),
        )

        with patch("importer.main.BigQueryClient", _PerAppBigQueryClient):
            _run_once(config, database)

        self.assertEqual(database.attempted, [(blocked.dataset, event_date)])
        self.assertEqual(database.completed, [(healthy.dataset, event_date)])
