#!/usr/bin/env python3
"""
Parses config.yaml and injects configuration into Grafana dashboard JSON files:

1. An `app_dataset` template variable (dropdown to switch between Firebase apps).
2. Event macros (e.g. __ADS_INTERSTITIAL_DISPLAYED__, __ERRORS_ADS__,
   __ALL_ERROR_EVENTS__) replaced with SQL-ready event lists from config.
"""

import json
import sys
import glob
import os

import yaml


def build_variable(apps, name="app_dataset", label="App / Dataset"):
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
        "name": name,
        "label": label,
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


def _to_sql(events):
    """Convert a list of event names to a SQL-ready quoted, comma-separated string."""
    return ", ".join(f"'{_escape_sql_string(e)}'" for e in events)


def build_event_macros(node, prefix=""):
    """Recursively walk an events config tree and build macro → SQL mappings.

    Each leaf value (a string or list of strings) produces a macro named
    ``__<PATH>__`` where PATH is the uppercased, underscore-joined key path.
    The value is a SQL-ready quoted, comma-separated list.

    Example config path ``events.ads.interstitial.displayed`` with value
    ``custom_ads_event_displayed`` produces the macro
    ``__ADS_INTERSTITIAL_DISPLAYED__`` → ``'custom_ads_event_displayed'``.
    """
    macros = {}
    if not isinstance(node, dict):
        return macros
    for key, value in node.items():
        path = f"{prefix}_{key}" if prefix else key
        if isinstance(value, str):
            macros[f"__{path.upper()}__"] = _to_sql([value])
        elif isinstance(value, list) and value:
            macros[f"__{path.upper()}__"] = _to_sql(value)
        elif isinstance(value, dict):
            macros.update(build_event_macros(value, path))
    return macros


def _collect_leaf_events(node):
    """Collect all leaf event strings from a nested config node."""
    events = []
    if isinstance(node, str):
        events.append(node)
    elif isinstance(node, list):
        events.extend(node)
    elif isinstance(node, dict):
        for value in node.values():
            events.extend(_collect_leaf_events(value))
    return events


def build_all_macros(config):
    """Build the complete macro dict from the events config section.

    Generates path-based macros via build_event_macros plus the aggregate
    __ALL_ERROR_EVENTS__ convenience macro.
    """
    events = config.get("events", {})
    macros = build_event_macros(events)

    # Aggregate convenience macro: all error events combined
    errors = events.get("errors", {})
    all_errors = _collect_leaf_events(errors)
    if all_errors:
        macros["__ALL_ERROR_EVENTS__"] = _to_sql(all_errors)

    return macros


def _has_ab_variables(dashboard):
    """Check if a dashboard uses app_dataset_a / app_dataset_b variables."""
    var_list = dashboard.get("templating", {}).get("list", [])
    names = {v.get("name") for v in var_list}
    return "app_dataset_a" in names or "app_dataset_b" in names


def inject_variable(dashboard_path, variable, macros=None, ab_variables=None):
    """Inject app dataset variable(s) and event macros into a dashboard.

    Dashboards that define ``app_dataset_a`` / ``app_dataset_b`` template
    variables get those replaced with *ab_variables*; all other dashboards
    receive the single *variable* (``app_dataset``).
    """
    with open(dashboard_path, "r") as f:
        dashboard = json.load(f)

    templating = dashboard.setdefault("templating", {})
    var_list = templating.setdefault("list", [])

    if _has_ab_variables(dashboard) and ab_variables:
        var_a, var_b = ab_variables
        var_list = [v for v in var_list
                    if v.get("name") not in ("app_dataset_a", "app_dataset_b")]
        var_list.insert(0, var_b)
        var_list.insert(0, var_a)
        injected = "app_dataset_a, app_dataset_b"
    else:
        var_list = [v for v in var_list if v.get("name") != "app_dataset"]
        var_list.insert(0, variable)
        injected = "app_dataset"
    templating["list"] = var_list

    with open(dashboard_path, "w") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
        f.write("\n")

    if macros:
        _replace_macros(dashboard_path, macros)

    print(f"[inject-variables] Injected {injected} into {os.path.basename(dashboard_path)}")


def _replace_macros(dashboard_path, macros):
    """Replace __MACRO__ placeholders with their SQL event lists."""
    with open(dashboard_path, "r") as f:
        content = f.read()

    original = content
    for placeholder, sql_list in macros.items():
        content = content.replace(placeholder, sql_list)

    if content != original:
        with open(dashboard_path, "w") as f:
            f.write(content)
        print(f"[inject-variables] Replaced event macros in {os.path.basename(dashboard_path)}")


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
    ab_variables = (
        build_variable(apps, name="app_dataset_a", label="App A"),
        build_variable(apps, name="app_dataset_b", label="App B"),
    )
    macros = build_all_macros(config)

    dashboards = glob.glob(os.path.join(dashboard_dir, "*.json"))
    if not dashboards:
        print(f"[inject-variables] WARNING: No dashboards found in {dashboard_dir}")
        return

    for path in sorted(dashboards):
        inject_variable(path, variable, macros, ab_variables)


if __name__ == "__main__":
    main()
