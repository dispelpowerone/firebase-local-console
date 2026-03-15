-- DuckDB schema initialization
-- This file is executed on first startup to create the required tables.

CREATE TABLE IF NOT EXISTS analytics_events (
    event_date DATE,
    event_timestamp TIMESTAMP,
    event_name VARCHAR,
    event_bundle_sequence_id BIGINT,
    user_id VARCHAR,
    user_pseudo_id VARCHAR,
    user_first_touch_timestamp TIMESTAMP,
    device_category VARCHAR,
    device_mobile_brand_name VARCHAR,
    device_mobile_model_name VARCHAR,
    device_operating_system VARCHAR,
    device_operating_system_version VARCHAR,
    device_language VARCHAR,
    geo_country VARCHAR,
    geo_region VARCHAR,
    geo_city VARCHAR,
    app_info_id VARCHAR,
    app_info_version VARCHAR,
    app_info_install_source VARCHAR,
    platform VARCHAR,
    stream_id VARCHAR,
    param_page_title VARCHAR,
    param_screen_class VARCHAR,
    param_engagement_time_msec BIGINT,
    param_value DOUBLE,
    param_currency VARCHAR,
    event_params_json TEXT,
    import_dataset VARCHAR,
    imported_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_watermarks (
    dataset VARCHAR PRIMARY KEY,
    last_date DATE NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
