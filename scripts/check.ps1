param([switch]$CoreOnly)
$ErrorActionPreference = "Stop"
python -m pip install -e .
if (-not $CoreOnly) { python -m pip install -e ".[research]" }
python -m pytest -q
python -m py_compile sar_runtime/*.py
