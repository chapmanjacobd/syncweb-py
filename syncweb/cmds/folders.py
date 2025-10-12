#!/usr/bin/env python3

import shutil

from tabulate import tabulate

from syncweb.log_utils import log
from syncweb.str_utils import file_size

# TODO: add args.st.folder_status(folder_id)
# print syncweb URL per folder with local device ID

def get_disk_usage(path):
    try:
        stat = shutil.disk_usage(path)
        used = stat.total - stat.free
        percent = (used / stat.total * 100) if stat.total > 0 else 0
        return {"total": stat.total, "used": used, "free": stat.free, "percent": percent}
    except Exception:
        return None


def cmd_list_folders(args):
    folders = args.st.folders()

    if not folders:
        log.info("No folders configured")
        return

    # Prepare table data
    table_data = []

    for folder in folders:
        folder_id = folder.get("id", "unknown")
        label = folder.get("label", "")
        path = folder.get("path", "")
        folder_type = folder.get("type", "unknown")
        paused = folder.get("paused", False)

        # Get device count
        devices = folder.get("devices", [])
        device_count = len(devices)

        # Get min disk free setting
        min_disk_free = folder.get("minDiskFree", {})
        min_free_str = f"{min_disk_free.get('value', 1)}{min_disk_free.get('unit', '%')}"

        # Get disk usage if path exists
        disk_info = get_disk_usage(path) if path else None
        if disk_info:
            disk_str = f"{file_size(disk_info['used'])} / {file_size(disk_info['total'])} ({disk_info['percent']:.1f}%)"
            free_str = file_size(disk_info["free"])
        else:
            disk_str = "N/A"
            free_str = "N/A"

        # Status
        status = "⏸ Paused" if paused else "✓ Active"

        if args.verbose:
            fs_type = folder.get("filesystemType", "basic")
            rescan = folder.get("rescanIntervalS", 3600)
            fs_watcher = "Yes" if folder.get("fsWatcherEnabled", False) else "No"

            table_data.append(
                [
                    folder_id,
                    label or "-",
                    path,
                    folder_type,
                    device_count,
                    disk_str,
                    free_str,
                    min_free_str,
                    fs_type,
                    f"{rescan}s",
                    fs_watcher,
                    status,
                ]
            )
        else:
            # Standard mode
            table_data.append(
                [folder_id, label or "-", path, folder_type, device_count, disk_str, free_str, min_free_str, status]
            )

    # Print table
    if args.verbose:
        headers = [
            "ID",
            "Label",
            "Path",
            "Type",
            "Devices",
            "Used/Total",
            "Free",
            "Min Free",
            "FS Type",
            "Rescan",
            "Watcher",
            "Status",
        ]
    else:
        headers = ["ID", "Label", "Path", "Type", "Devices", "Used/Total", "Free", "Min Free", "Status"]

    print(tabulate(table_data, headers=headers, tablefmt="simple"))
    print(f"\nTotal folders: {len(folders)}")
