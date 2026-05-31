#!/usr/bin/env bash
# Lint the whole repo with ruff (config in pyproject.toml).
# Usage: scripts/lint.sh [--fix]
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v ruff >/dev/null 2>&1; then
  echo "ruff not found. Install with: pip install ruff" >&2
  exit 127
fi

if [[ "${1:-}" == "--fix" ]]; then
  echo "==> ruff check --fix ."
  ruff check --fix .
else
  echo "==> ruff check ."
  ruff check .
fi
echo "lint: OK"
