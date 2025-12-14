#!/usr/bin/env python3

import os, shutil
from collections import Counter, defaultdict
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
            }
        )

    return summaries


def cmd_list_folders(args):
    if not any([args.joined, args.pending, args.discovered]):
        args.joined, args.pending, args.discovered = True, True, True

    existing_folders = args.st.folders()
    existing_folder_ids = {f["id"]: f for f in existing_folders}

    pending_folders = []
    if args.pending or args.discovered:
        pending_folders = conform_pending_folders(args.st.pending_folders())

    folders = []
    if args.joined:
        folders.extend(existing_folders)
    if args.pending:
        folders.extend([{**d, "pending": True} for d in pending_folders if d["id"] in existing_folder_ids])
    if args.discovered:
        folders.extend([{**d, "discovered": True} for d in pending_folders if d["id"] not in existing_folder_ids])

    if not folders:
        log.info("No folders configured or matched")
        return

    pending_device_folders_count = defaultdict(int)
    for d in folders:
        if d.get("pending"):
            pending_device_folders_count[d[id]] += 1

    filtered_folders = []
    for folder in folders:
        folder_id = folder.get("id")
        label = folder.get("label")
        path = folder.get("path")
        paused = folder.get("paused") or False
        status = "⏸️" if paused else ""
        pending = folder.get("pending") or False
        discovered = folder.get("discovered") or False

        if discovered:
            path = folder.get("devices")[0]

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
        err_fmt = []
        if err_count:
            err_fmt.append(f"errors:{err_count}")
        if pull_errors:
            err_fmt.append(f"pull:{pull_errors}")
        if err_msg:
            err_fmt.append(err_msg.strip())
        err_fmt = ", ".join(err_fmt) or "-"

        devices = folder.get("devices") or []
        device_count_fmt = f"{len(devices)}"
        if pending_device_folders_count.get(folder_id):
            device_count_fmt += f" ({pending_device_folders_count[folder_id]})"

        free_space = None
        if path and os.path.exists(path):
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
                "device_count_fmt": device_count_fmt,
                "err_fmt": err_fmt,
                "pending": pending,
            }
        )

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
            "Peers": d["device_count_fmt"],
            "Errors": d["err_fmt"],
        }
        for d in filtered_folders
        # for existing pending folders just show the number of devices
        # that want to join the folder (pending_device_folders_count)
        if not args.joined or (args.joined and not d["pending"])
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

    if args.join:
        pending_folders = [d for d in filtered_folders if d.get('pending') or d.get('discovered')]
        if not pending_folders:
            log.info(f"[%s] No pending folders", args.st.name)
            return

        for folder in pending_folders:
            folder_id = folder["id"]
            offered_by = folder.get("offeredBy", {}) or {}
            device_ids = list(offered_by.keys())

            if not device_ids:
                log.error(f"[%s] No devices offering folder '%s'", args.st.name, folder_id)
                continue

            if folder_id in existing_folder_ids:  # folder exists; just add new devices
                args.st.add_folder_devices(folder_id, device_ids)
                # pause and resume devices to unstuck them (ie. "Unexpected folder ID in ClusterConfig")
                for device_id in device_ids:
                    args.st.pause(device_id)
                for device_id in device_ids:
                    args.st.resume(device_id)
            else:  # folder doesn't exist; create it (with devices)
                log.info(f"[%s] Creating folder '%s'", args.st.name, folder_id)
                cfg = {
                    "id": folder_id,
                    "label": folder_id,
                    "path": str(args.st.home / folder_id),
                    "type": "receiveonly",
                    "devices": [{"deviceID": d} for d in device_ids],
                }
                args.st._post("config/folders", json=cfg)
