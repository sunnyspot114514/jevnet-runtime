#!/usr/bin/env bash
set -euo pipefail
python -m pip install -e .
if [[ "${1:-}" != "--core-only" ]]; then
  python -m pip install -e ".[research]"
fi
python -m pytest -q
python -m py_compile sar_runtime/*.py
