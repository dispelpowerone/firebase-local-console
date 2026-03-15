# firebase-grafana

Self-hosted Firebase Analytics monitoring stack. Periodically imports event data from BigQuery into a local database and visualizes it with pre-built Grafana dashboards.

```
BigQuery (Firebase exports) ──▶ Importer (Python/uv) ──▶ ClickHouse or DuckDB ◀── Grafana
```

Runs anywhere via Docker Compose — cloud VMs, home servers, Raspberry Pi.

## Prerequisites

- Docker and Docker Compose v2+
- A GCP service account with BigQuery read access (`roles/bigquery.dataViewer`)
- Firebase Analytics BigQuery export enabled ([instructions](https://support.google.com/firebase/answer/6318039))

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url> && cd firebase-grafana
cp config/config.example.yaml config/config.yaml
cp .env.example .env
```

Edit `config/config.yaml` with your GCP project and Firebase app datasets:

```yaml
gcp:
  project_id: "my-gcp-project"
  credentials_file: "/app/credentials/service-account.json"

apps:
  - name: "My Android App"
    dataset: "analytics_123456789"
  - name: "My iOS App"
    dataset: "analytics_987654321"
```

### 2. Add GCP credentials

Place your service account JSON key in a `credentials/` directory:

```bash
mkdir -p credentials
cp /path/to/your/service-account.json credentials/
```

### 3. Start the stack

**With ClickHouse** (recommended for powerful servers):

```bash
docker compose -f docker-compose.yml -f docker-compose.clickhouse.yml up -d
```

**With DuckDB** (lightweight, great for Raspberry Pi):

```bash
docker compose -f docker-compose.yml -f docker-compose.duckdb.yml up -d
```

### 4. Open Grafana

Navigate to `http://localhost:3000` (default credentials: `admin` / `admin`).

Pre-built dashboards are available under the **Firebase** folder:
- **Overview** — DAU, MAU, new users, event volume, platform/country breakdown
- **Events Deep Dive** — per-event trends, screen breakdown, device/OS analysis

## Project Structure

```
firebase-grafana/
├── docker-compose.yml              # Base: importer + grafana
├── docker-compose.clickhouse.yml   # Overlay: adds ClickHouse
├── docker-compose.duckdb.yml       # Overlay: adds DuckDB
├── importer/                       # Python service (managed with uv)
│   ├── pyproject.toml / uv.lock
│   ├── main.py                     # Entry point + scheduler
│   ├── config.py                   # Config loader (YAML + env vars)
│   ├── bigquery_client.py          # BQ data fetching
│   ├── db/
│   │   ├── base.py                 # Abstract DB interface
│   │   ├── clickhouse.py           # ClickHouse adapter
│   │   └── duckdb.py               # DuckDB adapter
│   └── schemas/
│       └── analytics.py            # Firebase Analytics schema mapping
├── db/
│   ├── clickhouse/                 # ClickHouse Dockerfile + configs
│   └── duckdb/                     # DuckDB Dockerfile + init SQL
├── grafana/
│   ├── Dockerfile
│   ├── provisioning/               # Auto-configured datasources
│   └── dashboards/                 # Pre-built dashboard JSONs
└── config/
    └── config.example.yaml
```

## Configuration

Configuration is loaded from `config/config.yaml` with environment variable overrides. Key env vars (set in `.env`):

| Variable | Default | Description |
|---|---|---|
| `GCP_PROJECT_ID` | — | GCP project containing BigQuery datasets |
| `DB_TYPE` | `clickhouse` | Database engine (`clickhouse` or `duckdb`) |
| `IMPORT_INTERVAL_HOURS` | `6` | Hours between import cycles |
| `GRAFANA_PORT` | `3000` | Host port for Grafana UI |
| `GF_SECURITY_ADMIN_PASSWORD` | `admin` | Grafana admin password |
| `CLICKHOUSE_DATABASE` | `firebase` | ClickHouse database name |
| `SA_KEY_FILENAME` | `service-account.json` | Service account key filename |

## How It Works

1. **Firebase** exports analytics events to BigQuery as day-sharded tables (`events_YYYYMMDD`)
2. **Importer** runs on a schedule, checks the last imported date per dataset, and fetches only new days
3. Events are flattened from BigQuery's nested schema into a columnar format optimized for analytics
4. **Grafana** queries the local database directly for dashboard visualizations

### Data Flow

- First run: backfills the last 30 days (configurable via `import.backfill_days`)
- Subsequent runs: incrementally imports only new days since the last watermark
- Import progress is tracked in an `import_watermarks` table in the local DB

## Adding New Apps

Add entries to the `apps` list in `config/config.yaml`:

```yaml
apps:
  - name: "New App"
    dataset: "analytics_<firebase_property_id>"
```

Find your Firebase property ID in the Firebase Console under Project Settings → Integrations → BigQuery.

Then restart the importer:

```bash
docker compose restart importer
```

## ClickHouse vs DuckDB

| | ClickHouse | DuckDB |
|---|---|---|
| **Best for** | Powerful servers, large datasets | Raspberry Pi, small deployments |
| **RAM** | 1-2 GB minimum | ~100 MB |
| **Architecture** | Client-server | Embedded (shared volume) |
| **Grafana plugin** | `grafana-clickhouse-datasource` | Requires HTTP API layer |
| **ARM support** | ✅ arm64 builds available | ✅ Python arm64 |

## Extending

The project is designed for easy extension:

- **New data sources**: Add schemas in `importer/schemas/` (e.g., `crashlytics.py`, `performance.py`)
- **New DB backends**: Implement `DatabaseAdapter` in `importer/db/`
- **Custom dashboards**: Add JSON files to `grafana/dashboards/`

## Development

```bash
cd importer
uv sync           # Install dependencies
uv run python -m importer.main  # Run locally
```

## License

MIT
