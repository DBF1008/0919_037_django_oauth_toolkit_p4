#!/usr/bin/env bash
#
# Manual test script for the cleartokens batch-cleanup feature.
#
# Usage:
#   ./test.sh           run all unit tests for the feature
#   ./test.sh --full    also run the complete test_models.py and test_commands.py files
#
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python"
fi

export DJANGO_SETTINGS_MODULE=tests.settings
export PYTHONPATH=.

echo "==> cleartokens management command tests"
"$PYTHON" -m pytest tests/test_commands.py -q -k "ClearTokens"

echo "==> clear_expired() model tests"
"$PYTHON" -m pytest tests/test_models.py -q -k "ClearExpired or clear_expired"

if [ "${1:-}" = "--full" ]; then
    echo "==> full test_commands.py and test_models.py"
    "$PYTHON" -m pytest tests/test_commands.py tests/test_models.py -q
fi

echo "==> ruff lint"
if [ -x ".venv/bin/ruff" ]; then
    .venv/bin/ruff check oauth2_provider/models.py oauth2_provider/management/commands/cleartokens.py tests/
    .venv/bin/ruff format --check oauth2_provider/models.py oauth2_provider/management/commands/cleartokens.py
else
    echo "    (ruff not installed, skipping)"
fi

echo "All checks passed."
