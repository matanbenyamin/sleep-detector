#!/bin/bash
# ==============================================================================
# Sleep Detector — 1-Click Automated Setup for New Devices
# Supports: macOS & Linux (Ubuntu, Debian, Fedora, Arch)
# ==============================================================================

set -e

# Color helpers
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo -e "${CYAN}${BOLD}"
echo "=========================================================="
echo "      Sleep Detector — Automated Setup & Installer        "
echo "=========================================================="
echo -e "${NC}"

# 1. Check for Python 3
echo -e "${CYAN}[1/5] Checking Python 3 installation...${NC}"
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1)
    echo -e "${GREEN}✓ Found: $PY_VER${NC}"
else
    echo -e "${RED}✗ Error: Python 3 is not installed.${NC}"
    echo "Please install Python 3 (https://www.python.org/downloads/) and re-run this script."
    exit 1
fi

# 2. Create Virtual Environment
echo -e "\n${CYAN}[2/5] Setting up isolated Python virtual environment (.venv)...${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}✓ Created new virtual environment in .venv${NC}"
else
    echo -e "${GREEN}✓ Virtual environment already exists (.venv)${NC}"
fi

# 3. Upgrade pip and install dependencies
echo -e "\n${CYAN}[3/5] Installing dependencies from requirements.txt...${NC}"
source .venv/bin/activate
pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r requirements.txt
echo -e "${GREEN}✓ All dependencies installed successfully (bleak, matplotlib, google-api, etc.)${NC}"

# 4. Check for Google Cloud OAuth Client Secret (Optional for Cloud Mode)
echo -e "\n${CYAN}[4/5] Checking for Google OAuth credentials (for Cloud Fit mode)...${NC}"
SECRET_FOUND=false
if ls client_secret*.json 1>/dev/null 2>&1; then
    SECRET_FILE=$(ls client_secret*.json | head -n 1)
    echo -e "${GREEN}✓ Found credentials in project: $SECRET_FILE${NC}"
    SECRET_FOUND=true
elif [ -d "$HOME/Downloads" ] && ls "$HOME/Downloads"/client_secret*.json 1>/dev/null 2>&1; then
    SECRET_FILE=$(ls "$HOME/Downloads"/client_secret*.json | head -n 1)
    cp "$SECRET_FILE" "$PROJECT_DIR/"
    echo -e "${GREEN}✓ Found and copied credentials from Downloads: $(basename "$SECRET_FILE")${NC}"
    SECRET_FOUND=true
else
    echo -e "${YELLOW}ℹ Note: No client_secret*.json found. Bluetooth mode (--ble) will work without it!${NC}"
fi

# 5. Make launchers executable
echo -e "\n${CYAN}[5/5] Creating 1-Click Launchers...${NC}"
chmod +x "$PROJECT_DIR/heart_rate_live.py"
chmod +x "$PROJECT_DIR/run.sh" 2>/dev/null || true
chmod +x "$PROJECT_DIR/Start Sleep Detector.command" 2>/dev/null || true
echo -e "${GREEN}✓ Configured double-clickable launchers.${NC}"

# Summary and instructions
echo -e "\n${GREEN}${BOLD}=========================================================="
echo "          Setup Completed Successfully! 🎉               "
echo "==========================================================${NC}"

echo -e "\n${BOLD}How to Run:${NC}"
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo -e "  🖱️  ${CYAN}Double-click:${NC} 'Start Sleep Detector.command' in Finder"
fi
echo -e "  💻  ${CYAN}Terminal:${NC}     ./run.sh --ble"
echo -e "  🧪  ${CYAN}Test UI:${NC}      ./run.sh --mock"

echo -e "\n${YELLOW}${BOLD}⚠️  Required One-Time Manual Steps (if not done yet):${NC}"
echo -e "  1. ${BOLD}Fitbit Air Setting:${NC} On your phone, open Google Health / Fitbit app"
echo -e "     → Tap Fitbit Air → 'Share heart rate' → Toggle ON '${BOLD}Always visible${NC}'."
echo -e "  2. ${BOLD}Put on the Band:${NC} Wear the Fitbit Air snugly on your wrist so the optical sensor reads your pulse."
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo -e "  3. ${BOLD}Mac Bluetooth Permission:${NC} When prompted by macOS on first launch, click 'Allow' for Bluetooth access."
fi
echo ""
