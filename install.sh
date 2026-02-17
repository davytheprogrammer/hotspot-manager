#!/bin/bash
set -e

echo "========================================="
echo "  Concurrent Hotspot Manager Installer  "
echo "========================================="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo ./install.sh"
    exit 1
fi

echo "[1/5] Installing dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-gi \
    network-manager wireless-tools iw hostapd dnsmasq \
    gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 \
    libgtk-3-0 libnotify4 arp-scan iptables iproute2

echo ""
echo "[2/5] Installing Python packages..."
pip3 install --user PyGObject notify2 2>/dev/null || true

echo ""
echo "[3/5] Creating directories..."
mkdir -p /usr/share/hotspot-manager
mkdir -p /usr/share/applications
mkdir -p /etc/hotspot-manager
mkdir -p ~/.config/hotspot-manager

echo ""
echo "[4/5] Copying files..."
cp -r src/hotspot_manager /usr/share/hotspot-manager/
cp data/hotspot-manager.desktop /usr/share/applications/
chmod +x /usr/share/applications/hotspot-manager.desktop

cat > /usr/bin/hotspot-manager << 'EOF'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/usr/share/hotspot-manager')
from hotspot_manager.main import main
if __name__ == "__main__":
    sys.exit(main())
EOF
chmod +x /usr/bin/hotspot-manager

cat > /usr/bin/hotspot-cli << 'EOF'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/usr/share/hotspot-manager')
from hotspot_manager.cli import main
if __name__ == "__main__":
    sys.exit(main())
EOF
chmod +x /usr/bin/hotspot-cli

echo ""
echo "[5/5] Configuring NetworkManager..."
cat > /etc/NetworkManager/conf.d/hotspot.conf << 'EOF'
[connection]
wifi.backend=wpa_supplicant

[device]
wifi.scan-rand-mac-address=no
EOF

systemctl restart NetworkManager 2>/dev/null || true

echo ""
echo "========================================="
echo "  Installation Complete!                 "
echo "========================================="
echo ""
echo "GUI: hotspot-manager"
echo "CLI: hotspot-cli status"
echo "CLI: hotspot-cli start --ssid MyHotspot --password mypassword"
echo "CLI: hotspot-cli stop"
echo ""
echo "IMPORTANT NOTES:"
echo "1. Connect to WiFi first"
echo "2. The hotspot will share your WiFi connection"
echo "3. Some WiFi cards don't support concurrent mode"
echo "   - Check with: hotspot-cli interfaces"
echo ""
echo "To check your hardware support:"
echo "  iw phy | grep -A10 'Supported interface'"
echo ""