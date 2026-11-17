#!/bin/bash
# Double-clickable macOS launcher for Sleep Detector
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================================="
echo "          Starting Sleep Detector (Bluetooth Live)        "
echo "=========================================================="

if [ ! -d ".venv" ]; then
    echo "First time running? Running automated setup..."
    ./install.sh
fi

source .venv/bin/activate
python3 heart_rate_live.py --ble "$@"
