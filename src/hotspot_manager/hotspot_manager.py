#!/usr/bin/env python3
import subprocess
import json
import re
import os
import logging
import time
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, replace
from pathlib import Path
import threading

from .hardware_detector import HardwareDetector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# How long to wait after starting hostapd before checking whether the
# original WiFi (STA) connection survived. Radios that can't truly run
# AP + managed concurrently will drop the STA link almost immediately.
STABILITY_CHECK_DELAY = 3
# How many times to try reconnecting WiFi automatically if it drops while
# a concurrent hotspot is active (auto-recovery).
RECOVERY_ATTEMPTS = 3
RECOVERY_RETRY_DELAY = 5


def get_config_dir() -> str:
    """Directory for this app's config/state. Network operations require
    root, so this app is normally launched with sudo/pkexec - in that case
    os.path.expanduser("~") resolves to /root, not the invoking user's real
    home. Honor SUDO_USER so settings and hostapd/dnsmasq configs land
    somewhere the actual user (and this tool, next run) can find them."""
    home = os.path.expanduser("~")
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and os.geteuid() == 0:
        try:
            import pwd

            home = pwd.getpwnam(sudo_user).pw_dir
        except (KeyError, ImportError):
            pass
    return os.path.join(home, ".config", "hotspot-manager")


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
    internet_interface: str = None


class ConcurrentHotspotManager:
    def __init__(self):
        self.hotspot_active = False
        self.current_config: Optional[HotspotConfig] = None
        self._monitor_thread = None
        self._stop_monitor = threading.Event()
        self._callbacks: List[callable] = []
        self._virtual_interface = None
        self._hostapd_process = None
        self._dnsmasq_process = None
        self._method_used = None
        self._detector = HardwareDetector()
        self._wifi_connection_id = None
        self._wifi_interface_for_recovery = None
        self._recovering = False
        self._last_hostapd_error = ""

    def register_callback(self, callback: callable):
        self._callbacks.append(callback)

    def _notify_callbacks(self, event: str, data: dict = None):
        for callback in self._callbacks:
            try:
                callback(event, data or {})
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def _run_cmd(
        self, cmd: List[str], check: bool = False
    ) -> subprocess.CompletedProcess:
        logger.debug(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            logger.error(f"Command failed: {result.stderr}")
        return result

    def get_connected_wifi_ssid(self) -> Optional[str]:
        try:
            result = self._run_cmd(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
            for line in result.stdout.splitlines():
                if line.startswith("yes:"):
                    ssid = line.split(":", 1)[1]
                    return ssid if ssid else None
        except Exception:
            pass
        return None

    def get_connected_wifi_interface(self) -> Optional[str]:
        try:
            result = self._run_cmd(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"]
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

    def get_internet_interface(self) -> Optional[str]:
        wifi_iface = self.get_connected_wifi_interface()
        if wifi_iface:
            return wifi_iface

        try:
            result = self._run_cmd(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"]
            )
            for line in result.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 3:
                    device, dev_type, state = parts[0], parts[1], parts[2]
                    if dev_type == "ethernet" and state == "connected":
                        return device
        except Exception:
            pass
        return None

    def get_interface_ip(self, interface: str) -> Optional[str]:
        try:
            result = self._run_cmd(["ip", "addr", "show", interface])
            for line in result.stdout.splitlines():
                if "inet " in line:
                    return line.split()[1].split("/")[0]
        except Exception:
            pass
        return None

    def _get_phy_number(self, interface: str) -> Optional[int]:
        try:
            result = self._run_cmd(["iw", "dev", interface, "info"])
            for line in result.stdout.splitlines():
                if "wiphy" in line:
                    return int(line.split()[-1])
        except Exception:
            pass
        return None

    def _get_connection_id(self, interface: str) -> Optional[str]:
        try:
            result = self._run_cmd(
                ["nmcli", "-t", "-f", "GENERAL.CONNECTION", "device", "show", interface]
            )
            for line in result.stdout.splitlines():
                if line.startswith("GENERAL.CONNECTION:"):
                    conn_id = line.split(":", 1)[1]
                    return conn_id if conn_id and conn_id != "--" else None
        except Exception:
            pass
        return None

    def _interface_exists(self, name: str) -> bool:
        return os.path.exists(f"/sys/class/net/{name}")

    def _create_virtual_interface(self, phy: int, base_name: str) -> Optional[str]:
        vif_name = f"{base_name}ap"

        if self._interface_exists(vif_name):
            self._delete_virtual_interface(vif_name)

        try:
            result = self._run_cmd(
                ["iw", "phy", f"phy{phy}", "interface", "add", vif_name, "type", "__ap"]
            )

            if result.returncode == 0 and self._interface_exists(vif_name):
                logger.info(f"Created virtual AP interface: {vif_name}")
                return vif_name

            for suffix in ["0", "1", "2", "3"]:
                vif_name = f"{base_name}{suffix}"
                if not self._interface_exists(vif_name):
                    result = self._run_cmd(
                        [
                            "iw",
                            "phy",
                            f"phy{phy}",
                            "interface",
                            "add",
                            vif_name,
                            "type",
                            "__ap",
                        ]
                    )
                    if result.returncode == 0:
                        return vif_name

            logger.error(f"Failed to create virtual interface: {result.stderr}")
            return None
        except Exception as e:
            logger.error(f"Error creating virtual interface: {e}")
            return None

    def _delete_virtual_interface(self, name: str):
        try:
            self._run_cmd(["iw", "dev", name, "del"])
            logger.info(f"Deleted virtual interface: {name}")
        except Exception:
            pass

    def _setup_ip_forwarding(self):
        self._run_cmd(["sysctl", "-w", "net.ipv4.ip_forward=1"])

        rules = [
            ["iptables", "-t", "nat", "-A", "POSTROUTING", "-j", "MASQUERADE"],
            ["iptables", "-A", "FORWARD", "-j", "ACCEPT"],
        ]
        for rule in rules:
            self._run_cmd(rule)

        logger.info("IP forwarding enabled")

    def _cleanup_ip_forwarding(self):
        rules = [
            ["iptables", "-t", "nat", "-D", "POSTROUTING", "-j", "MASQUERADE"],
            ["iptables", "-D", "FORWARD", "-j", "ACCEPT"],
        ]
        for rule in rules:
            try:
                self._run_cmd(rule)
            except Exception:
                pass

    def _setup_interface_ip(self, interface: str, gateway: str):
        self._run_cmd(["ip", "addr", "flush", "dev", interface])
        self._run_cmd(["ip", "addr", "add", f"{gateway}/24", "dev", interface])
        self._run_cmd(["ip", "link", "set", interface, "up"])
        logger.info(f"Configured {interface} with IP {gateway}")

    def _get_country_code(self) -> Optional[str]:
        try:
            result = self._run_cmd(["iw", "reg", "get"])
            match = re.search(r"^country\s+([A-Z]{2}):", result.stdout, re.MULTILINE)
            if match and match.group(1) != "00":
                return match.group(1)
        except Exception:
            pass
        return None

    def _write_hostapd_config(self, config: HotspotConfig, interface: str) -> str:
        config_dir = get_config_dir()
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "hostapd.conf")
        hw_mode = "g" if config.band == "bg" else "a"

        # No forced HT40/channel-bonding here: when this AP shares a radio
        # with an existing WiFi client link, the client's channel width was
        # already negotiated with the router. Forcing 40MHz on the AP side
        # can conflict with that and is what tends to knock the STA link
        # offline, so we stick to plain 20MHz HT operation.
        country = self._get_country_code()
        # 5GHz (hw_mode=a) needs a regulatory country set, or hostapd/the
        # kernel may refuse to bring up the radio on many 5GHz channels.
        reg_lines = ""
        if country:
            reg_lines = f"country_code={country}\nieee80211d=1\n"
        elif hw_mode == "a":
            logger.warning(
                "No regulatory country code detected; 5GHz AP mode may fail "
                "to start without one (run: sudo iw reg set <COUNTRY>)"
            )

        content = f"""interface={interface}
driver=nl80211
ssid={config.ssid}
hw_mode={hw_mode}
channel={config.channel}
{reg_lines}ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase={config.password}
"""

        with open(config_path, "w") as f:
            f.write(content)

        return config_path

    def _write_dnsmasq_config(self, config: HotspotConfig, interface: str) -> str:
        config_dir = get_config_dir()
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "dnsmasq.conf")

        content = f"""interface={interface}
bind-interfaces
dhcp-range={config.ip_range_start},{config.ip_range_end},12h
dhcp-option=3,{config.gateway}
dhcp-option=6,8.8.8.8,8.8.4.4
domain=local
"""

        with open(config_path, "w") as f:
            f.write(content)

        return config_path

    def _start_hostapd(self, config_path: str) -> bool:
        self._last_hostapd_error = ""
        try:
            # Deliberately NOT using hostapd's own "-B" (daemonize) flag:
            # with -B, hostapd forks to the background and the process we
            # launched exits almost immediately with code 0 on SUCCESS,
            # which looks identical to "already dead" from our side. Instead
            # we keep it in the foreground under our own Popen handle so
            # poll() reliably tells us whether it's still alive, which is
            # also what the crash monitor relies on later.
            self._hostapd_process = subprocess.Popen(
                ["hostapd", config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(2)
            if self._hostapd_process.poll() is None:
                return True

            try:
                _, stderr = self._hostapd_process.communicate(timeout=2)
            except Exception:
                stderr = ""
            self._last_hostapd_error = (stderr or "").strip()
            logger.error(f"hostapd exited immediately: {self._last_hostapd_error}")
            return False
        except Exception as e:
            logger.error(f"Failed to start hostapd: {e}")
            self._last_hostapd_error = str(e)
            return False

    def _start_dnsmasq(self, config_path: str) -> bool:
        try:
            self._dnsmasq_process = subprocess.Popen(
                ["dnsmasq", "-C", config_path, "--no-daemon"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(1)
            return True
        except Exception as e:
            logger.error(f"Failed to start dnsmasq: {e}")
            return False

    def _stop_hostapd(self):
        if self._hostapd_process:
            try:
                self._hostapd_process.terminate()
                self._hostapd_process.wait(timeout=5)
            except Exception:
                self._hostapd_process.kill()
            self._hostapd_process = None

        self._run_cmd(["pkill", "-f", "hostapd.*hotspot"])

    def _stop_dnsmasq(self):
        if self._dnsmasq_process:
            try:
                self._dnsmasq_process.terminate()
                self._dnsmasq_process.wait(timeout=5)
            except Exception:
                self._dnsmasq_process.kill()
            self._dnsmasq_process = None

        self._run_cmd(["pkill", "-f", "dnsmasq.*hotspot"])

    def start_hotspot(self, config: HotspotConfig) -> Tuple[bool, str]:
        internet_iface = config.internet_interface or self.get_internet_interface()

        if not internet_iface:
            return (
                False,
                "No internet connection found. Connect to WiFi or Ethernet first.",
            )

        hotspot_iface = config.interface

        is_wifi_internet = "wl" in internet_iface or "wlan" in internet_iface
        is_same_interface = internet_iface == hotspot_iface

        if is_wifi_internet and is_same_interface:
            phy = self._get_phy_number(internet_iface)
            concurrent_ok = False
            if phy is not None:
                combos = self._detector.get_phy_combinations(phy)
                concurrent_ok = self._phy_supports_concurrent(combos)

            if concurrent_ok:
                logger.info("Radio supports AP+managed concurrently, trying it...")
                success, message = self._start_with_virtual_interface(
                    config, internet_iface
                )
                if success:
                    return success, message
                logger.warning(
                    f"Concurrent attempt failed even though hardware reports "
                    f"support ({message}); falling back to single-interface AP mode."
                )
            else:
                logger.warning(
                    f"{internet_iface} (phy{phy}) cannot run AP and managed mode "
                    "at the same time. Falling back to single-interface hotspot "
                    "- this WILL disconnect your current WiFi. Use a second "
                    "(e.g. USB) WiFi adapter for true concurrent mode."
                )

            return self._start_with_hostapd(
                config,
                hotspot_iface,
                internet_iface,
                warn_disconnect=True,
            )

        logger.info("Starting hotspot with hostapd...")
        return self._start_with_hostapd(config, hotspot_iface, internet_iface)

    def _phy_supports_concurrent(self, combos: List[Dict]) -> bool:
        for combo in combos:
            groups = combo["groups"]
            total = combo["total"]
            total_ok = total is None or total >= 2

            managed_ok = any("managed" in roles and c >= 1 for roles, c in groups)
            ap_ok = any("AP" in roles and c >= 1 for roles, c in groups)
            combined_ok = any(
                "managed" in roles and "AP" in roles and c >= 2 for roles, c in groups
            )

            if total_ok and (combined_ok or (managed_ok and ap_ok)):
                return True
        return False

    def _start_with_virtual_interface(
        self, config: HotspotConfig, wifi_iface: str
    ) -> Tuple[bool, str]:
        phy = self._get_phy_number(wifi_iface)
        if phy is None:
            return False, "Could not determine PHY number"

        # A single radio operating AP + managed concurrently must keep both
        # interfaces on the same channel. We operate on a COPY of the config
        # so that if this attempt fails, the caller's original config (with
        # whatever channel/band the user actually asked for) is untouched
        # for a single-interface fallback, which has no such constraint.
        ap_config = replace(config)
        current = self._detector.get_current_channel(wifi_iface)
        if current:
            actual_channel, actual_band = current
            if actual_channel != ap_config.channel or actual_band != ap_config.band:
                logger.info(
                    f"Overriding requested channel {ap_config.channel}/{ap_config.band} "
                    f"with {actual_channel}/{actual_band} to match the active "
                    f"WiFi connection on {wifi_iface} (required for concurrent mode)"
                )
            ap_config.channel = actual_channel
            ap_config.band = actual_band
        else:
            logger.warning(
                f"Could not detect current channel for {wifi_iface}; proceeding "
                f"with requested channel {ap_config.channel} which may not match "
                "the live WiFi link and could cause a disconnect."
            )

        base_name = wifi_iface.rstrip("0123456789")
        vif = self._create_virtual_interface(phy, base_name)

        if not vif:
            return False, "Failed to create virtual interface"

        self._virtual_interface = vif
        self._wifi_connection_id = self._get_connection_id(wifi_iface)
        self._wifi_interface_for_recovery = wifi_iface

        self._setup_ip_forwarding()
        self._setup_interface_ip(vif, ap_config.gateway)

        hostapd_conf = self._write_hostapd_config(ap_config, vif)
        dnsmasq_conf = self._write_dnsmasq_config(ap_config, vif)

        if not self._start_hostapd(hostapd_conf):
            self._cleanup_virtual_interface()
            self._cleanup_ip_forwarding()
            detail = f": {self._last_hostapd_error}" if self._last_hostapd_error else ""
            return False, f"Failed to start hostapd{detail}"

        if not self._start_dnsmasq(dnsmasq_conf):
            self._stop_hostapd()
            self._cleanup_virtual_interface()
            self._cleanup_ip_forwarding()
            return False, "Failed to start dnsmasq"

        # Give the radio a moment to settle, then confirm the original WiFi
        # link is genuinely still up. Some cards report AP+managed support
        # in their combinations but still drop the STA link in practice.
        time.sleep(STABILITY_CHECK_DELAY)
        if self.get_connected_wifi_interface() != wifi_iface:
            logger.error(
                f"{wifi_iface} lost its WiFi connection right after the AP came "
                "up - this radio can't sustain true concurrent mode. Rolling back."
            )
            self._stop_dnsmasq()
            self._stop_hostapd()
            self._cleanup_virtual_interface()
            self._cleanup_ip_forwarding()
            return (
                False,
                "Your WiFi card dropped its connection when the hotspot started. "
                "This radio doesn't reliably support running WiFi and a hotspot "
                "together. Consider a USB WiFi adapter for the hotspot side.",
            )

        self.hotspot_active = True
        self.current_config = ap_config
        self._method_used = "virtual_interface"
        self._start_monitoring()

        ssid = self.get_connected_wifi_ssid() or "Ethernet"
        self._notify_callbacks(
            "hotspot_started", {"ssid": ap_config.ssid, "method": "virtual_interface"}
        )
        return (
            True,
            f"Concurrent hotspot ACTIVE! Internet: {ssid}, Hotspot: {ap_config.ssid} "
            f"(channel {ap_config.channel})",
        )

    def _start_with_hostapd(
        self,
        config: HotspotConfig,
        hotspot_iface: str,
        internet_iface: str,
        warn_disconnect: bool = False,
    ) -> Tuple[bool, str]:
        self._setup_ip_forwarding()
        self._setup_interface_ip(hotspot_iface, config.gateway)

        hostapd_conf = self._write_hostapd_config(config, hotspot_iface)
        dnsmasq_conf = self._write_dnsmasq_config(config, hotspot_iface)

        if not self._start_hostapd(hostapd_conf):
            self._cleanup_ip_forwarding()
            detail = f": {self._last_hostapd_error}" if self._last_hostapd_error else ""
            return False, f"Failed to start hostapd{detail}"

        if not self._start_dnsmasq(dnsmasq_conf):
            self._stop_hostapd()
            self._cleanup_ip_forwarding()
            return False, "Failed to start dnsmasq"

        self.hotspot_active = True
        self.current_config = config
        self._method_used = "hostapd"
        self._start_monitoring()

        ssid = self.get_connected_wifi_ssid() or f"Ethernet ({internet_iface})"
        self._notify_callbacks(
            "hotspot_started", {"ssid": config.ssid, "method": "hostapd"}
        )
        message = f"Hotspot ACTIVE! Internet: {ssid}, Hotspot: {config.ssid}"
        if warn_disconnect:
            message += " (WiFi client connection was disconnected to free the radio)"
        return True, message

    def _cleanup_virtual_interface(self):
        if self._virtual_interface:
            self._delete_virtual_interface(self._virtual_interface)
            self._virtual_interface = None

    def stop_hotspot(self) -> Tuple[bool, str]:
        if not self.hotspot_active:
            return True, "No hotspot active"

        self._stop_monitoring()

        self._stop_dnsmasq()
        self._stop_hostapd()
        self._cleanup_ip_forwarding()
        self._cleanup_virtual_interface()

        if self.current_config:
            try:
                subprocess.run(
                    [
                        "nmcli",
                        "connection",
                        "delete",
                        f"Hotspot-{self.current_config.ssid}",
                    ],
                    capture_output=True,
                )
            except Exception:
                pass

        self.hotspot_active = False
        self.current_config = None
        self._method_used = None
        self._wifi_connection_id = None
        self._wifi_interface_for_recovery = None
        self._notify_callbacks("hotspot_stopped", {})

        return True, "Hotspot stopped successfully"

    def _start_monitoring(self):
        self._stop_monitor.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_monitoring(self):
        self._stop_monitor.set()
        if self._monitor_thread and threading.current_thread() is not self._monitor_thread:
            self._monitor_thread.join(timeout=2)

    def _monitor_loop(self):
        while not self._stop_monitor.is_set():
            if not self.hotspot_active:
                self._stop_monitor.wait(5)
                continue

            if self._hostapd_process and self._hostapd_process.poll() is not None:
                logger.warning("hostapd process died!")
                self._teardown_after_failure()
                self._notify_callbacks("hotspot_lost", {"reason": "hostapd_died"})
                break

            if (
                self._method_used == "virtual_interface"
                and self._wifi_interface_for_recovery
                and not self._recovering
            ):
                current_iface = self.get_connected_wifi_interface()
                if current_iface != self._wifi_interface_for_recovery:
                    self._handle_wifi_dropped()
                    if not self.hotspot_active:
                        break

            self._stop_monitor.wait(5)

    def _teardown_after_failure(self):
        self._stop_dnsmasq()
        self._stop_hostapd()
        self._cleanup_ip_forwarding()
        self._cleanup_virtual_interface()
        self.hotspot_active = False
        self.current_config = None
        self._method_used = None

    def _handle_wifi_dropped(self):
        logger.warning(
            f"{self._wifi_interface_for_recovery} lost its WiFi connection while "
            "the hotspot was active. Attempting auto-recovery..."
        )
        self._notify_callbacks("wifi_lost", {})
        self._recovering = True

        config = self.current_config
        wifi_iface = self._wifi_interface_for_recovery
        conn_id = self._wifi_connection_id

        self._stop_dnsmasq()
        self._stop_hostapd()
        self._cleanup_virtual_interface()

        recovered = False
        if conn_id:
            for attempt in range(1, RECOVERY_ATTEMPTS + 1):
                logger.info(f"Reconnect attempt {attempt}/{RECOVERY_ATTEMPTS}...")
                self._run_cmd(["nmcli", "connection", "up", conn_id])
                time.sleep(RECOVERY_RETRY_DELAY)
                if self.get_connected_wifi_interface() == wifi_iface:
                    recovered = True
                    break

        if recovered and config:
            logger.info("WiFi reconnected, restarting concurrent hotspot...")
            success, message = self._start_with_virtual_interface(config, wifi_iface)
            self._recovering = False
            if success:
                self._notify_callbacks("hotspot_recovered", {})
                return
            logger.error(f"Failed to restore hotspot after recovery: {message}")

        self._recovering = False
        logger.error("Auto-recovery failed; stopping hotspot.")
        self._cleanup_ip_forwarding()
        self.hotspot_active = False
        self.current_config = None
        self._method_used = None
        self._notify_callbacks("hotspot_lost", {"reason": "wifi_recovery_failed"})

    def get_connected_clients(self) -> List[Dict]:
        clients = []
        if not self.hotspot_active or not self.current_config:
            return clients

        try:
            result = self._run_cmd(["arp", "-a"])
            gateway = self.current_config.gateway
            gateway_prefix = ".".join(gateway.split(".")[:3])

            for line in result.stdout.splitlines():
                if gateway not in line and "(" in line:
                    match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)", line)
                    if match:
                        ip = match.group(1)
                        if ip.startswith(gateway_prefix):
                            hostname = line.split()[0] if line.split() else "unknown"
                            clients.append({"ip": ip, "hostname": hostname})
        except Exception:
            pass

        return clients

    def get_status(self) -> Dict:
        wifi_ssid = self.get_connected_wifi_ssid()
        wifi_interface = self.get_connected_wifi_interface()
        ethernet_interface = None

        try:
            result = self._run_cmd(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"]
            )
            for line in result.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 3:
                    device, dev_type, state = parts[0], parts[1], parts[2]
                    if dev_type == "ethernet" and state == "connected":
                        ethernet_interface = device
                        break
        except Exception:
            pass

        return {
            "wifi_connected": wifi_ssid is not None,
            "wifi_ssid": wifi_ssid,
            "wifi_interface": wifi_interface,
            "ethernet_connected": ethernet_interface is not None,
            "ethernet_interface": ethernet_interface,
            "internet_interface": wifi_interface or ethernet_interface,
            "hotspot_active": self.hotspot_active,
            "hotspot_ssid": self.current_config.ssid if self.current_config else None,
            "hotspot_method": self._method_used,
            "connected_clients": len(self.get_connected_clients()),
        }

    def save_config(self, config: HotspotConfig, config_path: str = None):
        path = Path(
            config_path or os.path.join(get_config_dir(), "config.json")
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
                    "internet_interface": config.internet_interface,
                },
                f,
            )

        logger.info(f"Config saved to {path}")

    def load_config(self, config_path: str = None) -> Optional[HotspotConfig]:
        path = Path(
            config_path or os.path.join(get_config_dir(), "config.json")
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
                internet_interface=data.get("internet_interface"),
            )
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return None
