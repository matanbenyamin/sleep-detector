# Sleep Detector — Quick Setup & Installation Guide

This guide explains how to install and run the **Sleep Detector** on any new computer (macOS, Windows, or Linux).

---

## ⚡ 1-Click Automated Setup

### On macOS / Linux
Open your terminal, navigate to the folder, and run:
```bash
./install.sh
```

**What `install.sh` does automatically:**
1. Checks for Python 3.
2. Automatically creates an isolated virtual environment (`.venv`).
3. Installs all required packages (`bleak`, `matplotlib`, `google-api-python-client`, `google-auth-oauthlib`, etc.).
4. Auto-detects and copies `client_secret*.json` from your Downloads folder if present.
5. Configures 1-click launchers (`Start Sleep Detector.command`).

### On Windows
Double-click `install.bat`. It will create `.venv` and install all dependencies automatically.

---

## 🖱️ How to Run

### Option 1: macOS Finder (1-Click)
- In macOS Finder, simply **double-click** `Start Sleep Detector.command`.
- It will automatically open Terminal, activate the environment, and start live Bluetooth streaming.

### Option 2: Command Line
```bash
# Direct 1-second pulse live streaming over Bluetooth (Recommended)
./run.sh --ble

# Google Fitness API cloud mode
./run.sh

# Simulated test preview (no device needed)
./run.sh --mock
```

---

## 📋 What Cannot Be Done Automatically (Manual Steps)

Because these settings involve physical devices, operating system security, and your smartphone, they must be set once manually:

### 1. Fitbit Air: Enable "Always Visible" (Required for Bluetooth)
On your Android or iPhone:
1. Open the **Google Health** or **Fitbit** app.
2. Tap the device icon in the top corner → select your **Fitbit Air**.
3. Tap **Share heart rate**.
4. Toggle ON **"Always visible"**.
   > *Once turned on, the band stays in broadcast mode indefinitely. You do not need to re-enable it every night.*

### 2. Wear the Band Snugly on Wrist
The optical photoplethysmography (PPG) green sensor on the Fitbit Air automatically powers down if it does not detect skin contact to save battery. Wear it snugly on your wrist.

### 3. Mac Bluetooth Permission (First Run Only)
The first time the script runs on a new Mac, macOS will display a pop-up:
`"Terminal" (or "Python") would like to use Bluetooth.`
Click **Allow** (or enable it in **System Settings → Privacy & Security → Bluetooth**).

### 4. Google OAuth Consent (Only If using Google Fit Cloud Mode)
If you run without `--ble` (using Google Fit Cloud mode instead of Bluetooth):
1. Ensure your `client_secret_....json` file is in this folder or in `~/Downloads`.
2. Add your Google email as a **Test User** in your [Google Cloud Console OAuth Consent Screen](https://console.cloud.google.com/apis/credentials/consent).
