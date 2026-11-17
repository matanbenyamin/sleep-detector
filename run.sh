#!/bin/bash
# Portable CLI runner for Sleep Detector
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
    echo "Virtual environment not detected. Running automated install first..."
    ./install.sh
fi

source .venv/bin/activate
export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"
python3 heart_rate_live.py "$@"
