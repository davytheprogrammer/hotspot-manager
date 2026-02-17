#!/usr/bin/env python3
import subprocess
import json
import re
import os
import logging
import time
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class HotspotConfig:
    ssid: str
    password: str
    interface: str
    channel: int = 6
    band: str = "bg"
    ip_range_start: str = "10.42.0.10"
    ip_range_end: str = "10.42.0.100"
    gateway: str = "10.42.0.1"


class ConcurrentHotspotManager:
    def __init__(self):
        self.hotspot_active = False
        self.current_config: Optional[HotspotConfig] = None
        self._monitor_thread = None
        self._stop_monitor = threading.Event()
        self._callbacks: List[callable] = []
        self._nm_concurrent_capable = self._check_nm_concurrent_support()

    def _check_nm_concurrent_support(self) -> bool:
        try:
            result = subprocess.run(
                ["nmcli", "--version"], capture_output=True, text=True
            )
            version_match = re.search(r"(\d+)\.(\d+)", result.stdout)
            if version_match:
                major = int(version_match.group(1))
                minor = int(version_match.group(2))
                return major > 1 or (major == 1 and minor >= 40)
        except Exception:
            pass
        return False

    def register_callback(self, callback: callable):
        self._callbacks.append(callback)

    def _notify_callbacks(self, event: str, data: dict = None):
        for callback in self._callbacks:
            try:
                callback(event, data or {})
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def get_connected_wifi_ssid(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("yes:"):
                    ssid = line.split(":", 1)[1]
                    return ssid if ssid else None
        except Exception:
            pass
        return None

    def get_connected_wifi_interface(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 3:
                    device, dev_type, state = parts[0], parts[1], parts[2]
                    if dev_type == "wifi" and state == "connected":
                        return device
        except Exception:
            pass
        return None

    def start_concurrent_hotspot_nmcli(self, config: HotspotConfig) -> Tuple[bool, str]:
        logger.info(
            f"Starting concurrent hotspot with NetworkManager on {config.interface}"
        )

        connected_ssid = self.get_connected_wifi_ssid()
        if not connected_ssid:
            return False, "No WiFi connection active. Connect to WiFi first."

        hotspot_name = f"Hotspot-{config.ssid}"

        try:
            subprocess.run(
                ["nmcli", "connection", "delete", hotspot_name], capture_output=True
            )

            cmd = [
                "nmcli",
                "device",
                "wifi",
                "hotspot",
                "ifname",
                config.interface,
                "con-name",
                hotspot_name,
                "ssid",
                config.ssid,
                "channel",
                str(config.channel),
                "band",
                config.band,
                "password",
                config.password,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                logger.error(f"Hotspot creation failed: {error_msg}")
                return False, f"Failed to create hotspot: {error_msg}"

            self._configure_hotspot_ip(hotspot_name, config)

            subprocess.run(
                ["nmcli", "connection", "up", hotspot_name], capture_output=True
            )

            time.sleep(2)

            wifi_still_connected = self._verify_wifi_connected(connected_ssid)
            hotspot_running = self._verify_hotspot_running(hotspot_name)

            if wifi_still_connected and hotspot_running:
                self.hotspot_active = True
                self.current_config = config
                self._notify_callbacks("hotspot_started", {"ssid": config.ssid})
                self._start_monitoring()
                return (
                    True,
                    f"Concurrent hotspot active! WiFi: {connected_ssid}, Hotspot: {config.ssid}",
                )
            elif not wifi_still_connected:
                return (
                    False,
                    "WiFi connection was lost when creating hotspot. Hardware may not support concurrent mode.",
                )
            else:
                return False, "Hotspot failed to start properly."

        except Exception as e:
            logger.error(f"Error starting hotspot: {e}")
            return False, f"Error: {str(e)}"

    def _configure_hotspot_ip(self, connection_name: str, config: HotspotConfig):
        try:
            subprocess.run(
                [
                    "nmcli",
                    "connection",
                    "modify",
                    connection_name,
                    "ipv4.method",
                    "shared",
                    "ipv4.addresses",
                    f"{config.gateway}/24",
                ],
                capture_output=True,
            )

            logger.info(f"Configured IP sharing on {connection_name}")
        except Exception as e:
            logger.warning(f"Could not configure IP: {e}")

    def _verify_wifi_connected(self, expected_ssid: str) -> bool:
        current_ssid = self.get_connected_wifi_ssid()
        return current_ssid == expected_ssid

    def _verify_hotspot_running(self, connection_name: str) -> bool:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,STATE", "connection", "show", "--active"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if connection_name in line and "activated" in line.lower():
                    return True
        except Exception:
            pass
        return False

    def stop_hotspot(self) -> Tuple[bool, str]:
        if not self.hotspot_active:
            return True, "No hotspot active"

        self._stop_monitoring()

        try:
            hotspot_name = (
                f"Hotspot-{self.current_config.ssid}"
                if self.current_config
                else "Hotspot"
            )

            result = subprocess.run(
                ["nmcli", "connection", "down", hotspot_name],
                capture_output=True,
                text=True,
            )

            subprocess.run(
                ["nmcli", "connection", "delete", hotspot_name], capture_output=True
            )

            self.hotspot_active = False
            self.current_config = None
            self._notify_callbacks("hotspot_stopped", {})

            return True, "Hotspot stopped successfully"

        except Exception as e:
            logger.error(f"Error stopping hotspot: {e}")
            return False, f"Error: {str(e)}"

    def _start_monitoring(self):
        self._stop_monitor.set()
        time.sleep(0.5)
        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_monitoring(self):
        self._stop_monitor.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)

    def _monitor_loop(self):
        while not self._stop_monitor.is_set():
            if self.hotspot_active and self.current_config:
                wifi_connected = self.get_connected_wifi_ssid() is not None
                hotspot_running = self._verify_hotspot_running(
                    f"Hotspot-{self.current_config.ssid}"
                )

                if not wifi_connected:
                    logger.warning("WiFi connection lost!")
                    self._notify_callbacks("wifi_lost", {})
                    self.stop_hotspot()
                    break
                elif not hotspot_running:
                    logger.warning("Hotspot stopped unexpectedly!")
                    self._notify_callbacks("hotspot_lost", {})
                    self.hotspot_active = False
                    break

            self._stop_monitor.wait(5)

    def get_connected_clients(self) -> List[Dict]:
        clients = []
        if not self.hotspot_active or not self.current_config:
            return clients

        try:
            result = subprocess.run(["arp", "-a"], capture_output=True, text=True)

            gateway = self.current_config.gateway
            for line in result.stdout.splitlines():
                if gateway not in line and "(" in line:
                    match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)", line)
                    if match:
                        ip = match.group(1)
                        if ip.startswith(".".join(gateway.split(".")[:3])):
                            hostname = line.split()[0] if line.split() else "unknown"
                            clients.append({"ip": ip, "hostname": hostname})
        except Exception:
            pass

        return clients

    def get_status(self) -> Dict:
        wifi_ssid = self.get_connected_wifi_ssid()
        wifi_interface = self.get_connected_wifi_interface()

        return {
            "wifi_connected": wifi_ssid is not None,
            "wifi_ssid": wifi_ssid,
            "wifi_interface": wifi_interface,
            "hotspot_active": self.hotspot_active,
            "hotspot_ssid": self.current_config.ssid if self.current_config else None,
            "connected_clients": len(self.get_connected_clients()),
        }

    def save_config(self, config: HotspotConfig, config_path: str = None):
        path = Path(
            config_path or os.path.expanduser("~/.config/hotspot-manager/config.json")
        )
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(
                {
                    "ssid": config.ssid,
                    "password": config.password,
                    "interface": config.interface,
                    "channel": config.channel,
                    "band": config.band,
                },
                f,
            )

        logger.info(f"Config saved to {path}")

    def load_config(self, config_path: str = None) -> Optional[HotspotConfig]:
        path = Path(
            config_path or os.path.expanduser("~/.config/hotspot-manager/config.json")
        )

        if not path.exists():
            return None

        try:
            with open(path) as f:
                data = json.load(f)

            return HotspotConfig(
                ssid=data.get("ssid", "MyHotspot"),
                password=data.get("password", ""),
                interface=data.get("interface", "wlan0"),
                channel=data.get("channel", 6),
                band=data.get("band", "bg"),
            )
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return None
