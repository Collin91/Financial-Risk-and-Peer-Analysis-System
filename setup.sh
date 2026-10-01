#!/bin/sh
# One-time setup on macOS / Linux: finds Python 3.9 or newer, creates a private environment in .venv
# and installs the required packages there. Afterwards start the program with ./run.sh
set -e
cd "$(dirname "$0")"

PY=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Python 3.9 or newer was not found. Install it from https://www.python.org/downloads/ and run ./setup.sh again."
    exit 1
fi

echo "Using: $("$PY" --version)"
echo "Creating the environment in .venv ..."
"$PY" -m venv .venv
echo "Installing packages (this can take a few minutes) ..."
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt

echo
echo "Setup complete. Start the program with:  ./run.sh"
