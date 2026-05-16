#!/usr/bin/env bash
# Launch the Avinya web interface
cd "$(dirname "$0")/.."
exec ./venv/bin/python -m web.server "$@"
