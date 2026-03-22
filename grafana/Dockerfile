FROM grafana/grafana:latest

# Install ClickHouse datasource plugin
RUN grafana cli plugins install grafana-clickhouse-datasource

# Copy provisioning configs and dashboards
COPY provisioning/ /etc/grafana/provisioning/
