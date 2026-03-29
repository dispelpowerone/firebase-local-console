#!/usr/bin/env python3
"""
Parses config.yaml and injects an `app_dataset` template variable
into every Grafana dashboard JSON file.

The variable is a Grafana "custom" dropdown whose values map
"App Name : dataset_id" so users can switch between Firebase apps.
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


def inject_variable(dashboard_path, variable):
    """Inject the variable into a single dashboard JSON file."""
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

    print(f"[inject-variables] Injected app_dataset into {os.path.basename(dashboard_path)}")


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

    dashboards = glob.glob(os.path.join(dashboard_dir, "*.json"))
    if not dashboards:
        print(f"[inject-variables] WARNING: No dashboards found in {dashboard_dir}")
        return

    for path in sorted(dashboards):
        inject_variable(path, variable)


if __name__ == "__main__":
    main()
