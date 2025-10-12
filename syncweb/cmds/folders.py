#!/usr/bin/env python3

import shutil

from tabulate import tabulate

from syncweb.log_utils import log
from syncweb.str_utils import file_size


def cmd_list_folders(args):
    device_id = args.st.device_id
    folders = args.st.folders()

    if not folders:
        log.info("No folders configured")
        return

    table_data = []
    for folder in folders:
        folder_id = folder.get("id", "unknown")
        label = folder.get("label", "-")
        path = folder.get("path", "")
        paused = folder.get("paused", False)
        status = "⏸" if paused else "▶"

        url = f"sync://{folder_id}#{device_id}"
        print(url)

        fs = args.st.folder_status(folder_id) or {}

        # Basic state
        state = fs.get("state", "unknown")

        # Local vs Global
        local_files = fs.get("localFiles", 0)
        global_files = fs.get("globalFiles", 0)
        local_bytes = fs.get("localBytes", 0)
        global_bytes = fs.get("globalBytes", 0)

        # Sync progress (remaining items)
        need_files = fs.get("needFiles", 0)
        need_bytes = fs.get("needBytes", 0)
        sync_pct = 100
        if global_bytes > 0:
            sync_pct = (1 - (need_bytes / global_bytes)) * 100

        # Errors and pulls
        err_count = fs.get("errors", 0)
        pull_errors = fs.get("pullErrors", 0)
        err_msg = fs.get("error") or fs.get("invalid") or ""
        err_display = []
        if err_count:
            err_display.append(f"errors:{err_count}")
        if pull_errors:
            err_display.append(f"pull:{pull_errors}")
        if err_msg:
            err_display.append(err_msg.strip())
        err_display = ", ".join(err_display) or "-"

        devices = folder.get("devices") or []
        device_count = len(devices) - 1

        disk_info = shutil.disk_usage(path)
        if disk_info:
            free_str = file_size(disk_info.free)
        else:
            free_str = ""

        table_data.append(
            [
                folder_id,
                label,
                path,
                f"{local_files} files ({file_size(local_bytes)})",
                f"{need_files} files ({file_size(need_bytes)})",
                f"{global_files} files ({file_size(global_bytes)})",
                free_str,
                f"{status} {sync_pct:.0f}% {state}",
                device_count,
                err_display,
            ]
        )

    headers = [
        "Folder ID",
        "Label",
        "Path",
        "Local",
        "Needed",
        "Global",
        "Free",
        "Sync Status",
        "Peers",
        "Errors",
    ]

    print()
    print(tabulate(table_data, headers=headers, tablefmt="simple"))
    print(f"\nTotal folders: {len(folders)}")
