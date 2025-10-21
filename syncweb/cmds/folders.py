#!/usr/bin/env python3

import os, shutil
from collections import Counter
from datetime import datetime

from tabulate import tabulate

from syncweb.log_utils import log
from syncweb.str_utils import file_size


def conform_pending_folders(pending):
    summaries = []
    for folder_id, folder_data in pending.items():
        offered_by = folder_data.get("offeredBy", {})
        if not offered_by:
            continue

        labels, times, recv_enc, remote_enc = [], [], [], []
        device_ids = list(offered_by.keys())

        for info in offered_by.values():
            time_str = info.get("time")
            if time_str:
                times.append(datetime.fromisoformat(time_str.replace("Z", "+00:00")))
            labels.append(info.get("label"))
            recv_enc.append(info.get("receiveEncrypted", False))
            remote_enc.append(info.get("remoteEncrypted", False))

        label = Counter(labels).most_common(1)[0][0] if labels else None
        min_time = min(times).isoformat() if times else None
        max_time = max(times).isoformat() if times else None

        summaries.append(
            {
                "id": folder_id,
                "label": label,
                "min_time": min_time,
                "max_time": max_time,
                "receiveEncrypted": any(recv_enc),
                "remoteEncrypted": any(remote_enc),
                "devices": device_ids,
                "pending": True,
            }
        )

    return summaries


def cmd_list_folders(args):
    device_id = args.st.device_id

    if args.join:
        # TODO: add option(s) to filter by label, devices, or folder_id
        args.st.join_pending_folders()

    folders = []
    if not args.pending:
        folders.extend(args.st.folders())
    if not args.accepted:
        folders.extend(conform_pending_folders(args.st.pending_folders()))

    if not folders:
        log.info("No folders configured")
        return

    table_data = []
    for folder in folders:
        folder_id = folder.get("id") or "unknown"
        label = folder.get("label") or "-"
        path = folder.get("path") or ""
        paused = folder.get("paused") or False
        status = "⏸️" if paused else ""
        pending = folder.get("pending") or False

        url = f"sync://{folder_id}#{device_id}"
        if pending:
            url = f"sync://{folder_id}#{folder.get('devices')[0]}"
        print(url)

        fs = {}
        if not pending:
            fs |= args.st.folder_status(folder_id)

        # Basic state
        state = fs.get("state")
        if not state:
            state = "pending" if pending else "unknown"

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
        device_count = len(devices) - (0 if pending else 1)

        free_str = "-"
        if os.path.exists(path):
            disk_info = shutil.disk_usage(path)
            if disk_info:
                free_str = file_size(disk_info.free)

        table_data.append(
            [
                folder_id,
                label,
                "-" if pending else path,
                "-" if pending else f"{local_files} files ({file_size(local_bytes)})",
                "-" if pending else f"{need_files} files ({file_size(need_bytes)})",
                "-" if pending else f"{global_files} files ({file_size(global_bytes)})",
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
