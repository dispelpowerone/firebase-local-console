#!/bin/env bash

set -eo pipefail

echo "Running initial import..."
./import_once.sh

echo "Starting scheduler..."
exec supercronic crontab
