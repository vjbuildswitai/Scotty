#!/usr/bin/env bash
# Proves Scotty works: translations complete, every core and Windows-app test (each failure either
# new, which fails this, or listed by name in .sdlc/known-failures.txt), and a real 1 GB transfer
# through the encrypted file channel. On Windows run it in Git Bash:
#   "C:/Program Files/Git/bin/bash.exe" -c "bash scripts/verify.sh"
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"
elif [ -x win_app/.venv/Scripts/python.exe ]; then PY=win_app/.venv/Scripts/python.exe
elif [ -x win_app/.venv/bin/python ]; then PY=win_app/.venv/bin/python
else PY=python; fi
echo "python: $("$PY" --version 2>&1)"

echo "== translations"
"$PY" tools/i18n_extract.py --check

echo "== core tests"
"$PY" tools/run_suite.py core

echo "== Windows app tests"
"$PY" tools/run_suite.py win_app

echo "== 1 GB through the file channel"
"$PY" tools/scotty_gb_check.py

echo "VERIFY PASSED"
