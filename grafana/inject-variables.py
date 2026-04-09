#!/usr/bin/env python3
"""
Parses config.yaml and injects configuration into Grafana dashboard JSON files:

1. An `app_dataset` template variable (dropdown to switch between Firebase apps).
2. Error event list placeholders (__ALL_ERROR_EVENTS__, __AD_ERROR_EVENTS__,
   __IAP_ERROR_EVENTS__) replaced with the actual SQL-ready event lists from config.
"""

import json
import sys
import glob
import os

import yaml


def build_variable(apps):
    """Build a Grafana custom template variable from the apps list."""
    entries = [f"{app['name']} : {app['dataset']}" for app in apps]
    query = ", ".join(entries)

    options = []
    for i, entry in enumerate(entries):
        value = entry.split(" : ", 1)[1]
        options.append({
            "selected": i == 0,
            "text": entry,
            "value": value,
        })

    first = options[0] if options else {}

    return {
        "name": "app_dataset",
        "label": "App / Dataset",
        "type": "custom",
        "query": query,
        "current": {
            "selected": True,
            "text": first.get("text", ""),
            "value": first.get("value", ""),
        },
        "options": options,
        "multi": False,
        "includeAll": False,
    }


def _escape_sql_string(value):
    """Escape a value for use inside a ClickHouse SQL single-quoted string.

    ClickHouse follows the SQL standard: single quotes are escaped by
    doubling them, and backslashes are escaped as well.
    """
    return value.replace("\\", "\\\\").replace("'", "''")


def build_error_event_lists(config):
    """Build SQL-ready event lists from the error_events config section.

    Returns a dict mapping placeholder names to their quoted,
    comma-separated SQL values (e.g. "'event_a', 'event_b'").
    """
    error_events = config.get("error_events", {})
    ads = error_events.get("ads", [])
    iap = error_events.get("iap", [])
    all_events = ads + iap

    def to_sql(events):
        return ", ".join(f"'{_escape_sql_string(e)}'" for e in events)

    return {
        "__ALL_ERROR_EVENTS__": to_sql(all_events),
        "__AD_ERROR_EVENTS__": to_sql(ads),
        "__IAP_ERROR_EVENTS__": to_sql(iap),
    }


def inject_variable(dashboard_path, variable, error_event_lists=None):
    """Inject the app_dataset variable and error event placeholders into a dashboard."""
    with open(dashboard_path, "r") as f:
        dashboard = json.load(f)

    templating = dashboard.setdefault("templating", {})
    var_list = templating.setdefault("list", [])

    # Remove any existing app_dataset variable
    var_list = [v for v in var_list if v.get("name") != "app_dataset"]
    # Place app_dataset first so it appears at the top of the dashboard
    var_list.insert(0, variable)
    templating["list"] = var_list

    with open(dashboard_path, "w") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Replace error event placeholders in the written file
    if error_event_lists:
        _replace_error_event_placeholders(dashboard_path, error_event_lists)

    print(f"[inject-variables] Injected app_dataset into {os.path.basename(dashboard_path)}")


def _replace_error_event_placeholders(dashboard_path, error_event_lists):
    """Replace __*_ERROR_EVENTS__ placeholders with SQL event lists."""
    with open(dashboard_path, "r") as f:
        content = f.read()

    original = content
    for placeholder, sql_list in error_event_lists.items():
        content = content.replace(placeholder, sql_list)

    if content != original:
        with open(dashboard_path, "w") as f:
            f.write(content)
        print(f"[inject-variables] Replaced error event placeholders in {os.path.basename(dashboard_path)}")


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "/build/config.yaml"
    dashboard_dir = sys.argv[2] if len(sys.argv) > 2 else "/build/dashboards"

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    apps = config.get("apps", [])
    if not apps:
        print("[inject-variables] WARNING: No apps found in config — skipping")
        return

    variable = build_variable(apps)
    error_event_lists = build_error_event_lists(config)

    dashboards = glob.glob(os.path.join(dashboard_dir, "*.json"))
    if not dashboards:
        print(f"[inject-variables] WARNING: No dashboards found in {dashboard_dir}")
        return

    for path in sorted(dashboards):
        inject_variable(path, variable, error_event_lists)


if __name__ == "__main__":
    main()
