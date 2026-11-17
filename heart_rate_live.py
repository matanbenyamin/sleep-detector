#!/usr/bin/env python3
"""
Live Heart Rate Monitor & Sleep Detector for Google Fitbit Air.
Supports:
  1. Direct Bluetooth Low Energy (BLE) live 1-second pulse streaming (--ble).
  2. Local LAN Wi-Fi receiver on port 8080 (--wifi).
  3. Google Fitness REST API cloud sync over Wi-Fi (default).
  4. Adaptive sleep detection (sleep_algo.py): personal baseline, drop, stability, trend.
  5. Automated Smart TV (LG webOS / Xiaomi TV Box) power-off over LAN Wi-Fi.
  6. Offline simulated preview (--mock).
"""

import os
import sys
import time
import json
import argparse
import datetime
import threading
import warnings
import asyncio
import http.server
import urllib.parse
import ssl
from collections import deque
from bridge_html import BRIDGE_HTML
import numpy as np
from sleep_algo import SleepDetector, HRLogger, synthetic_night, AWAKE, DROWSY, ASLEEP
from typing import List, Tuple, Optional

# Suppress python version/SSL deprecation warnings for cleaner console output
warnings.filterwarnings("ignore")

# Setup matplotlib
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.animation import FuncAnimation

# Bluetooth LE support
try:
    from bleak import BleakScanner, BleakClient
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False

# Smart TV LAN control support
try:
    from tv_controller import SmartTVManager
    TV_CONTROL_AVAILABLE = True
except ImportError:
    TV_CONTROL_AVAILABLE = False

# Google API client imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_FIT_AVAILABLE = True
except ImportError:
    GOOGLE_FIT_AVAILABLE = False

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(PROJECT_DIR, "token.json")
BLE_HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
BLE_HR_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

SCOPES = [
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read",
]


def find_credentials_file() -> str:
    """Auto-discovers Google OAuth client_secret JSON in project dir or ~/Downloads."""
    for fname in os.listdir(PROJECT_DIR):
        if fname.startswith("client_secret") and fname.endswith(".json"):
            return os.path.join(PROJECT_DIR, fname)

    downloads_dir = os.path.expanduser("~/Downloads")
    if os.path.exists(downloads_dir):
        for fname in os.listdir(downloads_dir):
            if fname.startswith("client_secret") and fname.endswith(".json"):
                return os.path.join(downloads_dir, fname)

    return "/Users/matanbenyamin/Downloads/client_secret_333742183709-nporgqjluaop44kp7c8nck7k6tsi05hn.apps.googleusercontent.com.json"


class WiFiLANReceiver:
    """Listens on local LAN Wi-Fi for real-time heart rate packets from phone/apps."""

    def __init__(self, data_callback, port: int = 8443):
        self.data_callback = data_callback
        self.port = port
        self.server = None

    def start(self):
        callback = self.data_callback

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress HTTP log spam

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(BRIDGE_HTML.encode("utf-8"))
                    return

                # Accepts GET /hr?bpm=68
                if parsed.path == "/hr":
                    params = urllib.parse.parse_qs(parsed.query)
                    if "bpm" in params:
                        try:
                            val = float(params["bpm"][0])
                            callback(datetime.datetime.now(), val)
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(b'{"status":"ok"}')
                            return
                        except Exception:
                            pass
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Sleep Detector LAN Wi-Fi Endpoint Active.")

            def do_POST(self):
                # Accepts POST /hr with JSON {"bpm": 68}
                length = int(self.headers.get("content-length", 0))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body)
                    val = float(payload.get("bpm", 0))
                    if val > 0:
                        callback(datetime.datetime.now(), val)
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status":"ok"}')
                        return
                except Exception:
                    pass
                self.send_response(400)
                self.end_headers()

        self.server = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), Handler)

        cert_file = os.path.join(PROJECT_DIR, "cert.pem")
        key_file = os.path.join(PROJECT_DIR, "key.pem")
        if os.path.exists(cert_file) and os.path.exists(key_file):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
            proto = "https"
        else:
            proto = "http"

        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        print(f"[INFO] LAN Wi-Fi receiver running: {proto}://192.168.1.197:{self.port}/")


class BLEHeartRateClient:
    """Connects directly to Google Fitbit Air via Bluetooth Low Energy (BLE)."""

    def __init__(self, data_callback, target_name="Google Fitbit Air"):
        self.data_callback = data_callback
        self.target_name = target_name
        self.is_running = True
        self.connected_device_name = None
        self.status_message = "Scanning for Fitbit Air over Bluetooth..."

    def start(self):
        thread = threading.Thread(target=self._run_event_loop, daemon=True)
        thread.start()

    def _run_event_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._ble_worker())

    async def _ble_worker(self):
        while self.is_running:
            try:
                self.status_message = "Scanning for Fitbit Air..."
                target_address = None

                async with BleakScanner() as scanner:
                    await asyncio.sleep(4.0)
                    for d, adv in scanner.discovered_devices_and_advertisement_data.values():
                        name = d.name or adv.local_name or ""
                        if self.target_name.lower() in name.lower() or BLE_HR_SERVICE_UUID in adv.service_uuids:
                            target_address = d.address
                            self.connected_device_name = name or "Fitbit Air"
                            break

                if not target_address:
                    self.status_message = "Fitbit Air not found. Ensure 'Share heart rate' -> 'Always visible' is ON."
                    await asyncio.sleep(4.0)
                    continue

                self.status_message = f"Connecting to {self.connected_device_name}..."
                async with BleakClient(target_address, timeout=12.0) as client:
                    self.status_message = f"Connected to {self.connected_device_name}. Subscribing to pulse..."

                    def _on_hr_packet(sender, data):
                        flags = data[0]
                        if flags & 0x01:
                            bpm = int.from_bytes(data[1:3], byteorder='little')
                        else:
                            bpm = data[1]
                        self.status_message = f"Live BLE Stream: {bpm} BPM"
                        self.data_callback(datetime.datetime.now(), float(bpm))

                    await client.start_notify(BLE_HR_CHAR_UUID, _on_hr_packet)
                    self.status_message = f"Streaming live 1-sec pulse from {self.connected_device_name}."

                    while self.is_running and client.is_connected:
                        await asyncio.sleep(1.0)

                    await client.stop_notify(BLE_HR_CHAR_UUID)

            except Exception as e:
                self.status_message = f"BLE Disconnected: {e}. Reconnecting..."
                await asyncio.sleep(3.0)


class GoogleFitClient:
    """Handles OAuth 2.0 and fetching multi-metric health data from Google Fitness API."""

    def __init__(self, credentials_path: str = None, token_path: str = TOKEN_PATH):
        self.credentials_path = credentials_path or find_credentials_file()
        self.token_path = token_path
        self.service = None
        self.data_source_id = None

    def authenticate(self):
        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception as e:
                print(f"[WARN] Failed to load cached token: {e}. Re-authenticating...")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("[INFO] Refreshing expired OAuth credentials...")
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(f"OAuth credentials not found at: {self.credentials_path}")
                print(f"[INFO] Initiating OAuth flow using: {self.credentials_path}")
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())
            print(f"[INFO] Token saved to: {self.token_path}")

        self.service = build("fitness", "v1", credentials=creds)
        print("[INFO] Successfully connected to Google Fitness API.")
        self._find_heart_rate_datasource()

    def _find_heart_rate_datasource(self):
        try:
            sources = self.service.users().dataSources().list(userId="me").execute()
            data_sources = sources.get("dataSource", [])
            hr_sources = [
                ds for ds in data_sources
                if ds.get("dataType", {}).get("name") == "com.google.heart_rate.bpm"
            ]

            # Prioritize Fitbit stream, then standard merged stream
            for ds in hr_sources:
                stream_id = ds.get("dataStreamId", "")
                if "fitbit" in stream_id.lower():
                    self.data_source_id = stream_id
                    break

            if not self.data_source_id:
                for ds in hr_sources:
                    stream_id = ds.get("dataStreamId", "")
                    if "merge_heart_rate_bpm" in stream_id:
                        self.data_source_id = stream_id
                        break

            if not self.data_source_id:
                self.data_source_id = "raw:com.google.heart_rate.bpm:com.fitbit.FitbitMobile:health_platform"

            print(f"[INFO] Active Heart Rate Stream: {self.data_source_id}")
        except Exception:
            self.data_source_id = "raw:com.google.heart_rate.bpm:com.fitbit.FitbitMobile:health_platform"

    def fetch_heart_rate_range(self, start_dt: datetime.datetime, end_dt: datetime.datetime) -> List[Tuple[datetime.datetime, float]]:
        if not self.service:
            raise RuntimeError("Google Fit client not authenticated.")

        start_nanos = int(start_dt.timestamp() * 1e9)
        end_nanos = int(end_dt.timestamp() * 1e9)
        dataset_id = f"{start_nanos}-{end_nanos}"
        results = []

        streams_to_check = [self.data_source_id]
        for s in ("raw:com.google.heart_rate.bpm:com.fitbit.FitbitMobile:health_platform",
                  "derived:com.google.heart_rate.bpm:com.google.android.gms:merge_heart_rate_bpm"):
            if s not in streams_to_check:
                streams_to_check.append(s)

        for s_id in streams_to_check:
            try:
                dataset = self.service.users().dataSources().datasets().get(
                    userId="me",
                    dataSourceId=s_id,
                    datasetId=dataset_id
                ).execute()
                for pt in dataset.get("point", []):
                    pt_time_ns = int(pt.get("startTimeNanos", pt.get("endTimeNanos", 0)))
                    if pt_time_ns == 0:
                        continue
                    pt_time = datetime.datetime.fromtimestamp(pt_time_ns / 1e9)
                    values = pt.get("value", [])
                    if values and values[0].get("fpVal") is not None:
                        results.append((pt_time, float(values[0].get("fpVal"))))
                if results:
                    return sorted(results, key=lambda x: x[0])
            except Exception:
                pass

        # Fallback to aggregate query
        try:
            body = {
                "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                "bucketByTime": {"durationMillis": 10000},
                "startTimeMillis": int(start_dt.timestamp() * 1000),
                "endTimeMillis": int(end_dt.timestamp() * 1000)
            }
            res = self.service.users().dataset().aggregate(userId="me", body=body).execute()
            for bucket in res.get("bucket", []):
                b_start_ms = int(bucket.get("startTimeMillis", 0))
                b_time = datetime.datetime.fromtimestamp(b_start_ms / 1000.0)
                for ds in bucket.get("dataset", []):
                    for pt in ds.get("point", []):
                        for val in pt.get("value", []):
                            if val.get("fpVal") is not None:
                                results.append((b_time, float(val.get("fpVal"))))
            return sorted(results, key=lambda x: x[0])
        except Exception:
            return []

    def check_recent_steps(self, minutes: int = 10) -> int:
        """Returns total steps in last N minutes. 0 steps = physical stillness (sleep)."""
        if not self.service:
            return -1
        now = datetime.datetime.now()
        start = now - datetime.timedelta(minutes=minutes)
        body = {
            "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
            "startTimeMillis": int(start.timestamp() * 1000),
            "endTimeMillis": int(now.timestamp() * 1000)
        }
        try:
            res = self.service.users().dataset().aggregate(userId="me", body=body).execute()
            total = 0
            for b in res.get("bucket", []):
                for ds in b.get("dataset", []):
                    for pt in ds.get("point", []):
                        for val in pt.get("value", []):
                            total += val.get("intVal", 0)
            return total
        except Exception:
            return -1


class HeartRateLiveMonitor:
    """Live dashboard: heart rate, adaptive baseline, sleep score and detected sleep state."""

    BG, PANEL, GRID, TEXT, MUTED = "#0f1117", "#151922", "#262c3a", "#e6e9f0", "#8b93a7"
    C_HR, C_BASE = "#ff6b81", "#7c8aa5"
    C_STATE = {AWAKE: "#f5a524", DROWSY: "#5b8def", ASLEEP: "#8b5cf6"}
    STATE_LABEL = {AWAKE: "AWAKE", DROWSY: "DROWSY", ASLEEP: "ASLEEP"}

    def __init__(self, mode="google_fit", client=None, lookback_minutes=30, sleep_threshold=None,
                 tv_target="auto", tv_delay=180, lg_ip="192.168.1.215", xiaomi_ip=None,
                 lan_port=8443, view_minutes=30, log_data=True):
        # `sleep_threshold` is accepted for backwards compatibility but no longer used:
        # sleep is detected adaptively by sleep_algo.SleepDetector.
        self.mode = mode
        self.client = client
        self.lookback_minutes = lookback_minutes
        self.lan_port = lan_port
        self.view_minutes = view_minutes

        self.detector = SleepDetector()
        self.logger = HRLogger() if log_data and mode != "mock" else None

        # Smart TV
        self.tv_target = tv_target
        self.tv_delay = tv_delay
        self.tv_manager = SmartTVManager(target_tv=tv_target, lg_ip=lg_ip, xiaomi_ip=xiaomi_ip) if TV_CONTROL_AVAILABLE and tv_target != "none" else None
        self.tv_shutoff_triggered = False

        self.timestamps: deque = deque(maxlen=6 * 3600)
        self.bpms: deque = deque(maxlen=6 * 3600)
        self.lock = threading.Lock()
        self.is_running = True
        self._last_fed = None

        self._build_figure()

    # ------------------------------------------------------------------ figure
    def _build_figure(self):
        plt.rcParams.update({
            "font.family": "sans-serif",
            "font.sans-serif": ["SF Pro Display", "Helvetica Neue", "Arial", "DejaVu Sans"],
            "axes.edgecolor": self.GRID, "text.color": self.TEXT,
        })
        self.fig = plt.figure(figsize=(12, 7), facecolor=self.BG)
        mode_title = {"wifi": "LAN Wi-Fi", "ble": "Bluetooth LE", "mock": "Simulation"}.get(self.mode, "Google Fit")
        self.fig.canvas.manager.set_window_title(f"Sleep Detector - {mode_title}")
        gs = self.fig.add_gridspec(2, 1, height_ratios=[3.2, 1], left=0.065, right=0.975,
                                   top=0.80, bottom=0.08, hspace=0.07)
        self.ax = self.fig.add_subplot(gs[0])
        self.ax_s = self.fig.add_subplot(gs[1], sharex=self.ax)
        for ax in (self.ax, self.ax_s):
            ax.set_facecolor(self.PANEL)
            ax.grid(True, color=self.GRID, linewidth=0.7, alpha=0.8)
            ax.set_axisbelow(True)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
            ax.tick_params(colors=self.MUTED, labelsize=9, length=0)
        plt.setp(self.ax.get_xticklabels(), visible=False)
        self.ax_s.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        self.ax_s.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))

        self.ax.set_ylabel("BPM", color=self.MUTED, fontsize=10)
        self.ax_s.set_ylabel("Sleep score", color=self.MUTED, fontsize=10)
        self.ax_s.set_ylim(0, 1)
        self.ax_s.set_yticks([0, 0.5, 1])
        for y in (self.detector.cfg.drowsy_on, self.detector.cfg.asleep_on):
            self.ax_s.axhline(y, color=self.MUTED, linewidth=0.8, linestyle=(0, (3, 4)), alpha=0.7)

        self.l_raw, = self.ax.plot([], [], color=self.C_HR, linewidth=0.8, alpha=0.35, zorder=2)
        self.l_hr, = self.ax.plot([], [], color=self.C_HR, linewidth=2.4, solid_capstyle="round", zorder=4)
        self.l_base, = self.ax.plot([], [], color=self.C_BASE, linewidth=1.4, linestyle=(0, (5, 4)), zorder=3)
        self.dot, = self.ax.plot([], [], "o", color=self.C_HR, markersize=7,
                                 markeredgecolor=self.BG, markeredgewidth=1.5, zorder=5)
        self.l_score, = self.ax_s.plot([], [], color="#8b5cf6", linewidth=2.0, zorder=3)
        self._bands, self._score_fill = [], None
        self.lbl_base = self.ax.text(0.995, 0.03, "", transform=self.ax.transAxes, ha="right",
                                     color=self.MUTED, fontsize=9)

        # header
        f = self.fig
        f.text(0.065, 0.945, "Sleep Detector", fontsize=19, fontweight="bold", color=self.TEXT, va="center")
        self.t_sub = f.text(0.065, 0.905, "", fontsize=10, color=self.MUTED, va="center")
        self.t_bpm = f.text(0.52, 0.935, "--", fontsize=34, fontweight="bold", color=self.C_HR, ha="right", va="center")
        f.text(0.525, 0.925, "BPM", fontsize=10, color=self.MUTED, va="center")
        self.pill = f.text(0.975, 0.94, "WAITING", fontsize=12, fontweight="bold", color=self.BG, ha="right", va="center",
                           bbox=dict(boxstyle="round,pad=0.55,rounding_size=0.9", facecolor=self.MUTED, edgecolor="none"))
        self.t_detail = f.text(0.975, 0.885, "", fontsize=10, color=self.MUTED, ha="right", va="center")
        self.t_tv = f.text(0.065, 0.845, "", fontsize=10, color=self.TEXT, va="center")
        self.t_feat = f.text(0.975, 0.845, "", fontsize=9, color=self.MUTED, ha="right", va="center")

    # -------------------------------------------------------------------- data
    def on_live_heart_rate(self, dt_: datetime.datetime, bpm: float):
        """Callback for incoming BLE / LAN packets (any thread)."""
        with self.lock:
            self._ingest(dt_, bpm)

    def _ingest(self, dt_, bpm):
        if self._last_fed and dt_ <= self._last_fed:
            return
        self._last_fed = dt_
        self.timestamps.append(dt_)
        self.bpms.append(bpm)
        if self.logger:
            self.logger.log(dt_, bpm)
        self.detector.add(dt_, bpm)

    def start_data_polling(self):
        if self.mode == "ble":
            self.client = BLEHeartRateClient(data_callback=self.on_live_heart_rate)
            self.client.start()
        elif self.mode == "wifi":
            self.lan_receiver = WiFiLANReceiver(data_callback=self.on_live_heart_rate, port=self.lan_port)
            self.lan_receiver.start()
            if self.client:
                threading.Thread(target=self._google_fit_poll_loop, daemon=True).start()
        elif self.mode == "google_fit":
            threading.Thread(target=self._google_fit_poll_loop, daemon=True).start()
        elif self.mode == "mock":
            threading.Thread(target=self._mock_data_loop, daemon=True).start()

    def _google_fit_poll_loop(self):
        first_run = True
        while self.is_running:
            now = datetime.datetime.now()
            try:
                start_time = now - datetime.timedelta(minutes=self.lookback_minutes if first_run else 3)
                first_run = False
                readings = self.client.fetch_heart_rate_range(start_time, now)
                with self.lock:
                    for t, bpm in readings:      # sorted; _ingest skips anything already seen
                        self._ingest(t, bpm)
                steps = self.client.check_recent_steps(minutes=10)
                if steps >= 0:
                    self.detector.recent_steps = steps
            except Exception as e:
                print(f"[WARN] Error polling Google Fit: {e}")
            time.sleep(10)

    def _mock_data_loop(self):
        """Replays a synthetic evening (TV -> drifting off -> asleep) at 40x speed."""
        data = synthetic_night(minutes=120, onset_min=15, start=datetime.datetime.now())
        for i, (t, bpm) in enumerate(data):
            if not self.is_running:
                return
            self.on_live_heart_rate(t, bpm)
            if i % 40 == 0:
                time.sleep(1.0)

    # ------------------------------------------------------------------ drawing
    @staticmethod
    def _smooth(vals, k=15):
        a = np.asarray(vals, dtype=float)
        if len(a) < 3:
            return a
        k = min(k, len(a) | 1)
        pad = np.pad(a, (k // 2, k // 2), mode="edge")
        return np.array([np.median(pad[i:i + k]) for i in range(len(a))])

    def _draw_bands(self, snaps):
        for b in self._bands:
            b.remove()
        self._bands = []
        if not snaps:
            return
        t = mdates.date2num([s.t for s in snaps])
        for state in (DROWSY, ASLEEP):
            mask = np.array([s.state == state for s in snaps])
            for ax in (self.ax, self.ax_s):
                self._bands.append(ax.fill_between(
                    t, 0, 1, where=mask, transform=ax.get_xaxis_transform(),
                    color=self.C_STATE[state], alpha=0.16 if state == DROWSY else 0.22,
                    linewidth=0, step="post", zorder=1))

    def _tv_status(self, now_dt):
        if not self.tv_manager:
            return "TV auto-off: disabled"
        det = self.detector
        if self.tv_shutoff_triggered:
            return "TV  powered off (sleep detected)"
        if det.is_asleep and det.asleep_since:
            sustained = (now_dt - det.asleep_since).total_seconds()
            if sustained >= self.tv_delay:
                self.tv_shutoff_triggered = True
                threading.Thread(target=self.tv_manager.turn_off_tv, daemon=True).start()
                return "TV  powering off..."
            return f"TV  shutting off in {int(self.tv_delay - sustained)}s"
        return f"TV  auto-off armed ({self.tv_delay}s after sleep onset)"

    def update_plot(self, frame):
        det = self.detector
        with self.lock:
            times, bpms = list(self.timestamps), list(self.bpms)
            snaps = list(det.snapshots)
            last_t = det._last_t
        if not times:
            msg = getattr(self.client, "status_message", None) if self.mode == "ble" else None
            self.t_sub.set_text(msg or "Waiting for heart rate data...")
            return ()

        end = times[-1]
        start = end - datetime.timedelta(minutes=self.view_minutes)
        i0 = next((i for i, t in enumerate(times) if t >= start), 0)
        vt, vb = times[i0:], bpms[i0:]
        smooth = self._smooth(vb)
        self.l_raw.set_data(vt, vb)
        self.l_hr.set_data(vt, smooth)
        self.dot.set_data([vt[-1]], [smooth[-1]])

        vs = [s for s in snaps if s.t >= start]
        if vs:
            st = [s.t for s in vs]
            self.l_base.set_data(st, [s.baseline for s in vs])
            self.l_score.set_data(st, [s.score for s in vs])
            if self._score_fill:
                self._score_fill.remove()
            self._score_fill = self.ax_s.fill_between(st, 0, [s.score for s in vs],
                                                      color="#8b5cf6", alpha=0.18, linewidth=0, zorder=2)
        self._draw_bands(vs)

        self.ax.set_xlim(start, end + datetime.timedelta(seconds=max(10, self.view_minutes * 4)))
        lo, hi = min(vb), max(vb)
        if vs:
            lo, hi = min(lo, min(s.baseline for s in vs) - 2), max(hi, max(s.baseline for s in vs))
        self.ax.set_ylim(max(30, lo - 5), hi + 6)

        # header
        snap = snaps[-1] if snaps else None
        cur = smooth[-1]
        self.t_bpm.set_text(f"{cur:.0f}")
        if snap:
            col = self.C_STATE[snap.state]
            self.pill.set_text(f"  {self.STATE_LABEL[snap.state]}  ")
            self.pill.get_bbox_patch().set_facecolor(col)
            asleep_for = ""
            if det.is_asleep and det.asleep_since and last_t:
                asleep_for = f"  -  asleep for {int((last_t - det.asleep_since).total_seconds() // 60)} min"
            self.t_detail.set_text(f"sleep probability {snap.score * 100:.0f}%{asleep_for}")
            self.t_feat.set_text(
                f"drop {snap.drop:.2f}   stability {snap.stability:.2f}   "
                f"smooth {snap.smoothness:.2f}   trend {snap.trend:.2f}"
                + (f"   |  {snap.reason}" if snap.reason else ""))
            self.lbl_base.set_text(f"awake baseline {snap.baseline:.0f} BPM (adaptive)")
        else:
            self.pill.set_text("  LEARNING  ")
            self.t_detail.set_text("calibrating your baseline (~3 min)")
            self.t_feat.set_text("")
        src = {"ble": "Bluetooth LIVE", "wifi": "LAN Wi-Fi", "mock": "Simulation"}.get(self.mode, "Google Fit")
        self.t_sub.set_text(f"{src}  -  last sample {end:%H:%M:%S}  -  min {min(vb):.0f} / max {max(vb):.0f} BPM (window)")
        self.t_tv.set_text(self._tv_status(last_t or end))
        return ()

    def run(self):
        self.start_data_polling()
        interval = 1000 if self.mode in ("ble", "wifi", "mock") else 2000
        self._ani = FuncAnimation(self.fig, self.update_plot, interval=interval, cache_frame_data=False)
        plt.show()
        self.is_running = False


def main():
    parser = argparse.ArgumentParser(description="Live Heart Rate Plotter & Sleep Detector (Google Fitbit Air)")
    parser.add_argument("--ble", action="store_true", help="Connect directly to Google Fitbit Air via Bluetooth")
    parser.add_argument("--wifi", action="store_true", help="Run in LAN Wi-Fi mode (accepts local HTTP/REST packets + Google Fit cloud)")
    parser.add_argument("--credentials", default=find_credentials_file(), help="Path to Google OAuth client secret JSON")
    parser.add_argument("--threshold", type=float, default=None, help="(deprecated, ignored) sleep is now detected adaptively")
    parser.add_argument("--view", type=int, default=30, help="Minutes of history shown in the graph (default: 30)")
    parser.add_argument("--no-log", action="store_true", help="Do not save samples to hr_logs/*.csv")
    parser.add_argument("--lookback", type=int, default=30, help="Initial lookback window in minutes (Google Fit mode)")
    parser.add_argument("--mock", action="store_true", help="Run with simulated data for testing without live syncing")
    parser.add_argument("--tv", default="auto", choices=["auto", "lg", "xiaomi", "both", "none"], help="Smart TV to shut off when sleep detected")
    parser.add_argument("--tv-delay", type=int, default=180, help="Continuous seconds of sleep before turning off TV (default: 180s / 3m)")
    parser.add_argument("--lg-ip", default="192.168.1.215", help="LG webOS TV IP address (default: 192.168.1.215)")
    parser.add_argument("--xiaomi-ip", default=None, help="Xiaomi TV Box IP address (optional)")
    parser.add_argument("--port", type=int, default=8443, help="LAN Wi-Fi HTTP/HTTPS receiver port (default: 8443)")
    args = parser.parse_args()

    mode = "google_fit"
    client = None

    if args.mock:
        mode = "mock"
    elif args.ble:
        mode = "ble"
    elif args.wifi:
        mode = "wifi"
        try:
            client = GoogleFitClient(credentials_path=args.credentials)
            client.authenticate()
        except Exception:
            client = None
    else:
        mode = "google_fit"
        try:
            client = GoogleFitClient(credentials_path=args.credentials)
            client.authenticate()
        except Exception as e:
            print(f"[ERROR] Could not authenticate with Google Fitness API: {e}")
            print("Try running in Bluetooth mode: python heart_rate_live.py --ble")
            print("Or LAN Wi-Fi mode: python heart_rate_live.py --wifi")
            sys.exit(1)

    monitor = HeartRateLiveMonitor(
        mode=mode,
        client=client,
        lookback_minutes=args.lookback,
        view_minutes=args.view,
        log_data=not args.no_log,
        tv_target=args.tv,
        tv_delay=args.tv_delay,
        lg_ip=args.lg_ip,
        xiaomi_ip=args.xiaomi_ip,
        lan_port=args.port
    )
    monitor.run()


if __name__ == "__main__":
    main()
