#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then echo "Copy .env.example to .env and set SECRET_KEY first" >&2; exit 1; fi
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
source .venv/bin/activate
pip install -r requirements.txt
flask --app wsgi.py db upgrade
printf '\nRun: flask --app wsgi.py create-admin (once)\n'
flask --app wsgi.py run --host 127.0.0.1 --port 5000
