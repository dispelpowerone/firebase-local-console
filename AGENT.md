# Agent Guide

This document helps AI agents quickly understand the project without
needing to explore files individually.

## What This Project Is

Firebase Local Console is a self-hosted analytics stack that syncs
Firebase Analytics event data from BigQuery into ClickHouse and
visualizes it with pre-built Grafana dashboards.

```
BigQuery (Firebase exports) ──▶ Importer (Python) ──▶ ClickHouse ◀── Grafana
```

All three services run via Docker Compose on a single bridge network
(`firebase-net`). Services reference each other by container name:
`clickhouse`, `importer`, `grafana`.

## Project Layout

```
firebase-local-console/
├── docker-compose.yml          # Orchestrates all 3 services
├── .env / .env.example         # Environment variable overrides
├── config/
│   └── config.yaml             # App list, event macros, import settings
├── credentials/                # GCP service account JSON keys (gitignored)
├── data/                       # ClickHouse data volume (gitignored)
├── db/clickhouse/
│   ├── Dockerfile              # clickhouse/clickhouse-server:latest + config
│   ├── config.xml              # Server settings (listen 0.0.0.0, memory limits)
│   └── users.xml               # Default user, no password, access_management=1
├── importer/
│   ├── Dockerfile              # python:3.12-slim + uv package manager
│   ├── pyproject.toml          # Dependencies: clickhouse-driver, google-cloud-bigquery, pyyaml
│   ├── uv.lock
│   └── importer/
│       ├── __main__.py         # Entry point
│       ├── main.py             # Continuous import loop with per-task cooldown
│       ├── config.py           # Loads config.yaml + env var overrides
│       ├── bigquery_client.py  # Reads day-sharded BQ tables (events_YYYYMMDD)
│       ├── schemas/
│       │   └── analytics.py    # BQ→CH schema mapping, event flattening, SQL
│       └── db/
│           ├── base.py         # Abstract DatabaseAdapter interface
│           └── clickhouse.py   # ClickHouse adapter (TCP native, retries, migrations)
└── grafana/
    ├── Dockerfile              # Multi-stage: injects variables then builds Grafana image
    ├── inject-variables.py     # Build-time script: injects app_dataset dropdown + event macros
    ├── provisioning/
    │   ├── datasources/
    │   │   └── clickhouse.yml  # Native protocol, host=clickhouse, port=9000, db=firebase
    │   └── dashboards/
    │       └── dashboards.yml  # File-based provisioning, foldersFromFilesStructure
    └── dashboards/
        ├── General/            # Core + native Firebase analytics
        └── Custom/             # Custom insights not in Firebase Console
```

## ClickHouse Schema

Database: `firebase` (created by importer on first run).

### `analytics_events` (MergeTree)

Partitioned by `toYYYYMM(event_date)`, ordered by
`(event_date, event_name, user_pseudo_id, event_timestamp)`.

| Column Group | Key Columns |
|---|---|
| Event core | `event_date` (Date), `event_timestamp` (DateTime64(6)), `event_name` (String), `event_bundle_sequence_id` (Int64) |
| User | `user_id` (Nullable(String)), `user_pseudo_id` (String), `user_first_touch_timestamp` (Nullable(DateTime64(6))) |
| Device | `device_category`, `device_mobile_brand_name`, `device_mobile_model_name`, `device_operating_system`, `device_operating_system_version`, `device_language` — all Nullable(String) |
| Geo | `geo_country`, `geo_region`, `geo_city` — all Nullable(String) |
| App | `app_info_version`, `app_info_install_source` — Nullable(String) |
| Platform | `platform` (Nullable(String)), `stream_id` (Nullable(String)) |
| Extracted params | `param_page_title` (Nullable(String)), `param_screen_class` (Nullable(String)), `param_engagement_time_msec` (Int64), `param_ga_session_id` (Int64), `param_value` (Float64), `param_currency` (Nullable(String)) |
| Raw params | `event_params_json` (Nullable(String)) — full event_params as JSON |
| Import metadata | `import_dataset` (String), `imported_at` (DateTime) |

### `import_tasks` (ReplacingMergeTree)

Ordered by `(dataset, event_date)`, versioned by `created_at`.

| Column | Type | Purpose |
|---|---|---|
| `dataset` | String | BigQuery dataset identifier |
| `event_date` | Date | Date being imported |
| `created_at` | DateTime | Task creation time |
| `completed_at` | Nullable(DateTime) | When import finished (NULL = incomplete) |
| `updated_at` | Nullable(DateTime) | Last attempt time (cooldown tracking) |

## Grafana Dashboards

Dashboard JSON files, all using the `grafana-clickhouse-datasource`
plugin with datasource UID `clickhouse`.

### SQL conventions

- **Use CTEs** for any query with subqueries or multiple logical steps.
  Write `WITH ... AS (...)` instead of nested inline subqueries.
- **Uniform formatting** — all SQL queries must follow consistent pretty
  formatting: uppercase keywords (`SELECT`, `FROM`, `WHERE`, `GROUP BY`,
  `ORDER BY`, `WITH`, `AS`, `LEFT JOIN`, `ON`, `AND`, `HAVING`, etc.),
  2-space indentation for column lists and conditions, one clause per
  line. Keep the same style across all dashboard panels.

### Dashboard conventions

- Every dashboard query filters by `import_dataset = '${app_dataset}'`
  where `app_dataset` is a Grafana template variable (injected at build time).
- Date filtering uses `event_date >= toDate('${__from:date:YYYY-MM-DD}')`.
- Comparison dashboards (app-vs-app, version-vs-version, ios-vs-android)
  use dual variables: `app_dataset_a` / `app_dataset_b`.
- Event name placeholders like `__ADS_INTERSTITIAL_DISPLAYED__` are
  replaced at Docker build time by `inject-variables.py` with SQL-ready
  quoted comma-separated lists from `config.yaml`.
- Queries are ClickHouse SQL stored in `rawSql` fields as escaped strings
  with `\n` newlines.

### Dashboard files

**General/**: `acquisition.json`, `app-lifecycle.json`, `app-vs-app.json`,
`app-vs-app-events.json`, `audience-overview.json`, `device-geo.json`,
`events-deep-dive.json`, `import.json`, `overview.json`,
`retention-cohorts.json`, `revenue.json`, `session-analytics.json`,
`version-vs-version-events.json`, `version-vs-version.json`

**Custom/**: `ad-monetization.json`, `content-engagement.json`,
`errors-health.json`, `iap-funnel.json`, `ios-vs-android.json`,
`navigation.json`, `results-progress.json`, `test-funnel.json`,
`test-types.json`

## Configuration

### config/config.yaml

```yaml
apps:                               # Firebase apps to import
  - name: "My App"
    project_id: "gcp-project-id"
    credentials_file: "/app/credentials/sa.json"
    dataset: "analytics_123456789"
    # table_prefix: "events_"       # Optional, default "events_"

events:                             # Event name macros for dashboards
  ads:
    interstitial:
      displayed: custom_ads_event_displayed
  errors:
    ads: [custom_ads_init_failed, ...]
    iap: [custom_iap_init_failed, ...]

import:
  interval_hours: 6                 # Cooldown between import attempts per task
  poll_interval_minutes: 10         # Loop sleep between cycles
  backfill_days: 30                 # Days to look back
  batch_size: 10000                 # BigQuery page size

database:
  clickhouse:
    host: "clickhouse"
    port: 9000
    http_port: 8123
    database: "firebase"
    user: "default"
    password: ""
```

### Environment variables (.env)

| Variable | Default | Description |
|---|---|---|
| `CLICKHOUSE_DATABASE` | `firebase` | Database name |
| `CLICKHOUSE_USER` | `default` | ClickHouse user |
| `CLICKHOUSE_PASSWORD` | *(empty)* | ClickHouse password |
| `CLICKHOUSE_HOST` | `clickhouse` | Hostname (set in docker-compose) |
| `CLICKHOUSE_PORT` | `9000` | Native TCP port |
| `CLICKHOUSE_HTTP_PORT` | `8123` | HTTP port (exposed to host) |
| `CLICKHOUSE_NATIVE_PORT` | `9000` | Native port (exposed to host) |
| `GRAFANA_PORT` | `3000` | Grafana UI port |
| `GF_SECURITY_ADMIN_PASSWORD` | `admin` | Grafana admin password |
| `CONFIG_PATH` | `/app/config/config.yaml` | Config file path (importer) |
| `IMPORT_INTERVAL_HOURS` | `6` | Override import cooldown |
| `POLL_INTERVAL_MINUTES` | `10` | Override poll interval |
| `DB_TYPE` | `clickhouse` | Database backend |

## Development

```bash
# Importer (Python 3.12, managed with uv)
cd importer
uv sync
uv run python -m importer.main

# Dev dependency: black (formatter)

# Full stack
docker compose up -d

# Validate ClickHouse queries (HTTP API on port 8123)
curl 'http://localhost:8123/' --data-binary "EXPLAIN SYNTAX <query>"

# Validate dashboard JSON
python3 -c "import json; json.load(open('path/to/dashboard.json'))"
```

## Common Agent Tasks

- **Edit a dashboard query**: Find the panel by `title` in the dashboard
  JSON, edit the `rawSql` field. Validate JSON after editing and verify
  the query with `EXPLAIN SYNTAX` on ClickHouse (port 8123).
- **Add a new dashboard**: Create a JSON file in `grafana/dashboards/General/`
  or `grafana/dashboards/Custom/`. Use existing dashboards as templates.
  Ensure the `app_dataset` template variable is used for filtering.
- **Change the ClickHouse schema**: Edit `importer/importer/db/clickhouse.py`
  (`ensure_schema` method). Add a migration method if altering an
  existing table.
- **Add event macros**: Edit `config/config.yaml` under `events:`. The
  macro names are auto-generated from the YAML path (e.g.,
  `events.errors.ads` → `__ERRORS_ADS__`). Rebuild the Grafana image
  after changes.
