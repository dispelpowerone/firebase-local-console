#!/bin/env bash

set -eo pipefail

flock -n /tmp/importer.lock uv run --no-dev python -m importer.main || echo "Another instance of the importer is already running. Exiting."
