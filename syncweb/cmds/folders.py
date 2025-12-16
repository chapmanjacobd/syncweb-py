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
                "pending_devices": device_ids,
            }
        )

    return summaries


def cmd_list_folders(args):
    if not any([args.joined, args.pending, args.discovered]):
        args.joined, args.pending, args.discovered = True, True, True

    existing_folders = args.st.folders()
    existing_folder_ids = {d["id"]: d for d in existing_folders}
    for d in existing_folders:
        d["devices"] = [dd["deviceID"] for dd in d["devices"]]

    pending_folders = []
    if args.pending or args.discovered:
        pending_folders = conform_pending_folders(args.st.pending_folders())

    folders = {}
    if args.joined:
        for d in existing_folders:
            folders[d["id"]] = d
    if args.pending:
        for d in pending_folders:
            if d["id"] in existing_folder_ids:
                if args.joined:
                    folders[d["id"]]["pending_devices"] = d["pending_devices"]
                else:
                    folders[d["id"]] = d
    if args.discovered:
        for d in pending_folders:
            if d["id"] not in existing_folder_ids:
                folders[d["id"]] = d

    if not folders:
        log.info("No folders configured or matched")
        return

    local_devices = []
    if args.local_only:
        local_devices.append(args.st.device_id)
        local_devices.extend(args.st.devices(local_only=args.local_only))
        local_devices.extend(args.st.pending_devices(local_only=args.local_only).keys())
        local_devices.extend(args.st.discovered_devices(local_only=args.local_only).keys())

    filtered_folders = []
    for folder_id, folder in folders.items():
        label = folder.get("label")
        path = folder.get("path")
        paused = folder.get("paused") or False

        devices = folder.get("devices") or []
        pending_devices = folder.get("pending_devices") or []
        if args.local_only:
            devices = [s for s in devices if s in local_devices]
            pending_devices = [s for s in pending_devices if s in local_devices]

        discovered_folder = not devices
        folder_status = {} if discovered_folder else args.st.folder_status(folder_id)
        if args.missing:
            error = folder_status.get("error")
            if error is None:
                continue
            elif "folder path missing" not in error:
                continue

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
                "free_space": free_space,
                "paused": paused,
                "folder_status": folder_status,
                "devices": devices,
                "pending_devices": pending_devices,
            }
        )

    if not filtered_folders:
        log.info("No folders missing")
        return

    if args.print:
        for d in filtered_folders:
            folder_id = d["folder_id"]

            discovered_folder = not d["devices"]
            pending_devices = d["pending_devices"]
            if discovered_folder and pending_devices:
                url = f"sync://{folder_id}#{pending_devices[0]}"
            else:
                url = f"sync://{folder_id}#{args.st.device_id}"
            str_utils.pipe_print(url)
    else:
        table_data = []
        for d in filtered_folders:
            path = d["path"]
            folder_status = d["folder_status"]
            devices = d["devices"]
            pending_devices = d["pending_devices"]
            discovered_folder = not devices

            # Basic state
            state = folder_status.get("state")
            if not state:
                state = "pending" if discovered_folder else "unknown"

            # Local vs Global
            local_files = folder_status.get("localFiles")
            global_files = folder_status.get("globalFiles")
            local_bytes = folder_status.get("localBytes")
            global_bytes = folder_status.get("globalBytes")

            # Sync progress (remaining items)
            need_files = folder_status.get("needFiles")
            need_bytes = folder_status.get("needBytes")
            sync_pct = 100
            if global_bytes and global_bytes > 0:
                sync_pct = (1 - (need_bytes / global_bytes)) * 100

            # Errors and pulls
            err_count = folder_status.get("errors")
            pull_errors = folder_status.get("pullErrors")
            err_msg = folder_status.get("error") or folder_status.get("invalid") or ""
            err_fmt = []
            if err_count:
                err_fmt.append(f"errors:{err_count}")
            if pull_errors:
                err_fmt.append(f"pull:{pull_errors}")
            if err_msg:
                err_fmt.append(err_msg.strip())
            err_fmt = ", ".join(err_fmt) or "-"

            device_count_fmt = f"{len(devices)}"
            if pending_devices:
                device_count_fmt += f" ({len(pending_devices)})"

            if discovered_folder and pending_devices:
                path = pending_devices[0]

            status = "⏸️" if d["paused"] else ""

            table_data.append(
                {
                    "Folder ID": d["folder_id"],
                    "Label": d["label"],
                    "Path": path or "-",
                    "Local": (
                        "%d files (%s)" % (local_files, file_size(local_bytes)) if local_files is not None else "-"
                    ),
                    "Needed": (
                        "%d files (%s)" % (need_files, file_size(need_bytes)) if need_files is not None else "-"
                    ),
                    "Global": (
                        "%d files (%s)" % (global_files, file_size(global_bytes)) if global_files is not None else "-"
                    ),
                    "Free": d["free_space"] or "-",
                    "Sync Status": "%s %.0f%% %s" % (status, sync_pct, state),
                    "Peers": device_count_fmt,
                    "Errors": err_fmt,
                }
            )
        print(tabulate(table_data, headers="keys", tablefmt="simple"))
        print()

    if args.delete_files:
        for filtered_folder in filtered_folders:
            if filtered_folder["devices"] and os.path.exists(filtered_folder["path"]):
                shutil.rmtree(filtered_folder["path"])

    if args.delete:
        for filtered_folder in filtered_folders:
            for device_id in filtered_folder["pending_devices"]:
                args.st.delete_pending_folder(filtered_folder["folder_id"], device_id)
            if filtered_folder["devices"]:
                args.st.delete_folder(filtered_folder["folder_id"])

    if args.join:
        pending_folders = [d for d in filtered_folders if d["pending_devices"]]
        if not pending_folders:
            log.info(f"[%s] No pending folders", args.st.name)
            return

        for folder in pending_folders:
            folder_id = folder["folder_id"]
            device_ids = folder["pending_devices"]

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
