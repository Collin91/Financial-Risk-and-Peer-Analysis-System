#!/bin/sh
# Starts the program with the environment created by setup.sh. Any options are passed through,
# e.g.  ./run.sh --industry automotive --target Tesla --peers Ford Toyota --years 2021-2025
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "Run ./setup.sh first."
    exit 1
fi
exec .venv/bin/python main.py "$@"
