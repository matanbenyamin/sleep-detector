#!/usr/bin/env python3
"""
Smart TV Controller for Sleep Detector.
Supports:
  1. LG Smart TV (webOS) via WebSocket over LAN Wi-Fi.
  2. Xiaomi TV Box (Android TV) via ADB over LAN Wi-Fi.
  3. HDMI-CEC sync (turning off LG TV automatically turns off Xiaomi TV Box, and vice versa).
"""

import os
import sys
import json
import time
import argparse
import subprocess
from typing import Optional, Dict, Any

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LG_KEY_FILE = os.path.join(PROJECT_DIR, "lgtv_key.json")
DEFAULT_LG_IP = "192.168.1.215"
XIAOMI_IP = "192.168.1.241"

class LGWebOSTVController:
    """Controls LG Smart TV (webOS) over local Wi-Fi / LAN."""

    def __init__(self, ip: str = DEFAULT_LG_IP, key_file: str = LG_KEY_FILE):
        self.ip = ip
        self.key_file = key_file
        self.client = None
        self.store = self._load_store()

    def _load_store(self) -> Dict[str, Any]:
        if os.path.exists(self.key_file):
            try:
                with open(self.key_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_store(self):
        try:
            with open(self.key_file, "w") as f:
                json.dump(self.store, f, indent=2)
        except Exception as e:
            print(f"[WARN] Failed to save LG TV pairing key: {e}")

    def pair_and_connect(self, timeout: int = 20) -> bool:
        """Connects and pairs with LG TV. Shows on-screen prompt on TV if first time."""
        try:
            from pywebostv.connection import WebOSClient
            from pywebostv.controls import SystemControl

            print(f"[*] Connecting to LG TV at {self.ip}...")
            self.client = WebOSClient(self.ip)
            self.client.connect()

            for status in self.client.register(self.store, timeout=timeout):
                if status == WebOSClient.PROMPTED:
                    print("=" * 60)
                    print("👉 [ACTION REQUIRED] Please look at your LG TV screen!")
                    print("   Click 'Accept' / 'Allow' with your remote control.")
                    print("=" * 60)
                elif status == WebOSClient.REGISTERED:
                    print("[✓] LG TV Paired and Connected successfully!")
                    self._save_store()
                    return True
            return True
        except Exception as e:
            print(f"[!] Could not connect to LG TV at {self.ip}: {e}")
            return False

    def turn_off(self) -> bool:
        """Powers down the LG TV over LAN Wi-Fi."""
        try:
            from pywebostv.connection import WebOSClient
            from pywebostv.controls import SystemControl

            if not self.client:
                self.client = WebOSClient(self.ip)
                self.client.connect()
                for _ in self.client.register(self.store, timeout=5):
                    pass

            system = SystemControl(self.client)
            system.power_off()
            print(f"[✓] Sent POWER OFF command to LG TV ({self.ip}) over LAN Wi-Fi.")
            return True
        except Exception as e:
            print(f"[!] Error powering off LG TV: {e}")
            return False


class XiaomiTVController:
    """Controls Xiaomi TV Box (Android TV) via ADB over LAN Wi-Fi."""

    def __init__(self, ip: Optional[str] = None, port: int = 5555):
        self.ip = ip
        self.port = port
        self.device = None

    def turn_off(self) -> bool:
        """Sends Android TV power/sleep keyevent (26 / 223)."""
        if not self.ip:
            print("[!] Xiaomi TV Box IP not configured.")
            return False

        try:
            from adb_shell.adb_device import AdbDeviceTcp
            from adb_shell.auth.sign_pythonrsa import PythonRSASigner
            from adb_shell.auth.keygen import keygen

            priv_key_path = os.path.join(PROJECT_DIR, "adbkey")
            if not os.path.exists(priv_key_path):
                keygen(priv_key_path)

            with open(priv_key_path, "r") as f:
                priv = f.read()
            with open(priv_key_path + ".pub", "r") as f:
                pub = f.read()
            signer = PythonRSASigner(pub, priv)

            print(f"[*] Connecting to Xiaomi TV Box at {self.ip}:{self.port}...")
            self.device = AdbDeviceTcp(self.ip, self.port, default_transport_timeout_s=6.0)
            self.device.connect(rsa_keys=[signer], auth_timeout_s=5.0)

            # Keycode 26 = KEYCODE_POWER, 223 = KEYCODE_SLEEP
            self.device.shell("input keyevent 223 || input keyevent 26")
            print(f"[✓] Sent SLEEP command to Xiaomi TV Box ({self.ip}) over LAN Wi-Fi.")
            return True
        except Exception as e:
            # Fallback to local adb CLI if available
            try:
                subprocess.run(["adb", "connect", f"{self.ip}:{self.port}"], check=False, stdout=subprocess.DEVNULL)
                subprocess.run(["adb", "-s", f"{self.ip}:{self.port}", "shell", "input", "keyevent", "26"], check=False)
                print(f"[✓] Sent POWER command to Xiaomi TV via adb CLI.")
                return True
            except Exception:
                print(f"[!] Error sending power off to Xiaomi TV Box: {e}")
                return False


class SmartTVManager:
    """Unified controller for shutting down TVs when sleep is detected."""

    def __init__(self, target_tv: str = "auto", lg_ip: str = DEFAULT_LG_IP, xiaomi_ip: Optional[str] = None):
        self.target_tv = target_tv.lower()
        self.lg_controller = LGWebOSTVController(ip=lg_ip)
        self.xiaomi_controller = XiaomiTVController(ip=xiaomi_ip) if xiaomi_ip else None
        self.turned_off = False

    def turn_off_tv(self) -> bool:
        """Powers off the configured TV."""
        if self.turned_off:
            return True

        success = False
        if self.target_tv in ("lg", "auto"):
            print("[SLEEP DETECTOR] Triggering LG TV turn-off over Wi-Fi...")
            if self.lg_controller.turn_off():
                success = True

        if self.target_tv in ("xiaomi", "both") or (self.target_tv == "auto" and not success and self.xiaomi_controller):
            if self.xiaomi_controller:
                print("[SLEEP DETECTOR] Triggering Xiaomi TV Box turn-off over Wi-Fi...")
                if self.xiaomi_controller.turn_off():
                    success = True

        if success:
            self.turned_off = True
        return success


def main():
    parser = argparse.ArgumentParser(description="Sleep Detector — Smart TV Remote Controller")
    parser.add_argument("--pair-lg", action="store_true", help="Pair with LG webOS TV (shows prompt on TV screen)")
    parser.add_argument("--turn-off-lg", action="store_true", help="Send turn-off command to LG TV")
    parser.add_argument("--turn-off-xiaomi", action="store_true", help="Send turn-off command to Xiaomi TV Box")
    parser.add_argument("--lg-ip", default=DEFAULT_LG_IP, help="LG TV IP address (default: 192.168.1.215)")
    parser.add_argument("--xiaomi-ip", default=XIAOMI_IP, help="Xiaomi TV Box IP address")
    args = parser.parse_args()

    if args.pair_lg:
        lg = LGWebOSTVController(ip=args.lg_ip)
        lg.pair_and_connect()
    elif args.turn_off_lg:
        lg = LGWebOSTVController(ip=args.lg_ip)
        lg.turn_off()
    elif args.turn_off_xiaomi:
        if not args.xiaomi_ip:
            print("[!] Please provide --xiaomi-ip <IP_ADDRESS>")
            sys.exit(1)
        xiaomi = XiaomiTVController(ip=args.xiaomi_ip)
        xiaomi.turn_off()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
