#!/usr/bin/env python3
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")

from gi.repository import Gtk, GLib, Gdk, Pango
from gi.repository import AppIndicator3
from typing import Optional, Dict
import threading
import logging
import os
from pathlib import Path

from .hardware_detector import HardwareDetector, WifiInterface
from .hotspot_manager import ConcurrentHotspotManager, HotspotConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HotspotManagerApp:
    def __init__(self):
        self.app = (
            Gtk.Application(
                application_id="com.hotspot.manager",
                flags=Gio.ApplicationFlags.FLAGS_NONE,
            )
            if self._check_gio()
            else None
        )

        self.detector = HardwareDetector()
        self.manager = ConcurrentHotspotManager()
        self.manager.register_callback(self._on_hotspot_event)

        self.window: Optional[Gtk.Window] = None
        self.indicator: Optional[AppIndicator3.Indicator] = None
        self.interfaces: list = []
        self.status_timeout_id = None
        self.clients_timeout_id = None

        self._init_indicator()

    def _check_gio(self):
        try:
            from gi.repository import Gio

            return True
        except ImportError:
            return False

    def _init_indicator(self):
        try:
            self.indicator = AppIndicator3.Indicator.new(
                "hotspot-manager",
                "network-wireless-symbolic",
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self._update_indicator_menu()
        except Exception as e:
            logger.warning(f"Could not create system tray indicator: {e}")

    def _update_indicator_menu(self):
        if not self.indicator:
            return

        menu = Gtk.Menu()

        self.status_menu_item = Gtk.MenuItem(label="Status: Checking...")
        self.status_menu_item.set_sensitive(False)
        menu.append(self.status_menu_item)

        menu.append(Gtk.SeparatorMenuItem())

        toggle_item = Gtk.MenuItem(label="Toggle Hotspot")
        toggle_item.connect("activate", self._on_toggle_from_tray)
        menu.append(toggle_item)

        show_item = Gtk.MenuItem(label="Show Window")
        show_item.connect("activate", lambda w: self._show_window())
        menu.append(show_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._on_quit)
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

    def _on_toggle_from_tray(self, widget):
        if self.manager.hotspot_active:
            threading.Thread(target=self._stop_hotspot_async, daemon=True).start()
        else:
            config = self.manager.load_config()
            if config:
                threading.Thread(
                    target=self._start_hotspot_async, args=(config,), daemon=True
                ).start()

    def _start_hotspot_async(self, config: HotspotConfig):
        success, message = self.manager.start_hotspot(config)
        GLib.idle_add(self._update_status_display)
        if success:
            GLib.idle_add(lambda: self._show_info(message))
        else:
            GLib.idle_add(lambda: self._show_error(message))

    def _stop_hotspot_async(self):
        self.manager.stop_hotspot()
        GLib.idle_add(self._update_status_display)

    def _on_hotspot_event(self, event: str, data: dict):
        GLib.idle_add(self._update_status_display)

        if event == "hotspot_started":
            self._show_notification(
                "Hotspot Started", f"Hotspot '{data.get('ssid')}' is now active"
            )
        elif event == "hotspot_stopped":
            self._show_notification("Hotspot Stopped", "The hotspot has been stopped")
        elif event == "wifi_lost":
            self._show_notification(
                "WiFi Lost", "WiFi connection was lost, hotspot stopped"
            )

    def _show_notification(self, title: str, message: str):
        try:
            import notify2

            notify2.init("Hotspot Manager")
            notification = notify2.Notification(title, message, "network-wireless")
            notification.show()
        except ImportError:
            pass

    def build_ui(self):
        self.window = Gtk.Window()
        self.window.set_title("Concurrent Hotspot Manager")
        self.window.set_default_size(600, 500)
        self.window.set_border_width(10)
        self.window.connect("delete-event", self._on_window_close)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.window.add(main_box)

        header = self._create_header()
        main_box.pack_start(header, False, False, 0)

        self._create_status_section(main_box)
        self._create_config_section(main_box)
        self._create_clients_section(main_box)
        self._create_action_buttons(main_box)

        self._refresh_interfaces()

        self.window.show_all()

        self.status_timeout_id = GLib.timeout_add(2000, self._update_status_display)
        self.clients_timeout_id = GLib.timeout_add(5000, self._update_clients_list)

        config = self.manager.load_config()
        if config:
            self.ssid_entry.set_text(config.ssid)
            self.password_entry.set_text(config.password)
            self.channel_spin.set_value(config.channel)

    def _create_header(self) -> Gtk.Widget:
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header_box.set_margin_bottom(10)

        icon = Gtk.Image.new_from_icon_name(
            "network-wireless-hotspot", Gtk.IconSize.DIALOG
        )
        header_box.pack_start(icon, False, False, 0)

        title_label = Gtk.Label()
        title_label.set_markup(
            "<span size='large' weight='bold'>Concurrent Hotspot Manager</span>"
        )
        header_box.pack_start(title_label, False, False, 0)

        subtitle = Gtk.Label(label="Share WiFi connection while connected")
        subtitle.get_style_context().add_class("dim-label")
        header_box.pack_start(subtitle, False, False, 0)

        return header_box

    def _create_status_section(self, parent: Gtk.Box):
        frame = Gtk.Frame(label="Current Status")
        frame.set_margin_top(10)
        parent.pack_start(frame, False, False, 0)

        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_box.set_margin_top(10)
        status_box.set_margin_bottom(10)
        status_box.set_margin_start(10)
        status_box.set_margin_end(10)
        frame.add(status_box)

        wifi_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.wifi_icon = Gtk.Image.new_from_icon_name(
            "network-wireless", Gtk.IconSize.MENU
        )
        wifi_row.pack_start(self.wifi_icon, False, False, 0)
        self.wifi_status_label = Gtk.Label(label="WiFi: Checking...")
        wifi_row.pack_start(self.wifi_status_label, False, False, 0)
        status_box.pack_start(wifi_row, False, False, 0)

        ethernet_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.ethernet_icon = Gtk.Image.new_from_icon_name(
            "network-wired", Gtk.IconSize.MENU
        )
        ethernet_row.pack_start(self.ethernet_icon, False, False, 0)
        self.ethernet_status_label = Gtk.Label(label="Ethernet: Checking...")
        ethernet_row.pack_start(self.ethernet_status_label, False, False, 0)
        status_box.pack_start(ethernet_row, False, False, 0)

        hotspot_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.hotspot_icon = Gtk.Image.new_from_icon_name(
            "network-wireless-hotspot", Gtk.IconSize.MENU
        )
        hotspot_row.pack_start(self.hotspot_icon, False, False, 0)
        self.hotspot_status_label = Gtk.Label(label="Hotspot: Inactive")
        hotspot_row.pack_start(self.hotspot_status_label, False, False, 0)
        status_box.pack_start(hotspot_row, False, False, 0)

        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.mode_icon = Gtk.Image.new_from_icon_name("emblem-ok", Gtk.IconSize.MENU)
        mode_row.pack_start(self.mode_icon, False, False, 0)
        self.mode_status_label = Gtk.Label(label="Concurrent Mode: Waiting...")
        mode_row.pack_start(self.mode_status_label, False, False, 0)
        status_box.pack_start(mode_row, False, False, 0)

    def _create_config_section(self, parent: Gtk.Box):
        frame = Gtk.Frame(label="Hotspot Configuration")
        frame.set_margin_top(10)
        parent.pack_start(frame, False, False, 0)

        config_grid = Gtk.Grid()
        config_grid.set_margin_top(10)
        config_grid.set_margin_bottom(10)
        config_grid.set_margin_start(10)
        config_grid.set_margin_end(10)
        config_grid.set_column_spacing(20)
        config_grid.set_row_spacing(10)
        frame.add(config_grid)

        row = 0

        iface_label = Gtk.Label(label="Interface:")
        iface_label.set_halign(Gtk.Align.START)
        config_grid.attach(iface_label, 0, row, 1, 1)

        self.interface_combo = Gtk.ComboBoxText()
        config_grid.attach(self.interface_combo, 1, row, 2, 1)

        row += 1

        ssid_label = Gtk.Label(label="Hotspot Name (SSID):")
        ssid_label.set_halign(Gtk.Align.START)
        config_grid.attach(ssid_label, 0, row, 1, 1)

        self.ssid_entry = Gtk.Entry()
        self.ssid_entry.set_placeholder_text("Enter hotspot name")
        config_grid.attach(self.ssid_entry, 1, row, 2, 1)

        row += 1

        pass_label = Gtk.Label(label="Password:")
        pass_label.set_halign(Gtk.Align.START)
        config_grid.attach(pass_label, 0, row, 1, 1)

        self.password_entry = Gtk.Entry()
        self.password_entry.set_placeholder_text("Enter password (min 8 chars)")
        self.password_entry.set_visibility(False)
        config_grid.attach(self.password_entry, 1, row, 1, 1)

        self.show_pass_check = Gtk.CheckButton(label="Show")
        self.show_pass_check.connect("toggled", self._on_show_password_toggled)
        config_grid.attach(self.show_pass_check, 2, row, 1, 1)

        row += 1

        channel_label = Gtk.Label(label="Channel:")
        channel_label.set_halign(Gtk.Align.START)
        config_grid.attach(channel_label, 0, row, 1, 1)

        self.channel_spin = Gtk.SpinButton.new_with_range(1, 14, 1)
        self.channel_spin.set_value(6)
        config_grid.attach(self.channel_spin, 1, row, 1, 1)

        band_label = Gtk.Label(label="Band:")
        band_label.set_halign(Gtk.Align.START)
        config_grid.attach(band_label, 0, row + 1, 1, 1)

        self.band_combo = Gtk.ComboBoxText()
        self.band_combo.append("bg", "2.4 GHz (bg)")
        self.band_combo.append("a", "5 GHz (a)")
        self.band_combo.set_active_id("bg")
        config_grid.attach(self.band_combo, 1, row + 1, 1, 1)

    def _create_clients_section(self, parent: Gtk.Box):
        frame = Gtk.Frame(label="Connected Devices")
        frame.set_margin_top(10)
        parent.pack_start(frame, True, True, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(100)
        frame.add(scrolled)

        self.clients_list = Gtk.ListBox()
        scrolled.add(self.clients_list)

        placeholder = Gtk.Label(label="No devices connected")
        placeholder.get_style_context().add_class("dim-label")
        placeholder.set_margin_top(20)
        placeholder.set_margin_bottom(20)
        self.clients_list.set_placeholder(placeholder)

    def _create_action_buttons(self, parent: Gtk.Box):
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_margin_top(10)
        button_box.set_halign(Gtk.Align.CENTER)
        parent.pack_start(button_box, False, False, 0)

        self.start_button = Gtk.Button(label="Start Hotspot")
        self.start_button.get_style_context().add_class("suggested-action")
        self.start_button.connect("clicked", self._on_start_clicked)
        button_box.pack_start(self.start_button, False, False, 0)

        self.stop_button = Gtk.Button(label="Stop Hotspot")
        self.stop_button.get_style_context().add_class("destructive-action")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self._on_stop_clicked)
        button_box.pack_start(self.stop_button, False, False, 0)

        save_button = Gtk.Button(label="Save Config")
        save_button.connect("clicked", self._on_save_config)
        button_box.pack_start(save_button, False, False, 0)

    def _refresh_interfaces(self):
        self.interfaces = self.detector.get_wifi_interfaces()

        self.interface_combo.remove_all()

        for iface in self.interfaces:
            label = iface.name
            if iface.supports_concurrent:
                label += " (Concurrent)"
            elif iface.supports_ap:
                label += " (AP)"
            else:
                label += " (Limited)"

            self.interface_combo.append(iface.name, label)

            if iface.connected:
                self.interface_combo.set_active_id(iface.name)

        if self.interface_combo.get_active_id() is None and self.interfaces:
            self.interface_combo.set_active(0)

    def _on_show_password_toggled(self, widget):
        self.password_entry.set_visibility(widget.get_active())

    def _on_start_clicked(self, widget):
        ssid = self.ssid_entry.get_text().strip()
        password = self.password_entry.get_text()
        interface = self.interface_combo.get_active_id()
        channel = int(self.channel_spin.get_value())
        band = self.band_combo.get_active_id()

        if not ssid:
            self._show_error("Please enter a hotspot name")
            return

        if len(password) < 8:
            self._show_error("Password must be at least 8 characters")
            return

        if not interface:
            self._show_error("Please select an interface")
            return

        config = HotspotConfig(
            ssid=ssid,
            password=password,
            interface=interface,
            channel=channel,
            band=band,
        )

        self.start_button.set_sensitive(False)
        self.start_button.set_label("Starting...")

        threading.Thread(
            target=self._start_hotspot_async, args=(config,), daemon=True
        ).start()

    def _on_stop_clicked(self, widget):
        self.stop_button.set_sensitive(False)
        threading.Thread(target=self._stop_hotspot_async, daemon=True).start()

    def _on_save_config(self, widget):
        config = HotspotConfig(
            ssid=self.ssid_entry.get_text().strip(),
            password=self.password_entry.get_text(),
            interface=self.interface_combo.get_active_id() or "wlan0",
            channel=int(self.channel_spin.get_value()),
            band=self.band_combo.get_active_id() or "bg",
        )
        self.manager.save_config(config)
        self._show_info("Configuration saved!")

    def _update_status_display(self) -> bool:
        if not self.window:
            return False

        status = self.manager.get_status()

        has_internet = status.get("wifi_connected") or status.get("ethernet_connected")

        if status["wifi_connected"]:
            self.wifi_icon.set_from_icon_name(
                "network-wireless-connected", Gtk.IconSize.MENU
            )
            self.wifi_status_label.set_text(f"WiFi: {status['wifi_ssid']}")
        else:
            self.wifi_icon.set_from_icon_name(
                "network-wireless-disconnected", Gtk.IconSize.MENU
            )
            self.wifi_status_label.set_text("WiFi: Not connected")

        if status.get("ethernet_connected"):
            self.ethernet_icon.set_from_icon_name("network-wired", Gtk.IconSize.MENU)
            self.ethernet_status_label.set_text(
                f"Ethernet: {status['ethernet_interface']}"
            )
        else:
            self.ethernet_icon.set_from_icon_name(
                "network-wired-disconnected", Gtk.IconSize.MENU
            )
            self.ethernet_status_label.set_text("Ethernet: Not connected")

        if status["hotspot_active"]:
            self.hotspot_icon.set_from_icon_name(
                "network-wireless-hotspot", Gtk.IconSize.MENU
            )
            self.hotspot_status_label.set_text(f"Hotspot: {status['hotspot_ssid']}")

            self.mode_icon.set_from_icon_name("emblem-ok", Gtk.IconSize.MENU)
            source = status.get("internet_interface", "unknown")
            self.mode_status_label.set_text(f"Sharing internet from: {source}")

            self.start_button.set_sensitive(False)
            self.stop_button.set_sensitive(True)

            if self.indicator:
                self.indicator.set_icon("network-wireless-hotspot-symbolic")
                self.status_menu_item.set_label("Status: Active")
        else:
            self.hotspot_icon.set_from_icon_name(
                "network-wireless-hotspot", Gtk.IconSize.MENU
            )
            self.hotspot_status_label.set_text("Hotspot: Inactive")

            if has_internet:
                self.mode_icon.set_from_icon_name(
                    "dialog-information", Gtk.IconSize.MENU
                )
                source = status.get("internet_interface", "")
                if status.get("wifi_connected"):
                    self.mode_status_label.set_text(
                        f"Ready to share WiFi: {status['wifi_ssid']}"
                    )
                else:
                    self.mode_status_label.set_text(
                        f"Ready to share Ethernet: {source}"
                    )
            else:
                self.mode_icon.set_from_icon_name("dialog-warning", Gtk.IconSize.MENU)
                self.mode_status_label.set_text("Connect to WiFi or Ethernet first")

            self.start_button.set_sensitive(has_internet)
            self.start_button.set_label("Start Hotspot")
            self.stop_button.set_sensitive(False)

            if self.indicator:
                self.indicator.set_icon("network-wireless-symbolic")
                self.status_menu_item.set_label("Status: Inactive")

        return True

    def _update_clients_list(self) -> bool:
        if not self.window:
            return False

        for child in self.clients_list.get_children():
            self.clients_list.remove(child)

        clients = self.manager.get_connected_clients()

        for client in clients:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            icon = Gtk.Image.new_from_icon_name("computer", Gtk.IconSize.MENU)
            box.pack_start(icon, False, False, 0)

            info = Gtk.Label(label=f"{client['hostname']} - {client['ip']}")
            info.set_halign(Gtk.Align.START)
            box.pack_start(info, True, True, 0)

            row.add(box)
            self.clients_list.add(row)

        self.clients_list.show_all()

        return True

    def _show_error(self, message: str):
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error",
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _show_info(self, message: str):
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Info",
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _on_window_close(self, widget, event):
        self.window.hide()
        return True

    def _show_window(self):
        if self.window:
            self.window.show_all()
            self.window.present()

    def _on_quit(self, widget=None):
        if self.status_timeout_id:
            GLib.source_remove(self.status_timeout_id)
        if self.clients_timeout_id:
            GLib.source_remove(self.clients_timeout_id)

        if self.manager.hotspot_active:
            self.manager.stop_hotspot()

        if self.window:
            self.window.destroy()

        Gtk.main_quit()

    def run(self):
        self.build_ui()
        Gtk.main()
        return 0


def main():
    app = HotspotManagerApp()
    return app.run()


if __name__ == "__main__":
    main()
