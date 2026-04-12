# --- Stage 1: inject template variables into dashboard JSON files ---
FROM python:3-alpine AS builder

RUN pip install --no-cache-dir pyyaml

WORKDIR /build
COPY config/config.yaml /build/config.yaml
COPY grafana/dashboards/ /build/dashboards/
COPY grafana/inject-variables.py /build/

RUN find /build/dashboards -name '*.json' -printf '%h\n' | sort -u | \
    while read dir; do python inject-variables.py /build/config.yaml "$dir"; done

# --- Stage 2: final Grafana image ---
FROM grafana/grafana:latest

# Install ClickHouse datasource plugin
RUN grafana cli plugins install grafana-clickhouse-datasource

# Copy provisioning configs
COPY grafana/provisioning/ /etc/grafana/provisioning/

# Copy processed dashboards (with injected variables) from builder
COPY --from=builder /build/dashboards/ /var/lib/grafana/dashboards/
