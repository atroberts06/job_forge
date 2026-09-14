#!/bin/sh
# Serve the local job-search dashboard on http://127.0.0.1:8765
set -e

PORT=8765
PYTHON="${PYTHON:-python}"

while [ $# -gt 0 ]; do
    case "$1" in
        --port)
            PORT=$2
            shift 2
            ;;
        --python)
            PYTHON=$2
            shift 2
            ;;
        *)
            PORT=$1
            shift
            ;;
    esac
done

DASHBOARD_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SERVE_PY="$DASHBOARD_DIR/serve.py"

echo "Serving job-search dashboard from: $(dirname "$DASHBOARD_DIR")"
echo "Open http://127.0.0.1:${PORT}/dashboard/"
exec "$PYTHON" "$SERVE_PY" --port "$PORT"
