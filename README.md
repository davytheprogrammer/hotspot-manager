<p align="center">
  <img src="docs/icon.svg" alt="Hotspot Manager Logo" width="128" height="128">
  <h1 align="center">🔥 Hotspot Manager</h1>
  <p align="center">
    <strong>Concurrent WiFi + Hotspot for Linux</strong>
    <br>
    <em>Share your WiFi connection while staying connected</em>
  </p>
</p>

<p align="center">
  <a href="https://github.com/davytheprogrammer/hotspot-manager/releases">
    <img src="https://img.shields.io/github/v/release/davytheprogrammer/hotspot-manager?include_prereleases" alt="Release">
  </a>
  <a href="https://github.com/davytheprogrammer/hotspot-manager/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/davytheprogrammer/hotspot-manager" alt="License">
  </a>
  <a href="https://github.com/davytheprogrammer/hotspot-manager/issues">
    <img src="https://img.shields.io/github/issues/davytheprogrammer/hotspot-manager" alt="Issues">
  </a>
  <a href="https://github.com/davytheprogrammer/hotspot-manager/stargazers">
    <img src="https://img.shields.io/github/stars/davytheprogrammer/hotspot-manager?style=social" alt="Stars">
  </a>
</p>

<p align="center">
  <a href="#-installation">Installation</a> •
  <a href="#-usage">Usage</a> •
  <a href="#-screenshots">Screenshots</a> •
  <a href="#-compatibility">Compatibility</a> •
  <a href="#-contributing">Contributing</a>
</p>

---

## 🎯 What is this?

**Hotspot Manager** is a native Linux GTK3 application that solves a common problem: **how to share your WiFi connection with other devices while you're still using it.**

Normally, when you create a hotspot on Linux, your WiFi disconnects. This app enables **concurrent mode** - you stay connected to WiFi for internet access while simultaneously broadcasting a hotspot that other devices can connect to.

### Perfect for:
- 📱 Sharing hotel WiFi with your phone, tablet, and laptop
- 🎮 Creating a local network for multiplayer gaming
- 🏢 Sharing a single WiFi connection at conferences or meetings
- 🏠 Extending WiFi range to devices that have weak reception

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔀 **Concurrent Mode** | WiFi + Hotspot at the same time |
| 🖥️ **GTK3 GUI** | Clean, native Linux interface |
| 📍 **System Tray** | Quick toggle from notification area |
| 🔍 **Hardware Detection** | Auto-detects concurrent mode support |
| 📱 **Device List** | See who's connected to your hotspot |
| ⌨️ **CLI Interface** | Script and automate hotspot management |
| 🔄 **Auto-Recovery** | Restarts hotspot when WiFi reconnects |
| 💾 **Config Save** | Remember your hotspot settings |

---

## 📸 Screenshots

<p align="center">
  <img src="docs/screenshot-main.png" alt="Main Window" width="400">
  <img src="docs/screenshot-tray.png" alt="System Tray" width="200">
</p>

---

## 📦 Installation

### Option 1: Download DEB (Recommended)

Download the latest `.deb` from [Releases](https://github.com/davytheprogrammer/hotspot-manager/releases):

```bash
wget https://github.com/davytheprogrammer/hotspot-manager/releases/latest/download/hotspot-manager.deb
sudo dpkg -i hotspot-manager.deb
sudo apt install -f
```

### Option 2: From Source

```bash
git clone https://github.com/davytheprogrammer/hotspot-manager.git
cd hotspot-manager
sudo ./install.sh
```

### Dependencies

The packages are automatically installed with the `.deb`, but for source installation:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 \
    network-manager iw hostapd dnsmasq libnotify4 arp-scan
```

---

## 🚀 Usage

### GUI

1. **Connect to WiFi first** - Join a WiFi network normally
2. Open Hotspot Manager from your application menu
3. Enter hotspot name and password (min 8 characters)
4. Click **Start Hotspot**
5. Other devices can now find and connect to your hotspot

### CLI

```bash
# Check status
hotspot-cli status

# Check hardware support
hotspot-cli interfaces

# Start hotspot
hotspot-cli start --ssid MyHotspot --password mypassword123

# Stop hotspot
hotspot-cli stop

# Advanced options
hotspot-cli start --ssid MyHotspot --password secret \
    --channel 6 --band bg --interface wlan0
```

### System Tray

The app runs in the system tray. Right-click to:
- Toggle hotspot on/off
- Show the main window
- Quit the application

---

## ⚙️ Compatibility

### Supported OS
- Ubuntu 20.04+ / Pop!_OS
- Debian 11+
- Linux Mint 20+
- Any Debian-based distribution with NetworkManager

### Hardware Requirements

Not all WiFi cards support concurrent mode. Check yours:

```bash
hotspot-cli interfaces
```

Or manually:

```bash
iw phy | grep -A10 "Supported interface"
```

Look for both `* AP` and `* managed` in the output. Cards with `AP/VLAN` typically support concurrent mode best.

#### Known Compatible Cards
- Intel AX200, AX201, AX210, AX211
- Realtek RTL8812AU, RTL8814AU (USB)
- Atheros AR9271, AR9485
- MediaTek MT7612U (USB)

#### Problematic Cards
- Some Realtek RTL8188CE/RTL8192CE (limited concurrent support)
- Older Broadcom cards (may need proprietary drivers)

---

## 🔧 How It Works

```
┌─────────────────────────────────────────────────────────┐
│                    YOUR LAPTOP                          │
│                                                         │
│  ┌─────────────┐         ┌─────────────────────────┐   │
│  │   WiFi      │         │      Hotspot            │   │
│  │  Client     │         │      (AP Mode)          │   │
│  │ (Managed)   │         │                         │   │
│  └──────┬──────┘         └───────────┬─────────────┘   │
│         │                            │                  │
│         │  ┌──────────────────────┐  │                  │
│         └──┤  NetworkManager      ├──┘                  │
│            │  (Concurrent Mode)   │                     │
│            └──────────┬───────────┘                     │
│                       │                                 │
│            ┌──────────┴───────────┐                     │
│            │   NAT / IP Forward   │                     │
│            └──────────┬───────────┘                     │
└───────────────────────┼─────────────────────────────────┘
                        │
          ┌─────────────┴─────────────┐
          │                           │
    ┌─────▼─────┐               ┌─────▼─────┐
    │  Router   │               │  Devices  │
    │ (Internet)│               │  (Phone,  │
    │           │               │  Tablet)  │
    └───────────┘               └───────────┘
```

1. Connects to WiFi as a client (managed mode)
2. Creates a hotspot access point (AP mode) on the same card
3. NetworkManager handles the concurrent mode
4. NAT/IP forwarding shares internet with hotspot clients

---

## 🐛 Troubleshooting

### "WiFi connection was lost"

Your WiFi card may not support concurrent mode fully. Try:
- Different channel (1, 6, or 11 for 2.4GHz)
- Use a USB WiFi adapter with AP support
- Check `iw phy` output

### "No WiFi connection active"

You must connect to WiFi before starting the hotspot. This app shares an existing connection.

### Hotspot won't start

```bash
# Check NetworkManager is running
systemctl status NetworkManager

# Check your WiFi hardware
iw phy

# Try a different interface
hotspot-cli interfaces
```

### Can't connect devices to hotspot

- Check password is correct
- Try a different channel (avoid interference)
- Ensure DHCP is working (restart dnsmasq)

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Development Setup

```bash
git clone https://github.com/davytheprogrammer/hotspot-manager.git
cd hotspot-manager
python3 -m venv venv
source venv/bin/activate
pip install -e .
python3 run.py
```

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- NetworkManager team for concurrent mode support
- GTK3/GObject developers
- The Linux wireless community

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/davytheprogrammer">Davis Ogega</a>
</p>

<p align="center">
  <a href="https://github.com/davytheprogrammer/hotspot-manager/issues">Report Bug</a> •
  <a href="https://github.com/davytheprogrammer/hotspot-manager/issues">Request Feature</a>
</p>