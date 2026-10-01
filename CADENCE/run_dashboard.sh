#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
    printf '%s\n' "Missing CADENCE/.venv. Follow the installation steps in CADENCE/README.md." >&2
    exit 1
fi

printf '%s\n' "CADENCE dashboard: http://localhost:8520/" \
    "If port 8520 is occupied, reuse the running dashboard or stop it with Ctrl+C before restarting."
exec .venv/bin/python -m streamlit run src/cadence/ui/app.py \
    --server.address 127.0.0.1 --server.port 8520 --server.headless true