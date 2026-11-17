"""
Quick scratch launcher for Sleep Detector.
Run directly to launch the live heart rate monitor with smart TV auto-shutoff!
"""

import sys
import warnings
warnings.filterwarnings("ignore")

from heart_rate_live import GoogleFitClient, HeartRateLiveMonitor

if __name__ == "__main__":
    print("[*] Launching Sleep Detector...")

    mode = "ble" if "--ble" in sys.argv else ("mock" if "--mock" in sys.argv else "ble")

    client = None
    if mode == "google_fit":
        try:
            client = GoogleFitClient()
            client.authenticate()
        except Exception as e:
            print(f"[!] Google Fit failed ({e}), falling back to Bluetooth mode (--ble)...")
            mode = "ble"

    monitor = HeartRateLiveMonitor(
        mode=mode,
        client=client,
        lookback_minutes=30,
        view_minutes=30,
        tv_target="auto",
        tv_delay=180,  # 3 minutes of sustained sleep
        lg_ip="192.168.1.215"
    )
    monitor.run()



