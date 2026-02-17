#!/usr/bin/env python3
import subprocess
import re
from dataclasses import dataclass
from typing import Optional, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WifiInterface:
    name: str
    driver: str
    supports_ap: bool
    supports_concurrent: bool
    phy_number: int
    current_mode: str
    connected: bool


class HardwareDetector:
    def __init__(self):
        self.interfaces: List[WifiInterface] = []

    def get_wifi_interfaces(self) -> List[WifiInterface]:
        self.interfaces = []
        try:
            iw_result = subprocess.run(
                ["iw", "dev"], capture_output=True, text=True, check=True
            )
            current_if = None
            current_phy = None

            for line in iw_result.stdout.splitlines():
                if line.strip().startswith("Interface"):
                    if current_if:
                        self._finalize_interface(current_if)
                    current_if = {
                        "name": line.split()[-1],
                        "phy": current_phy,
                        "modes": [],
                    }
                elif line.strip().startswith("wiphy"):
                    current_phy = int(line.split()[-1])
                    if current_if:
                        current_if["phy"] = current_phy

            if current_if:
                self._finalize_interface(current_if)

            for iface in self.interfaces:
                self._check_ap_support(iface)
                self._check_current_state(iface)

            return self.interfaces
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get wifi interfaces: {e}")
            return []

    def _finalize_interface(self, iface_data: dict):
        driver = self._get_driver(iface_data["name"])
        self.interfaces.append(
            WifiInterface(
                name=iface_data["name"],
                driver=driver,
                supports_ap=False,
                supports_concurrent=False,
                phy_number=iface_data.get("phy", 0),
                current_mode="unknown",
                connected=False,
            )
        )

    def _get_driver(self, interface: str) -> str:
        try:
            result = subprocess.run(
                ["readlink", "-f", f"/sys/class/net/{interface}/device/driver"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("/")[-1]
        except Exception:
            pass
        return "unknown"

    def _check_ap_support(self, iface: WifiInterface):
        try:
            result = subprocess.run(
                ["iw", "phy", f"phy{iface.phy_number}", "info"],
                capture_output=True,
                text=True,
            )

            output = result.stdout
            iface.supports_ap = "AP" in output

            supports_ap_vlan = "AP/VLAN" in output
            iface.supports_concurrent = iface.supports_ap and supports_ap_vlan

            if iface.supports_concurrent:
                logger.info(f"{iface.name} supports concurrent mode (AP + managed)")

        except subprocess.CalledProcessError:
            iface.supports_ap = False
            iface.supports_concurrent = False

    def _check_current_state(self, iface: WifiInterface):
        try:
            nmcli_result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device", "status"],
                capture_output=True,
                text=True,
            )

            for line in nmcli_result.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[0] == iface.name:
                    state = parts[1]
                    iface.connected = state in ["connected", "connected (externally)"]
                    if "Hotspot" in line or "ap" in line.lower():
                        iface.current_mode = "hotspot"
                    elif iface.connected:
                        iface.current_mode = "managed"
                    break

            iw_result = subprocess.run(
                ["iw", "dev", iface.name, "info"], capture_output=True, text=True
            )

            if "type AP" in iw_result.stdout:
                iface.current_mode = "hotspot"
            elif "type managed" in iw_result.stdout:
                if iface.current_mode != "hotspot":
                    iface.current_mode = "managed"

        except Exception as e:
            logger.error(f"Error checking state for {iface.name}: {e}")

    def get_connected_wifi(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("yes:"):
                    return line.split(":", 1)[1] if ":" in line else None
        except Exception:
            pass
        return None

    def check_hostapd_available(self) -> bool:
        try:
            subprocess.run(["which", "hostapd"], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def check_dnsmasq_available(self) -> bool:
        try:
            subprocess.run(["which", "dnsmasq"], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def get_network_manager_version(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["nmcli", "--version"], capture_output=True, text=True
            )
            match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
            return match.group(1) if match else None
        except Exception:
            return None
