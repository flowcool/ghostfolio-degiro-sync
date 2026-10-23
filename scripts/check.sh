#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
check_python=${PYTHON:-.venv/bin/python}
"$check_python" -m ruff check ghostfolio_degiro_sync
"$check_python" -m mypy
"$check_python" -m pytest -q tests/test_python_conventions.py
