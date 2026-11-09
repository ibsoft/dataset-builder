#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m compileall -q datasetbuilder migrations wsgi.py
node --check datasetbuilder/static/js/app.js
node --check datasetbuilder/static/js/editor.js
printf 'Python and JavaScript syntax valid.\n'
