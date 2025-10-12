#!/usr/bin/env python3

from tabulate import tabulate

from syncweb.log_utils import log

# TODO: add args.st.device_status(folder_id)


def cmd_list_devices(args):
    devices = args.st.devices()

    if not devices:
        log.info("No devices configured")
        return

    # Prepare table data
    table_data = []

    for device in devices:
        device_id = device.get("deviceID", "unknown")
        # Shorten device ID for display
        device_id_short = device_id[:7] if len(device_id) > 7 else device_id

        name = device.get("name", "unnamed")
        addresses = device.get("addresses", [])
        address_str = ", ".join(addresses[:2])  # Show first 2 addresses
        if len(addresses) > 2:
            address_str += f", ... (+{len(addresses) - 2})"

        compression = device.get("compression", "metadata")
        introducer = "Yes" if device.get("introducer", False) else "No"
        paused = device.get("paused", False)
        untrusted = device.get("untrusted", False)
        num_connections = device.get("numConnections", 0)

        # Bandwidth limits
        max_send = device.get("maxSendKbps", 0)
        max_recv = device.get("maxRecvKbps", 0)

        if max_send > 0 or max_recv > 0:
            send_str = f"{max_send}" if max_send > 0 else "∞"
            recv_str = f"{max_recv}" if max_recv > 0 else "∞"
            bandwidth_str = f"↑{send_str}/↓{recv_str} Kbps"
        else:
            bandwidth_str = "Unlimited"

        # Status
        if paused:
            status = "⏸ Paused"
        elif untrusted:
            status = "⚠ Untrusted"
        elif num_connections > 0:
            status = f"✓ Connected ({num_connections})"
        else:
            status = "○ Disconnected"

        if args.verbose:
            # Verbose mode: include more details
            ignored_folders = device.get("ignoredFolders", [])
            ignored_count = len(ignored_folders)
            auto_accept = "Yes" if device.get("autoAcceptFolders", False) else "No"

            table_data.append(
                [
                    device_id_short,
                    name,
                    address_str,
                    compression,
                    introducer,
                    bandwidth_str,
                    auto_accept,
                    ignored_count,
                    status,
                ]
            )
        else:
            # Standard mode
            table_data.append([device_id_short, name, address_str, compression, introducer, status])

    # Print table
    if args.verbose:
        headers = [
            "Device ID",
            "Name",
            "Addresses",
            "Compression",
            "Introducer",
            "Bandwidth",
            "Auto-Accept",
            "Ignored",
            "Status",
        ]
    else:
        headers = ["Device ID", "Name", "Addresses", "Compression", "Introducer", "Status"]

    print(tabulate(table_data, headers=headers, tablefmt="simple"))
    print(f"\nTotal devices: {len(devices)}")

    # Show full device IDs if requested
    if args.full_id:
        print("\nFull Device IDs:")
        for device in devices:
            device_id = device.get("deviceID", "unknown")
            name = device.get("name", "unnamed")
            print(f"  {name}: {device_id}")
