#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$SCRIPT_DIR/../backend"

# Check if venv exists, if not, use system python or warn
if [ -x "../.venv/bin/python3" ]; then
    PYTHON_BIN="../.venv/bin/python3"
elif [ -x ".venv/bin/python3" ]; then
    PYTHON_BIN=".venv/bin/python3"
elif [ -x "venv/bin/python3" ]; then
    PYTHON_BIN="venv/bin/python3"
else
    PYTHON_BIN="python3"
fi

if [ -f "../config/.env" ]; then
    export $(grep -v '^#' ../config/.env | grep -v '^$' | xargs)
fi

mkdir -p logs
UVICORN_WORKERS="${UVICORN_WORKERS:-2}"
PORT="${PORT:-8080}"
$PYTHON_BIN -u -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers "$UVICORN_WORKERS" > logs/server.log 2>&1 &
disown
echo "Backend started on port $PORT with $UVICORN_WORKERS uvicorn worker(s). Logs: backend/logs/server.log"
