#!/usr/bin/env python3
import time
from datetime import datetime

from tabulate import tabulate

from syncweb import str_utils
from syncweb.log_utils import log

# TODO: show remoteneed (need for local device); estimated time to completion


def _parse_at(at_str):
    try:
        return datetime.fromisoformat(at_str)
    except Exception:
        return datetime.now()


def _calc_rate(prev, curr, dt):
    """Return (UL_rate, DL_rate) in KB/s"""
    if not prev or dt <= 0:
        return 0.0, 0.0
    up = (curr["outBytesTotal"] - prev["outBytesTotal"]) / dt / 1024
    down = (curr["inBytesTotal"] - prev["inBytesTotal"]) / dt / 1024
    return up, down


def cmd_list_devices(args):
    devices = args.st.devices()
    device_stats = args.st.device_stats()

    if not devices:
        log.info("No devices configured")
        return

    conn_before = args.st._get("system/connections")

    # delay for rate measurement
    if args.xfer:
        time.sleep(args.xfer)
        conn_after = args.st._get("system/connections")
    else:
        conn_after = conn_before

    total_before = conn_before.get("total", {})
    total_after = conn_after.get("total", {})
    total_at_before = _parse_at(total_before.get("at", ""))
    total_at_after = _parse_at(total_after.get("at", ""))
    dt = (total_at_after - total_at_before).total_seconds() or 1.0

    if args.xfer:
        total_up, total_down = _calc_rate(total_before, total_after, dt)
    else:
        total_up = total_down = None

    table_data = []
    connections_before = conn_before.get("connections", {})
    connections_after = conn_after.get("connections", {})

    for device in devices:
        device_id = device.get("deviceID")
        is_local = device_id == args.st.device_id
        if is_local:
            continue

        name = device.get("name", "<no name>")
        paused = device.get("paused", False)

        device_stat = device_stats[device_id]
        last_seen = device_stat["lastSeen"]
        last_duration = device_stat["lastConnectionDurationS"]

        # Bandwidth limits
        max_send = device.get("maxSendKbps", 0)
        max_recv = device.get("maxRecvKbps", 0)
        if max_send > 0 or max_recv > 0:
            send_str = f"{max_send}" if max_send > 0 else "∞"
            recv_str = f"{max_recv}" if max_recv > 0 else "∞"
            bandwidth_str = f"↑{send_str}/↓{recv_str} Kbps"
        else:
            bandwidth_str = "Unlimited"

        conn_b = connections_before.get(device_id)
        conn_a = connections_after.get(device_id)

        if conn_a and conn_a.get("connected"):
            status = "●"
        elif paused:
            status = "⏸"
        else:
            status = "◌"

        row = [
            device_id,
            name,
            status + " " + str_utils.relative_datetime(str_utils.isodate2seconds(last_seen)),
            str_utils.duration_short(last_duration),
            bandwidth_str,
        ]

        if args.xfer and conn_a and conn_b and conn_a.get("connected"):
            conn_at_b = _parse_at(conn_b.get("at")) if conn_b else total_at_before
            conn_at_a = _parse_at(conn_a.get("at")) if conn_a else total_at_after
            dt_dev = (conn_at_a - conn_at_b).total_seconds() or dt
            ul, dl = _calc_rate(conn_b, conn_a, dt_dev)
            row.append(f"↑{ul:.1f} KB/s / ↓{dl:.1f} KB/s")

        table_data.append(row)

    headers = [
        "Device ID",
        "Name",
        "Last Seen",
        "Duration",
        "Bandwidth Limit",
    ]

    if args.xfer:
        headers.append("UL / DL")

    print(tabulate(table_data, headers=headers, tablefmt="simple"))

    print(f"\nTotal devices: {len(devices) - 1}", end="")
    if args.xfer and total_up is not None:
        print(f"  |  Total ↑{total_up:.1f} KB/s  ↓{total_down:.1f} KB/s (Δt={dt:.1f}s)")
    else:
        print()
