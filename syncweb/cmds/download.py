#!/usr/bin/env python3
import os, shlex, shutil
from collections import defaultdict
from pathlib import Path

from syncweb import str_utils
from syncweb.cmds.ls import is_directory, path2fid
from syncweb.log_utils import log

# TODO: add --timeout-size and quantity limits
# add option to truncate at free space limit


def collect_files(args, items, current_path=""):
    for item in items:
        name = item.get("name", "")
        item_path = f"{current_path}/{name}" if current_path else name
        size = item.get("size", 0)

        is_dir = is_directory(item)

        if not is_dir:  # It's a file
            yield (item_path, size)
        elif "children" in item and item["children"]:  # Recurse into directory
            yield from collect_files(args, item["children"], item_path)


def calculate_min_disk_free(total_space, min_disk_free):
    value = min_disk_free.get("value", 1)
    unit = min_disk_free.get("unit", "%")

    if unit == "%":
        return int(total_space * value / 100)
    elif unit.lower() in ("kb", "kib"):
        return value * 1024
    elif unit.lower() in ("mb", "mib"):
        return value * 1024 * 1024
    elif unit.lower() in ("gb", "gib"):
        return value * 1024 * 1024 * 1024
    elif unit.lower() in ("tb", "tib"):
        return value * 1024 * 1024 * 1024 * 1024
    else:  # bytes ?
        return value


def get_folder_space_info(args, folder_id):
    try:
        # Get folder info
        folders = args.st.folders() or []
        folder_info = None
        for folder in folders:
            if folder["id"] == folder_id:
                folder_info = folder
                break

        if not folder_info:
            return None

        folder_path = folder_info.get("path")
        if not folder_path:
            return None

        # Get disk space info
        disk_stat = shutil.disk_usage(folder_path)

        # Get pending download size from Syncthing
        pending_download = 0
        try:
            status = args.st.folder_status(folder_id)
            pending_download = status.get("needBytes", 0)
            log.debug("Folder %s has %d bytes pending download", folder_id, pending_download)
        except Exception as e:
            log.debug("Failed to get needBytes for folder %s: %s", folder_id, e)

        # Try to get actual mountpoint for better grouping
        try:
            # Get the actual mountpoint by checking stat.st_dev
            path_obj = Path(folder_path).resolve()
            folder_stat = os.stat(path_obj)
            dev = folder_stat.st_dev

            # Find mountpoint by walking up until device changes
            mountpoint = path_obj
            while mountpoint.parent != mountpoint:
                try:
                    parent_stat = os.stat(mountpoint.parent)
                    if parent_stat.st_dev != dev:
                        break
                    mountpoint = mountpoint.parent
                except (OSError, PermissionError):
                    break
            mountpoint_str = str(mountpoint)
            device_id = dev
        except Exception:
            # Fallback: use the folder path itself
            mountpoint_str = folder_path
            device_id = None

        # Calculate minimum free space to preserve
        min_disk_free_config = folder_info.get("minDiskFree", {"value": 1, "unit": "%"})
        min_free = calculate_min_disk_free(disk_stat.total, min_disk_free_config)

        # Usable space = free space - minimum buffer - pending downloads
        usable = max(0, disk_stat.free - min_free - pending_download)

        return {
            "free": disk_stat.free,
            "total": disk_stat.total,
            "min_free": min_free,
            "usable": usable,
            "min_free_config": min_disk_free_config,
            "mountpoint": mountpoint_str,
            "device_id": device_id,
            "pending_download": pending_download,
        }
    except Exception as e:
        log.debug("Failed to get space info for folder %s: %s", folder_id, e)
        return None


def group_folders_by_mountpoint(folder_stats):
    from collections import defaultdict

    # Group by free space + total space as a heuristic for same mountpoint
    # This handles cases where we can't determine actual mountpoint
    mountpoint_groups = defaultdict(list)

    for folder_id, stats in folder_stats.items():
        space_info = stats.get("space_info")
        if space_info is None:
            # Each folder with unknown space is its own group
            mountpoint_groups[f"unknown_{folder_id}"].append(folder_id)
            continue

        # Try to use actual mountpoint if available
        mountpoint = space_info.get("mountpoint")
        if mountpoint:
            mountpoint_groups[mountpoint].append(folder_id)
        else:
            # Fallback: group by free+total space (likely same partition)
            # Use tuple as key: (free, total)
            key = (space_info["free"], space_info["total"])
            mountpoint_groups[f"partition_{key}"].append(folder_id)

    return mountpoint_groups


def calculate_mountpoint_pending_downloads(folder_ids, folder_stats) -> int:
    total_pending = 0
    for folder_id in folder_ids:  # same mountpoint
        space_info = folder_stats[folder_id].get("space_info")
        if space_info:
            total_pending += space_info.get("pending_download", 0)

    return total_pending


def build_download_plan(args, paths):
    plan = defaultdict(list)
    for path in paths:
        path = path.strip()
        if not path:
            continue

        abs_path = Path(path).resolve()
        folder_id, prefix = path2fid(args, abs_path)

        if folder_id is None:
            log.warning("%s is not inside of a Syncthing folder", shlex.quote(str(abs_path)))
            continue
        if not prefix:
            log.warning("%s: is not a relative path. Including all files in %s...", path, folder_id)
            prefix = "/"

        file_data = args.st.file(folder_id, prefix)
        if file_data and file_data["global"]["type"] != "FILE_INFO_TYPE_DIRECTORY":
            size = file_data["global"]["size"]
            plan[folder_id].append((prefix, size))
        else:
            folder_data = args.st.files(folder_id, levels=args.depth, prefix=prefix)
            if not folder_data:
                log.warning("%s: No data returned", shlex.quote(path))
                continue

            # Collect files
            for file_path, size in collect_files(args, folder_data, prefix):
                plan[folder_id].append((file_path, size))

    return plan


def print_download_summary(args, plan) -> bool:
    if not plan:
        log.info("No files to download")
        return False

    # Calculate totals per folder
    folder_stats = {}
    warnings = []
    for folder_id, files in plan.items():
        total_size = sum(size for _, size in files)
        file_count = len(files)
        space_info = get_folder_space_info(args, folder_id)

        folder_stats[folder_id] = {"count": file_count, "size": total_size, "space_info": space_info}

    # Group folders by mountpoint to avoid double-booking space
    mountpoint_groups = group_folders_by_mountpoint(folder_stats)

    # TODO: We should also subtract space for files queued for download but not yet downloaded

    # Calculate space usage per mountpoint
    mountpoint_usage = {}
    for mountpoint, folder_ids in mountpoint_groups.items():
        total_download_size = sum(folder_stats[fid]["size"] for fid in folder_ids)

        # Get space info from first folder in group (they share same mountpoint)
        first_folder_id = folder_ids[0]
        space_info = folder_stats[first_folder_id].get("space_info")

        if space_info is not None:
            # Calculate maximum buffer requirement across all folders on this mountpoint
            max_min_free = max(
                folder_stats[fid]["space_info"]["min_free"]
                for fid in folder_ids
                if folder_stats[fid]["space_info"] is not None
            )

            # Calculate total pending downloads across all folders on this mountpoint
            total_pending = calculate_mountpoint_pending_downloads(folder_ids, folder_stats)

            # Usable = free - max_buffer - pending_downloads
            usable = max(0, space_info["free"] - max_min_free - total_pending)

            mountpoint_usage[mountpoint] = {
                "total_download": total_download_size,
                "usable": usable,
                "free": space_info["free"],
                "max_min_free": max_min_free,
                "total_pending": total_pending,
                "folder_ids": folder_ids,
                "shared": len(folder_ids) > 1,
            }

            # Check if total size exceeds usable space for this mountpoint
            if total_download_size > usable:
                if len(folder_ids) > 1:
                    folder_list = ", ".join(folder_ids[:3])
                    if len(folder_ids) > 3:
                        folder_list += f", ... ({len(folder_ids)} total)"
                    warnings.append(
                        f"⚠ Shared mountpoint ({mountpoint}): "
                        f"Combined download size ({str_utils.file_size(total_download_size)}) "
                        f"exceeds usable space ({str_utils.file_size(usable)}) "
                        f"across folders: {folder_list}"
                    )
                else:
                    space_info_folder = folder_stats[first_folder_id]["space_info"]
                    min_free_config = space_info_folder["min_free_config"]
                    buffer_desc = f"{min_free_config['value']}{min_free_config['unit']}"
                    warnings.append(
                        f"⚠ Folder {first_folder_id}: Download size ({str_utils.file_size(total_download_size)}) "
                        f"exceeds usable space ({str_utils.file_size(usable)}) "
                        f"[preserving {str_utils.file_size(max_min_free)} buffer ({buffer_desc})]"
                    )

    # Print table header
    print("\nDownload Summary:")
    print("-" * 135)
    print(
        f"{'Folder ID':<40} {'Files':>8} {'Total Size':>12} {'Usable':>12} {'Pending':>12} {'Buffer':>12} {'Shared':>7} {'Status':>8}"
    )
    print("-" * 135)

    # Print each folder
    grand_total_size = 0
    grand_total_files = 0

    for folder_id, stats in folder_stats.items():
        count = stats["count"]
        size = stats["size"]
        space_info = stats["space_info"]

        grand_total_size += size
        grand_total_files += count

        # Find which mountpoint this folder belongs to
        folder_mountpoint = None
        for mp, mp_info in mountpoint_usage.items():
            if folder_id in mp_info["folder_ids"]:
                folder_mountpoint = mp
                break

        # Status indicator and space strings
        if space_info is not None and folder_mountpoint:
            mp_info = mountpoint_usage[folder_mountpoint]
            usable = mp_info["usable"]
            max_min_free = mp_info["max_min_free"]
            total_pending = mp_info["total_pending"]
            total_download_on_mp = mp_info["total_download"]
            is_shared = mp_info["shared"]

            # For display, show the folder's individual buffer config and pending downloads
            min_free_config = space_info["min_free_config"]
            buffer_desc = f"{min_free_config['value']}{min_free_config['unit']}"
            buffer_str = f"{str_utils.file_size(space_info['min_free'])} ({buffer_desc})"

            pending_download = space_info.get("pending_download", 0)
            pending_str = str_utils.file_size(pending_download) if pending_download > 0 else "-"

            usable_str = str_utils.file_size(usable)
            shared_str = "Yes" if is_shared else "No"

            # Status based on total mountpoint usage, not individual folder
            if total_download_on_mp > usable:
                status = "⚠ LOW"
            else:
                status = "OK"
        else:
            usable_str = "Unknown"
            pending_str = "?"
            buffer_str = "Unknown"
            shared_str = "?"
            status = "?"

        print(
            f"{folder_id:<40} {count:>8} {str_utils.file_size(size):>12} {usable_str:>12} {pending_str:>12} {buffer_str:>12} {shared_str:>7} {status:>8}"
        )

    # Print totals
    print("-" * 135)
    print(f"{'TOTAL':<40} {grand_total_files:>8} {str_utils.file_size(grand_total_size):>12}")
    print("-" * 135)

    # Print mountpoint summary if there are shared mountpoints
    shared_mps = [mp for mp, info in mountpoint_usage.items() if info["shared"]]
    if shared_mps:
        print("\nShared Mountpoints:")
        for mp in shared_mps:
            info = mountpoint_usage[mp]
            print(f"  {mp}:")
            print(f"    Folders: {', '.join(info['folder_ids'])}")
            print(f"    Combined download: {str_utils.file_size(info['total_download'])}")
            print(f"    Pending downloads: {str_utils.file_size(info['total_pending'])}")
            print(
                f"    Usable space: {str_utils.file_size(info['usable'])} (after {str_utils.file_size(info['max_min_free'])} buffer and {str_utils.file_size(info['total_pending'])} pending)"
            )

    # Print warnings
    if warnings:
        print("\n⚠ WARNINGS:")
        for warning in warnings:
            print(f"  {warning}")
        print()

    if args.no_confirm:
        return True

    warning_suffix = " (WARNING: Insufficient space!)" if warnings else ""
    try:
        response = input(
            f"\nMark {grand_total_files} files ({str_utils.file_size(grand_total_size)}) for download?{warning_suffix} [y/N]: "
        )
        return response.lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted")
        return False


def cmd_download(args):
    if not args.paths:
        log.error("No paths provided")
        raise SystemExit(2)

    # Build download plan
    log.debug("Building download plan for %d paths...", len(args.paths))
    plan = build_download_plan(args, args.paths)

    if not plan:
        log.error("No files found to download")
        raise SystemExit(0)

    # Show summary and get confirmation
    if not print_download_summary(args, plan):
        log.info("Download cancelled")
        raise SystemExit(3)

    # Execute unignore operations
    download_count = 0
    for folder_id, files in plan.items():
        rel_paths = [file_path for file_path, _ in files]

        try:
            log.info("Queueing %d files in folder %s...", len(rel_paths), folder_id)
            args.st.add_ignores(folder_id, rel_paths)
            download_count += len(rel_paths)

        except Exception as e:
            log.error("Failed to unignore files in folder %s: %s", folder_id, str(e))
            continue

    log.info("Total: Queued %d files across %d folders", download_count, len(plan))
