#!/bin/bash
# Foxentry Data Cleaner - launcher (macOS)
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    echo "Python 3 not found / Nenašel jsem Python 3. https://www.python.org/downloads/"
    read -r -p "Press Enter to close / Stiskněte Enter pro zavření…"
    exit 1
fi

# The wizard opens in your browser. Set the API key there (gear icon) and Save.
"$PY" run.py
