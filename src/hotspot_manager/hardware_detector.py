#!/usr/bin/env python3
import subprocess
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WifiInterface:
    name: str
    driver: str
    supports_ap: bool
    supports_concurrent: bool
    max_concurrent_channels: int
    phy_number: int
    current_mode: str
    connected: bool


def freq_to_channel(freq_mhz: int) -> Optional[int]:
    if freq_mhz == 2484:
        return 14
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if 5000 <= freq_mhz <= 5900:
        return (freq_mhz - 5000) // 5
    if 5955 <= freq_mhz <= 7115:
        return (freq_mhz - 5950) // 5
    return None


def channel_to_band(channel: int) -> str:
    return "bg" if channel <= 14 else "a"


class HardwareDetector:
    def __init__(self):
        self.interfaces: List[WifiInterface] = []

    def get_wifi_interfaces(self) -> List[WifiInterface]:
        self.interfaces = []
        try:
            iw_result = subprocess.run(
                ["iw", "dev"], capture_output=True, text=True, check=True
            )
            current_phy = None

            for line in iw_result.stdout.splitlines():
                if line.strip().startswith("phy#"):
                    match = re.search(r"phy#(\d+)", line)
                    if match:
                        current_phy = int(match.group(1))
                elif line.strip().startswith("Interface"):
                    iface_name = line.split()[-1]
                    if current_phy is not None:
                        driver = self._get_driver(iface_name)
                        self.interfaces.append(
                            WifiInterface(
                                name=iface_name,
                                driver=driver,
                                supports_ap=False,
                                supports_concurrent=False,
                                max_concurrent_channels=1,
                                phy_number=current_phy,
                                current_mode="unknown",
                                connected=False,
                            )
                        )

            for iface in self.interfaces:
                self._check_ap_support(iface)
                self._check_current_state(iface)

            return self.interfaces
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get wifi interfaces: {e}")
            return []

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

    def get_phy_combinations(self, phy_number: int) -> List[Dict]:
        """Parse `iw phy phyN info` 'valid interface combinations' into
        structured data: each combo is a dict with 'groups' (list of
        (role_names, max_count)), 'total' and 'channels' limits."""
        combos = []
        try:
            result = subprocess.run(
                ["iw", "phy", f"phy{phy_number}", "info"],
                capture_output=True,
                text=True,
            )
            output = result.stdout
        except Exception:
            return combos

        match = re.search(
            r"valid interface combinations:\s*\n(.*?)(?:\n\S|\Z)", output, re.DOTALL
        )
        if not match:
            return combos

        block = match.group(1)
        # Each combo is a "*"-prefixed bullet, possibly wrapped over lines.
        bullets = re.split(r"\n\s*\*\s*", "\n * " + block.strip())
        for bullet in bullets:
            bullet = bullet.strip()
            if not bullet:
                continue

            groups = []
            for group_match in re.finditer(
                r"#\{\s*([^}]+?)\s*\}\s*<=\s*(\d+)", bullet
            ):
                roles = [r.strip() for r in group_match.group(1).split(",")]
                groups.append((roles, int(group_match.group(2))))

            total_match = re.search(r"total\s*<=\s*(\d+)", bullet)
            channels_match = re.search(r"#channels\s*<=\s*(\d+)", bullet)

            if groups:
                combos.append(
                    {
                        "groups": groups,
                        "total": int(total_match.group(1)) if total_match else None,
                        "channels": int(channels_match.group(1))
                        if channels_match
                        else 1,
                    }
                )

        return combos

    def _check_ap_support(self, iface: WifiInterface):
        try:
            result = subprocess.run(
                ["iw", "phy", f"phy{iface.phy_number}", "info"],
                capture_output=True,
                text=True,
            )
            output = result.stdout
            iface.supports_ap = "\t\t * AP\n" in output or "* AP\n" in output

            combos = self.get_phy_combinations(iface.phy_number)
            best_channels = 0
            concurrent = False

            for combo in combos:
                managed_ok = any(
                    "managed" in roles and count >= 1 for roles, count in combo["groups"]
                )
                ap_ok = any(
                    "AP" in roles and count >= 1 for roles, count in combo["groups"]
                )
                total_ok = combo["total"] is None or combo["total"] >= 2

                # A single group covering both roles with count>=2 also counts
                # (e.g. "#{ managed, AP } <= 2").
                combined_ok = any(
                    "managed" in roles and "AP" in roles and count >= 2
                    for roles, count in combo["groups"]
                )

                if total_ok and (combined_ok or (managed_ok and ap_ok)):
                    concurrent = True
                    best_channels = max(best_channels, combo["channels"] or 1)

            iface.supports_concurrent = concurrent
            iface.max_concurrent_channels = best_channels or 1

            if iface.supports_concurrent:
                logger.info(
                    f"{iface.name} supports concurrent AP+managed mode "
                    f"(max {iface.max_concurrent_channels} channel(s) simultaneously)"
                )
            elif iface.supports_ap:
                logger.info(
                    f"{iface.name} supports AP mode but NOT concurrent with managed "
                    f"mode on the same radio (hotspot will disconnect existing WiFi)"
                )

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

    def get_current_channel(self, interface: str) -> Optional[Tuple[int, str]]:
        """Return (channel, band) the interface is currently operating on,
        or None if it can't be determined (e.g. not connected)."""
        try:
            result = subprocess.run(
                ["iw", "dev", interface, "link"], capture_output=True, text=True
            )
            match = re.search(r"freq:\s*(\d+)", result.stdout)
            if not match:
                result = subprocess.run(
                    ["iw", "dev", interface, "info"], capture_output=True, text=True
                )
                match = re.search(r"channel\s+\d+\s+\((\d+)\s*MHz\)", result.stdout)

            if match:
                freq = int(match.group(1))
                channel = freq_to_channel(freq)
                if channel is not None:
                    return channel, channel_to_band(channel)
        except Exception as e:
            logger.error(f"Error reading current channel for {interface}: {e}")
        return None

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
