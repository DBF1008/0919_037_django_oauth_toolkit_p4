#!/usr/bin/env bash
#
# Test script for the cleartokens / clear_expired rework.
#
# Unit tests:
#   1. clear_expired model-level behavior (batching, dry-run, FK ordering)
#   2. Prometheus metrics exposed by clear_expired
#   3. cleartokens management command (flags, progress, dry-run output)
#   4. Pre-existing token/command regression tests
#   5. Full test suite
# Lint:
#   6. Ruff lint + format checks
#
# Usage:
#   ./test.sh                 # run everything
#   ./test.sh unit            # run only the unit tests (1-4)
#   ./test.sh metrics         # run only the metrics tests
#   ./test.sh command         # run only the management command tests
#   ./test.sh regression      # run only the pre-existing token/command tests
#   ./test.sh full            # run the complete test suite
#   ./test.sh lint            # run ruff checks
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ -x ".venvtest/bin/python" ]; then
    PYTHON_BIN=".venvtest/bin/python"
elif [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
fi
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-tests.settings}"
PYTEST="$PYTHON_BIN -m pytest"

UNIT_TARGETS=(tests/test_clear_expired.py)
REGRESSION_TARGETS=(tests/test_models.py tests/test_commands.py)

banner() {
    echo ""
    echo "=============================================="
    echo " $1"
    echo "=============================================="
}

run_unit() {
    banner "[1-3] clear_expired unit tests (batching, FK order, command)"
    $PYTEST "${UNIT_TARGETS[@]}" -v "$@"
}

run_metrics() {
    banner "[2] Prometheus metrics tests"
    $PYTEST "${UNIT_TARGETS[@]}" -v -k "metric" "$@"
}

run_command() {
    banner "[3] cleartokens management command tests"
    $PYTEST "${UNIT_TARGETS[@]}" -v -k "Command" "$@"
}

run_regression() {
    banner "[4] Regression tests (models + commands)"
    $PYTEST "${REGRESSION_TARGETS[@]}" -v "$@"
}

run_full() {
    banner "[5] Full test suite"
    $PYTEST tests/ "$@"
}

run_lint() {
    banner "[6] Ruff lint + format"
    ruff check oauth2_provider tests
    ruff format --check oauth2_provider tests
}

case "${1:-all}" in
    unit)
        run_unit
        ;;
    metrics)
        run_metrics
        ;;
    command)
        run_command
        ;;
    regression)
        run_regression
        ;;
    full)
        run_full
        ;;
    lint)
        run_lint
        ;;
    all)
        run_unit
        run_regression
        run_lint
        echo ""
        echo "All checks passed."
        ;;
    *)
        echo "Usage: $0 {unit|metrics|command|regression|full|lint|all}"
        exit 1
        ;;
esac
