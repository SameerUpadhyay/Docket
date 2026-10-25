#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt -r backend/tests/requirements.txt
npm ci --prefix frontend
if [[ "$(uname -s)" == "Darwin" ]] && command -v swiftc >/dev/null 2>&1; then
  mkdir -p backend/bin
  swiftc -module-cache-path "${TMPDIR:-/tmp}/docket-swift-cache" scripts/vision_ocr.swift -o backend/bin/vision-ocr
fi
