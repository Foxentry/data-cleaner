#!/bin/bash
# Foxentry Data Cleaner - launcher (Linux)
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    echo "Python 3 not found / Nenašel jsem Python 3 (e.g. sudo apt install python3)."
    exit 1
fi

# The wizard opens in your browser. Set the API key there (gear icon ⚙) and Save.
"$PY" run.py
