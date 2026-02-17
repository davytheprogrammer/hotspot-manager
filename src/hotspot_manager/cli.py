#!/usr/bin/env python3
import argparse
import sys
from hotspot_manager import ConcurrentHotspotManager, HotspotConfig, HardwareDetector


def cmd_status(manager, detector):
    status = manager.get_status()
    print("\n=== Hotspot Manager Status ===")

    if status["wifi_connected"]:
        print(f"WiFi: Connected to {status['wifi_ssid']} ({status['wifi_interface']})")
    else:
        print("WiFi: Not connected")

    if status.get("ethernet_connected"):
        print(f"Ethernet: Connected ({status['ethernet_interface']})")
    else:
        print("Ethernet: Not connected")

    if status.get("internet_interface"):
        print(f"Internet Source: {status['internet_interface']}")

    print()
    if status["hotspot_active"]:
        print(f"Hotspot: ACTIVE - {status['hotspot_ssid']}")
        print(f"Method: {status.get('hotspot_method', 'unknown')}")
        print(f"Connected Clients: {status['connected_clients']}")
    else:
        print("Hotspot: Inactive")
    print()


def cmd_start(manager, args):
    if not args.ssid:
        print("Error: SSID required. Use --ssid")
        return 1

    if not args.password or len(args.password) < 8:
        print("Error: Password must be at least 8 characters")
        return 1

    detector = HardwareDetector()
    interfaces = detector.get_wifi_interfaces()

    interface = args.interface
    if not interface:
        connected = [i for i in interfaces if i.connected]
        if connected:
            interface = connected[0].name
        elif interfaces:
            interface = interfaces[0].name
        else:
            print("Error: No WiFi interfaces found")
            return 1

    config = HotspotConfig(
        ssid=args.ssid,
        password=args.password,
        interface=interface,
        channel=args.channel,
        band=args.band,
        internet_interface=args.internet,
    )

    print(f"Starting hotspot '{config.ssid}' on {config.interface}...")
    success, message = manager.start_hotspot(config)
    print(message)
    return 0 if success else 1


def cmd_stop(manager):
    success, message = manager.stop_hotspot()
    print(message)
    return 0 if success else 1


def cmd_interfaces(detector):
    print("\n=== WiFi Interfaces ===")
    interfaces = detector.get_wifi_interfaces()

    if not interfaces:
        print("No WiFi interfaces found")
        return

    for iface in interfaces:
        concurrent = "✓" if iface.supports_concurrent else "✗"
        ap = "✓" if iface.supports_ap else "✗"
        print(f"\n{iface.name}:")
        print(f"  Driver: {iface.driver}")
        print(f"  AP Mode Support: {ap}")
        print(f"  Concurrent Support: {concurrent}")
        print(f"  Current Mode: {iface.current_mode}")
        print(f"  Connected: {'Yes' if iface.connected else 'No'}")

    print("\n=== Ethernet Interfaces ===")
    import subprocess

    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "ethernet":
                print(f"\n{parts[0]}: {parts[2]}")
    except Exception:
        pass
    print()


def main():
    parser = argparse.ArgumentParser(description="Concurrent Hotspot Manager CLI")
    parser.add_argument(
        "command", choices=["status", "start", "stop", "interfaces", "check"]
    )

    parser.add_argument("--ssid", "-s", help="Hotspot SSID")
    parser.add_argument("--password", "-p", help="Hotspot password (min 8 chars)")
    parser.add_argument("--interface", "-i", help="WiFi interface to use")
    parser.add_argument(
        "--internet",
        "-I",
        help="Internet source interface (auto-detected if not specified)",
    )
    parser.add_argument(
        "--channel", "-c", type=int, default=6, help="WiFi channel (default: 6)"
    )
    parser.add_argument(
        "--band", "-b", default="bg", choices=["bg", "a"], help="WiFi band"
    )

    args = parser.parse_args()

    manager = ConcurrentHotspotManager()
    detector = HardwareDetector()

    if args.command == "status":
        cmd_status(manager, detector)
    elif args.command == "start":
        sys.exit(cmd_start(manager, args))
    elif args.command == "stop":
        sys.exit(cmd_stop(manager))
    elif args.command == "interfaces":
        cmd_interfaces(detector)
    elif args.command == "check":
        cmd_status(manager, detector)
        cmd_interfaces(detector)


if __name__ == "__main__":
    main()
