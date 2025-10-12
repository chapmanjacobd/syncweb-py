#!/usr/bin/env python3
import datetime, shlex
from pathlib import Path

from syncweb.cmds.ls import path2fid
from syncweb.log_utils import log


def format_timestamp(timestamp_str: str, format_type: str = "human") -> str:
    try:
        dt = datetime.datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

        if format_type == "unix":
            return str(int(dt.timestamp()))
        elif format_type == "iso":
            return timestamp_str
        else:  # human
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S.%f") + dt.strftime(" %z")
    except (ValueError, AttributeError):
        return timestamp_str


def get_file_type(item: dict) -> str:
    file_type = item.get("type", "")
    if file_type == "FILE_INFO_TYPE_DIRECTORY":
        return "directory"
    elif file_type == "FILE_INFO_TYPE_FILE":
        return "regular file"
    elif file_type == "FILE_INFO_TYPE_SYMLINK":
        return "symbolic link"
    else:
        return "unknown"


def print_stat(args, file_data: dict, path: str) -> None:
    local = file_data.get("local", {})
    global_data = file_data.get("global", {})

    # local for display, but compare both
    name = local.get("name", path)
    size = local.get("size", 0)
    file_type = get_file_type(local)
    modified = local.get("modified", "")
    inode_change = local.get("inodeChange", "")
    permissions = local.get("permissions", "0000")
    modified_by = local.get("modifiedBy", "unknown")
    version = local.get("version") or []
    num_blocks = local.get("numBlocks", 0)
    deleted = local.get("deleted", False)
    ignored = local.get("ignored", False)
    invalid = local.get("invalid", False)

    availability = file_data.get("availability") or []
    num_devices = len(availability)
    device_ids = [args.st.device_long2name(av.get("id", "unknown")) for av in availability]

    diffs = []
    for key in ["size", "modified", "deleted", "ignored", "invalid"]:
        local_value = local.get(key)
        global_value = global_data.get(key)
        if local_value == global_value:
            continue

        if key == "modified":
            local_value = format_timestamp(local_value, args.time_format)
            global_value = format_timestamp(global_value, args.time_format)

        if isinstance(local_value, bool):
            local_value = "Yes" if local_value else "No"
            global_value = "Yes" if global_value else "No"

        diffs.append([key, str(local_value), str(global_value)])

    if args.terse:
        # Terse format: name|size|blocks|permissions|type|modified|device_count|has_diffs
        print(f"{path}|{size}|{num_blocks}|{permissions}|{file_type}|{modified}|{num_devices}|{len(diffs)}")
    elif args.format:
        output = args.format
        output = output.replace("%n", name)
        output = output.replace("%s", str(size))
        output = output.replace("%b", str(num_blocks))
        output = output.replace("%f", permissions)
        output = output.replace("%F", file_type)
        output = output.replace("%y", modified)
        output = output.encode("utf-8").decode("unicode_escape")
        print(output)
    else:
        print(f"  Path: {path}")
        print(f"  Size: {size:<15} Blocks: {num_blocks:<10}   {file_type}")

        # Device availability
        if num_devices <= 3:
            device_str = ", ".join(device_ids) if device_ids else "none"
        else:
            device_str = f"{num_devices} devices"

        version_str = ""
        if version:
            version_str = ", ".join(version[:3])
            if len(version) > 3:
                version_str += f", ... ({len(version)} total)"

        print(f"Device: {device_str:<15} Version: {version_str}")

        # Permissions and flags
        flags = []
        if deleted:
            flags.append("deleted")
        if ignored:
            flags.append("ignored")
        if invalid:
            flags.append("invalid")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"Access: ({permissions}/---------) {flag_str}")

        # Timestamps
        print(
            f"Modify: {format_timestamp(modified, args.time_format)}",
            f"{args.st.device_long2name(args.st.device_short2long(modified_by))}",
        )
        print(f"Change: {format_timestamp(inode_change, args.time_format)}")

        # Show differences between local and global
        headers = ["Key", "Local", "Global"]
        # Compute column widths
        widths = [max(len(r[i]) for r in ([headers] + diffs)) for i in range(3)]
        if diffs:
            print()
            # header
            print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
            # print("  ".join("-" * w for w in widths))
            for r in diffs:
                print("  ".join(str(r[i]).ljust(widths[i]) for i in range(3)))


def cmd_stat(args) -> None:
    if args.terse:
        args.time_format = "unix"
    else:
        args.time_format = "human"

    for path in args.paths:
        abs_path = Path(path).resolve()
        folder_id, file_path = path2fid(args, abs_path)

        if folder_id is None:
            log.error("%s is not inside of a Syncthing folder", shlex.quote(str(abs_path)))
            continue
        if file_path is None:
            log.error("%s is not a valid _subpath_ of its Syncthing folder", shlex.quote(str(abs_path)))
            # TODO: stat of Syncthing folder root?
            continue

        file_data = args.st.file(folder_id, file_path.rstrip("/"))

        if not file_data:
            log.error("%s: No such file or directory", shlex.quote(path))
            continue

        print_stat(args, file_data, path)
        # Add blank line between multiple files (except in terse mode)
        if not args.terse and len(args.paths) > 1 and path != args.paths[-1]:
            print()
