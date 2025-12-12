#!/usr/bin/env python3

import os, shutil
from collections import Counter
from datetime import datetime

from tabulate import tabulate

from syncweb import str_utils
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
    if not any([args.joined, args.pending]):
        args.joined, args.pending = True, True

    folders = []
    if args.joined:
        folders.extend(args.st.folders())
    if not args.pending:
        folders.extend(conform_pending_folders(args.st.pending_folders()))

    if not folders:
        log.info("No folders configured or matched")
        return

    filtered_folders = []
    for folder in folders:
        folder_id = folder.get("id")
        label = folder.get("label")
        path = folder.get("path")
        paused = folder.get("paused") or False
        status = "⏸️" if paused else ""
        pending = folder.get("pending") or False

        if args.print:
            url = f"sync://{folder_id}#{args.st.device_id}"
            if pending:
                url = f"sync://{folder_id}#{folder.get('devices')[0]}"
            str_utils.pipe_print(url)

        fs = {}
        if not pending:
            fs |= args.st.folder_status(folder_id)

        if args.missing:
            error = fs.get("error")
            if error is None:
                continue
            elif "folder path missing" not in error:
                continue

        # Basic state
        state = fs.get("state")
        if not state:
            state = "pending" if pending else "unknown"

        # Local vs Global
        local_files = fs.get("localFiles")
        global_files = fs.get("globalFiles")
        local_bytes = fs.get("localBytes")
        global_bytes = fs.get("globalBytes")

        # Sync progress (remaining items)
        need_files = fs.get("needFiles")
        need_bytes = fs.get("needBytes")
        sync_pct = 100
        if global_bytes and global_bytes > 0:
            sync_pct = (1 - (need_bytes / global_bytes)) * 100

        # Errors and pulls
        err_count = fs.get("errors")
        pull_errors = fs.get("pullErrors")
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

        free_space = None
        if os.path.exists(path):
            disk_info = shutil.disk_usage(path)
            if disk_info:
                free_space = file_size(disk_info.free)

        filtered_folders.append(
            {
                "folder_id": folder_id,
                "label": label,
                "path": path,
                "local_files": local_files,
                "local_bytes": local_bytes,
                "need_files": need_files,
                "need_bytes": need_bytes,
                "global_files": global_files,
                "global_bytes": global_bytes,
                "free_space": free_space,
                "status": status,
                "sync_pct": sync_pct,
                "state": state,
                "device_count": device_count,
                "err_display": err_display,
                "pending": pending,
            }
        )

    if args.join:
        # TODO: add option(s) to filter by label, devices, or folder_id
        args.st.join_pending_folders()

    table_data = [
        {
            "Folder ID": d["folder_id"],
            "Label": d["label"],
            "Path": d["path"] or "-",
            "Local": (
                "%d files (%s)" % (d["local_files"], file_size(d["local_bytes"]))
                if d["local_files"] is not None
                else "-"
            ),
            "Needed": (
                "%d files (%s)" % (d["need_files"], file_size(d["need_bytes"])) if d["need_files"] is not None else "-"
            ),
            "Global": (
                "%d files (%s)" % (d["global_files"], file_size(d["global_bytes"]))
                if d["global_files"] is not None
                else "-"
            ),
            "Free": d["free_space"] or "-",
            "Sync Status": "%s %.0f%% %s" % (d["status"], d["sync_pct"], d["state"]),
            "Peers": d["device_count"],
            "Errors": d["err_display"],
        }
        for d in filtered_folders
    ]

    if not args.print:
        print(tabulate(table_data, headers="keys", tablefmt="simple"))

    if args.delete_files:
        print()
        for filtered_folder in filtered_folders:
            if not filtered_folder["pending"]:
                shutil.rmtree(filtered_folder["path"])

    if args.delete:
        for filtered_folder in filtered_folders:
            if filtered_folder["pending"]:
                args.st.delete_pending_folder(filtered_folder["folder_id"])
            else:
                args.st.delete_folder(filtered_folder["folder_id"])
