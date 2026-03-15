# DuckDB is embedded — no server container needed.
# This Dockerfile provides a lightweight utility container for DuckDB CLI access,
# schema initialization, and data inspection.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN uv pip install --system duckdb>=1.5.0

COPY config/init.sql /app/init.sql

WORKDIR /data

# Initialize the database on first run, then keep alive for debugging
CMD ["sh", "-c", "python3 -c \"import duckdb; conn = duckdb.connect('/data/firebase.duckdb'); conn.execute(open('/app/init.sql').read()); conn.close(); print('DuckDB initialized')\" && tail -f /dev/null"]
