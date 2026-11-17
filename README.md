# Sleep Detector — Live Heart Rate & Smart TV Sleep Automator

Real-time dynamic heart rate tracking and sleep detection for your **Google Fitbit Air**, with automated **Smart TV (LG webOS / Xiaomi TV Box) shutoff over LAN Wi-Fi** when sleep is detected.

---

## 📺 Smart TV Auto-Shutoff over Wi-Fi

When you fall asleep (the adaptive detector confirms sleep (see below) for a sustained duration, default: 3 minutes), the system automatically transmits a **Power Off command over your home Wi-Fi** to shut down your TV!

### 1. LG Smart TV (webOS)
- We detected your TV on your network: **`[LG] webOS TV UA73006LA`** at `192.168.1.215`.
- **First-Time Pairing**:
  With your TV powered ON, run the one-time pairing command:
  ```bash
  python tv_controller.py --pair-lg
  ```
  Look at your TV screen and click **"Accept" / "Allow"** with your LG Magic Remote. The key is saved in `lgtv_key.json` and future power-offs happen silently over Wi-Fi.

- **HDMI-CEC / SIMPLINK**: If your Xiaomi TV Box is connected to your LG TV via HDMI, powering off the LG TV will also automatically power down the Xiaomi Box!

### 2. Xiaomi TV Box (Android TV)
- Connects over LAN Wi-Fi using Android's remote ADB protocol.
- Make sure "Network Debugging" is enabled on your Xiaomi Box.

---

## 🚀 Running the System

Activate environment:
```bash
cd /Users/matanbenyamin/picobebe/sleep-detector
source .venv/bin/activate
```

### Recommended Run (Bluetooth Live 1-sec Pulse + Auto TV Shutdown):
```bash
./run.sh --ble
```
*(Or double-click `Start Sleep Detector.command` in Finder!)*

### Test Simulated Sleep + TV Shutdown Preview:
```bash
# Sets a 15-second sleep timer to preview the TV shutdown countdown:
./run.sh --mock --threshold 80 --tv-delay 15
```

---

## ⚙️ Key CLI Options

| Argument | Default | Description |
|---|---|---|
| `--ble` | `False` | Direct Bluetooth LE 1-second live stream from Fitbit Air |
| `--tv` | `auto` | Target TV to shut off: `auto`, `lg`, `xiaomi`, `both`, or `none` |
| `--tv-delay` | `180` | Continuous seconds of sleep required before powering off TV (default 3m) |
| `--lg-ip` | `192.168.1.215`| IP address of your LG webOS Smart TV |
| `--view` | `30` | Minutes of history shown in the graph |
| `--no-log` | `False` | Don't save samples to `hr_logs/*.csv` |
| `--mock` | `False` | Run with simulated data to test UI & TV shutdown |

---

## 🧠 How sleep is detected (no fixed BPM threshold)

`sleep_algo.py` compares the last minutes of HR against a **lagged, adaptive awake baseline** learned
from your current session, and scores four signals: drop vs. baseline, plateau stability, low jitter and a
falling trend. Spikes (movement) and steps subtract from the score. A hysteresis state machine
(AWAKE → DROWSY → ASLEEP) with minimum dwell times makes the call. Your typical sleep drop is learned over
time in `sleep_profile.json`. Every HR sample is logged to `hr_logs/hr_YYYY-MM-DD.csv` for tuning.
# sleep-detector
