# Firebase Local Console

Self-hosted Firebase Analytics stack that syncs event data from BigQuery into ClickHouse and visualizes it with 18+ pre-built Grafana dashboards. One `docker compose up` gives you a full analytics console — faster, more flexible, and fully under your control.

```
BigQuery (Firebase exports) ──▶ Importer (Python) ──▶ ClickHouse ◀── Grafana
```

## Why

The Firebase Console provides basic analytics but limits you to predefined reports, slow queries, and Google-controlled data retention. Firebase Local Console addresses this by putting the same data on your infrastructure with a proper analytics engine:

- **Sub-second queries** — ClickHouse is a columnar database built for analytical workloads; complex queries over millions of events return instantly
- **18 pre-built dashboards** — retention cohorts, revenue breakdowns, ad monetization, session analytics, and more — including reports the Firebase Console doesn't offer
- **Multi-app in one place** — monitor all your Firebase apps (Android, iOS, Web) from a unified dashboard instead of switching between projects
- **Full Grafana ecosystem** — alerting (Slack, PagerDuty, email), annotations, custom dashboards, team sharing, and API access
- **Self-hosted** — your analytics data stays on your infrastructure; runs on cloud VMs, bare metal, or a Raspberry Pi
- **Zero ongoing cost** — no per-query charges, no seat licenses, no usage tiers

## Dashboards

Pre-built dashboards ship ready to use and are organized into three groups.

**Core**

| Dashboard | Description |
|---|---|
| Overview | DAU, MAU, new users, platform and country breakdown |
| Events Deep Dive | Per-event trends, screen breakdown, device and OS analysis |
| Platform Comparison | Side-by-side Android vs iOS vs Web metrics |
| Import Monitor | Daily event volume, top events, import task health |

**Native Analytics** — mirrors and extends standard Firebase Console reports

| Dashboard | Description |
|---|---|
| Acquisition | Install sources, campaign performance, first-open funnels |
| App Lifecycle | App updates, first opens, engagement across versions |
| Audience Overview | User demographics, interests, and segments |
| Device & Geo | Device models, OS versions, screen resolutions, countries |
| Retention Cohorts | Day-N retention heatmaps and trend lines |
| Revenue | In-app purchase and ad revenue tracking |
| Session Analytics | Session duration, screens per session, bounce rates |

**Custom Insights** — analytics not available in the Firebase Console

| Dashboard | Description |
|---|---|
| Ad Monetization | Ad impressions, eCPM, fill rates by ad unit |
| Content Engagement | Content views, shares, completion rates |
| Errors & Health | Crashes, ANRs, error events by version |
| IAP Funnel | Purchase funnel from view to cart to purchase |
| Navigation Flow | Screen-to-screen navigation patterns |
| Test Funnel & Types | A/B test results and experiment analysis |

## Prerequisites

- Docker and Docker Compose v2+
- A GCP service account with BigQuery read access (`roles/bigquery.dataViewer`)
- Firebase Analytics BigQuery export enabled ([instructions](https://support.google.com/firebase/answer/6318039))

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url> && cd firebase-local-console
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

```bash
docker compose up -d
```

### 4. Open Grafana

Navigate to `http://localhost:3000` (default credentials: `admin` / `admin`).

All pre-built dashboards are available under the **Firebase** folder.

## Project Structure

```
firebase-local-console/
├── docker-compose.yml              # Full stack: ClickHouse + importer + Grafana
├── importer/                       # Python service (managed with uv)
│   ├── pyproject.toml / uv.lock
│   ├── main.py                     # Continuous import loop with cooldown check
│   ├── config.py                   # Config loader (YAML + env vars)
│   ├── bigquery_client.py          # BQ data fetching
│   ├── db/
│   │   ├── base.py                 # Abstract DB interface
│   │   └── clickhouse.py           # ClickHouse adapter
│   └── schemas/
│       └── analytics.py            # Firebase Analytics schema mapping
├── db/
│   └── clickhouse/                 # ClickHouse Dockerfile + configs
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
| `GRAFANA_PORT` | `3000` | Host port for Grafana UI |
| `GF_SECURITY_ADMIN_PASSWORD` | `admin` | Grafana admin password |
| `CLICKHOUSE_DATABASE` | `firebase` | ClickHouse database name |
| `IMPORT_INTERVAL_HOURS` | `6` | Minimum hours between import cycles |
| `POLL_INTERVAL_MINUTES` | `10` | How often to check for new data |

## How It Works

1. **Firebase** exports analytics events to BigQuery as day-sharded tables (`events_YYYYMMDD`)
2. **Importer** runs a continuous loop, polling every `poll_interval_minutes` (default 10 min). On each poll it ensures import tasks exist for every available date within the backfill window
3. It then processes eligible tasks — those not yet completed and not attempted within the last `interval_hours` (default 6h). Each task has its own cooldown so one successful import never blocks others
4. **Grafana** queries ClickHouse directly for dashboard visualizations

### Data Flow

- Each cycle: discovers available BigQuery tables within the backfill window (`backfill_days`, default 30 days) and creates task records for any new dates
- Tasks with data are marked completed; tasks with no data are retried after the cooldown period
- Import progress is tracked per-date in an `import_tasks` table in ClickHouse

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

## Extending

The project is designed for easy extension:

- **New data sources**: Add schemas in `importer/schemas/` (e.g., `crashlytics.py`, `performance.py`)
- **Custom dashboards**: Add JSON files to `grafana/dashboards/`

## Development

```bash
cd importer
uv sync           # Install dependencies
uv run python -m importer.main  # Run locally
```

## License

MIT
