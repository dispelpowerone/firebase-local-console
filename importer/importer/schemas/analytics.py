"""Firebase Analytics BigQuery schema mapping.

Firebase Analytics exports events to BigQuery using day-sharded tables
(events_YYYYMMDD) with a nested schema. This module defines the flattened
schema used in the local database and provides utilities for transforming
BigQuery rows into flat records suitable for columnar storage.

Reference: https://support.google.com/firebase/answer/7029846
"""

from datetime import datetime, timezone
from typing import Any

# Flattened schema for the local analytics_events table.
# Maps column name -> (ClickHouse SQL type, description)
ANALYTICS_COLUMNS = {
    "event_date": ("Date", "Event date (YYYYMMDD)"),
    "event_timestamp": ("DateTime64(6)", "Event timestamp in UTC"),
    "event_name": ("String", "Event name"),
    "event_bundle_sequence_id": ("Int64", "Bundle sequence ID"),
    # User dimensions
    "user_id": ("Nullable(String)", "User ID set by the app"),
    "user_pseudo_id": ("String", "Pseudonymous user ID (app instance)"),
    "user_first_touch_timestamp": ("Nullable(DateTime64(6))", "First touch time"),
    # Device info
    "device_category": ("Nullable(String)", "Device category (mobile/tablet)"),
    "device_mobile_brand_name": ("Nullable(String)", "Device brand"),
    "device_mobile_model_name": ("Nullable(String)", "Device model"),
    "device_operating_system": ("Nullable(String)", "OS name"),
    "device_operating_system_version": ("Nullable(String)", "OS version"),
    "device_language": ("Nullable(String)", "Device language"),
    # Geo info
    "geo_country": ("Nullable(String)", "Country"),
    "geo_region": ("Nullable(String)", "Region"),
    "geo_city": ("Nullable(String)", "City"),
    # App info
    "app_info_id": ("Nullable(String)", "App package name / bundle ID"),
    "app_info_version": ("Nullable(String)", "App version string"),
    "app_info_install_source": ("Nullable(String)", "Install source"),
    # Platform
    "platform": ("Nullable(String)", "Platform (ANDROID/IOS/WEB)"),
    "stream_id": ("Nullable(String)", "Stream ID"),
    # Flattened event parameters (common ones extracted as dedicated columns)
    "param_page_title": ("Nullable(String)", "page_title param"),
    "param_screen_class": ("Nullable(String)", "screen_class param"),
    "param_engagement_time_msec": ("Nullable(Int64)", "engagement_time_msec param"),
    "param_value": ("Nullable(Float64)", "value param"),
    "param_currency": ("Nullable(String)", "currency param"),
    # JSON blob for all event params (for flexible querying)
    "event_params_json": ("Nullable(String)", "All event params as JSON"),
    # Import metadata
    "import_dataset": ("String", "Source BQ dataset"),
    "imported_at": ("DateTime", "When this row was imported"),
}

# Common event parameter keys to extract as dedicated columns
EXTRACTED_PARAMS = {
    "page_title": ("string_value", "param_page_title"),
    "screen_class": ("string_value", "param_screen_class"),
    "engagement_time_msec": ("int_value", "param_engagement_time_msec"),
    "value": ("double_value", "param_value"),
    "currency": ("string_value", "param_currency"),
}


def _micros_to_datetime(micros: int | None) -> datetime | None:
    """Convert microsecond timestamp to datetime."""
    if micros is None:
        return None
    return datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc)


def _extract_param_value(param: dict[str, Any]) -> Any:
    """Extract the actual value from a Firebase event parameter record."""
    for value_key in ("string_value", "int_value", "float_value", "double_value"):
        val = param.get("value", {}).get(value_key)
        if val is not None:
            return val
    return None


def flatten_event(row: dict[str, Any], dataset: str) -> dict[str, Any]:
    """Flatten a BigQuery analytics event row into a dict matching ANALYTICS_COLUMNS.

    Args:
        row: A single row from the BigQuery events table.
        dataset: The source dataset identifier (e.g., 'analytics_123456789').

    Returns:
        A flat dictionary with keys matching ANALYTICS_COLUMNS.
    """
    import json
    from datetime import date as date_type

    device = row.get("device") or {}
    geo = row.get("geo") or {}
    app_info = row.get("app_info") or {}

    # Build the event params JSON and extract common params
    event_params = row.get("event_params") or []
    params_dict = {}
    extracted = {}

    for param in event_params:
        key = param.get("key", "")
        value = _extract_param_value(param)
        params_dict[key] = value

        if key in EXTRACTED_PARAMS:
            _, col_name = EXTRACTED_PARAMS[key]
            extracted[col_name] = value

    # Convert event_date from BQ format "YYYYMMDD" string to date object
    raw_date = row.get("event_date")
    if isinstance(raw_date, str) and len(raw_date) == 8:
        event_date = date_type(
            int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8])
        )
    else:
        event_date = raw_date

    return {
        "event_date": event_date,
        "event_timestamp": _micros_to_datetime(row.get("event_timestamp")),
        "event_name": row.get("event_name", ""),
        "event_bundle_sequence_id": row.get("event_bundle_sequence_id", 0),
        "user_id": row.get("user_id"),
        "user_pseudo_id": row.get("user_pseudo_id", ""),
        "user_first_touch_timestamp": _micros_to_datetime(
            row.get("user_first_touch_timestamp")
        ),
        "device_category": device.get("category"),
        "device_mobile_brand_name": device.get("mobile_brand_name"),
        "device_mobile_model_name": device.get("mobile_model_name"),
        "device_operating_system": device.get("operating_system"),
        "device_operating_system_version": device.get("operating_system_version"),
        "device_language": device.get("language"),
        "geo_country": geo.get("country"),
        "geo_region": geo.get("region"),
        "geo_city": geo.get("city"),
        "app_info_id": app_info.get("id"),
        "app_info_version": app_info.get("version"),
        "app_info_install_source": app_info.get("install_source"),
        "platform": row.get("platform"),
        "stream_id": row.get("stream_id"),
        "param_page_title": extracted.get("param_page_title"),
        "param_screen_class": extracted.get("param_screen_class"),
        "param_engagement_time_msec": extracted.get("param_engagement_time_msec"),
        "param_value": extracted.get("param_value"),
        "param_currency": extracted.get("param_currency"),
        "event_params_json": json.dumps(params_dict) if params_dict else None,
        "import_dataset": dataset,
        "imported_at": datetime.now(tz=timezone.utc),
    }


def get_bigquery_sql(table_ref: str) -> str:
    """Generate the SELECT query for fetching events from BigQuery.

    Args:
        table_ref: Fully qualified table reference (e.g., 'project.dataset.events_20240101').

    Returns:
        SQL query string.
    """
    return f"""
    SELECT
        event_date,
        event_timestamp,
        event_name,
        event_bundle_sequence_id,
        user_id,
        user_pseudo_id,
        user_first_touch_timestamp,
        device,
        geo,
        app_info,
        platform,
        stream_id,
        event_params
    FROM `{table_ref}`
    """
