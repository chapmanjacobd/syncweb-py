#!/usr/bin/env python3
import os, random, shlex
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from syncweb import str_utils
from syncweb.cmds.find import parse_depth_constraints
from syncweb.cmds.ls import path2fid
from syncweb.consts import APPLICATION_START
from syncweb.log_utils import log
from syncweb.str_utils import human_to_bytes, pipe_print


def aggregate_folders(records, output_aggregates, min_depth=None, max_depth=None):
    agg_funcs = {
        "mean": mean,
        "median": median,
        "sum": sum,
        "min": min,
        "max": max,
        "count": lambda x: len(x),
    }

    # Parse aggregate specs like "size_mean"
    parsed = []
    for spec in output_aggregates:
        if "_" not in spec:
            raise ValueError(f"Invalid spec '{spec}', expected format 'field_agg'.")
        field, agg = spec.rsplit("_", 1)
        if agg not in agg_funcs:
            raise ValueError(f"Unknown aggregate '{agg}' in '{spec}'.")
        parsed.append((spec, field, agg))

    # Helper to compute grouping folders
    def grouping_keys(path):
        root = "/" if path.startswith("/") else ""

        if min_depth is None and max_depth is None:
            # classic: just the immediate parent folder
            parent = os.path.dirname(path).rstrip("/") or root
            return [parent]

        # split without empty first element
        parts = [p for p in path.split("/") if p]

        # extract folder levels only (exclude filename)
        if len(parts) > 1:
            folder_parts = parts[:-1]
        else:
            folder_parts = []

        keys = []
        for depth in range(min_depth or 0, (max_depth or len(folder_parts)) + 1):
            if depth <= len(folder_parts):
                # join first N folders
                folder = root + "/".join(folder_parts[:depth])
                keys.append(folder)
        return keys

    # grouped[group_folder][field] -> list of values
    grouped = defaultdict(lambda: defaultdict(list))
    for d in records:
        path = d.get("path")
        if path.startswith("."):
            path = os.path.normpath(path)
        if not path:
            continue

        for group_key in grouping_keys(path):
            for _, field, _ in parsed:
                value = d.get(field)
                if isinstance(value, (int, float)):
                    grouped[group_key][field].append(value)

    results = {}
    for folder, field_values in grouped.items():
        folder_result = {"file_count": len(field_values)}
        for full_key, field, agg in parsed:
            values = field_values.get(field, [])
            if values:
                func = agg_funcs[agg]
                folder_result[full_key] = func(values)
        if folder_result:
            results[folder] = folder_result

    return results


def make_sort_key(folder_aggregates, sort_modes):
    rand_map = {}  # stable random order per file

    def days(modified_time):
        return (APPLICATION_START - modified_time) / 86400.0

    def sort_key(file_data):
        folder_aggregate = folder_aggregates.get(os.path.dirname(file_data["path"].rstrip("/")))

        key = []
        for mode in sort_modes:
            reverse = False
            if mode.startswith("-"):
                mode = mode[1:]
                reverse = True

            value = None
            match mode:
                case "popular" | "popularity" | "peers" | "seeds":
                    value = file_data["num_peers"]
                case "recent" | "date":
                    value = -days(file_data["modified"])
                case "old":
                    value = days(file_data["modified"])
                case "time":
                    value = -file_data["modified"]
                case "size":
                    value = file_data["size"]
                case "balanced":
                    value = -abs(file_data["num_peers"] - 3)
                case "frecency":  # popular + recent
                    value = file_data["num_peers"] - (days(file_data["modified"]) / 3)
                case "random":
                    value = rand_map.setdefault(id(file_data), random.random())
                case "folder-size" | "foldersize":
                    value = folder_aggregate["size_sum"] if folder_aggregate else None
                case "folder-avg-size" | "folder-size-avg" | "foldersize-avg":
                    value = folder_aggregate["size_median"] if folder_aggregate else None
                case "folder-date" | "folderdate":
                    value = -days(folder_aggregate["modified_median"]) if folder_aggregate else None
                case "folder-time" | "foldertime":
                    value = -folder_aggregate["modified_median"] if folder_aggregate else None
                case "count" | "file-count":
                    value = folder_aggregate["file_count"] if folder_aggregate else None
                case _:
                    msg = f"mode {mode} not supported"
                    raise ValueError(msg)

            if value is None:
                key.append(float("inf") if reverse else -float("inf"))
            else:
                key.append(-value if reverse else value)

        return tuple(key)

    return sort_key


def cmd_sort(args) -> None:
    if not args.sort:
        args.sort = ["balanced", "frecency"]
    args.sort = [s.lower() for s in args.sort]

    args.limit_size = human_to_bytes(args.limit_size) if args.limit_size else None

    args.min_depth, args.max_depth = parse_depth_constraints(args.depth, args.min_depth, args.max_depth)

    data = []
    for path in args.paths:
        abs_path = Path(path).absolute()
        folder_id, file_path = path2fid(args, abs_path)

        if folder_id is None:
            log.error("%s is not inside of a Syncthing folder", shlex.quote(str(abs_path)))
            continue
        if file_path is None:
            log.error("%s is not a valid _subpath_ of its Syncthing folder %s", shlex.quote(str(abs_path)), folder_id)
            # TODO: stat of Syncthing folder root?
            continue

        file_data = args.st.file(folder_id, file_path.rstrip("/"))

        if not file_data:
            log.error("%s: No such file or directory", shlex.quote(path))
            continue

        file_data["num_peers"] = len(file_data.pop("availability", None) or [])
        if args.min_seeders and file_data["num_peers"] < args.min_seeders:
            continue
        if args.max_seeders is not None and args.max_seeders < file_data["num_peers"]:
            continue

        file_data_global = file_data.pop("global", None) or {}
        file_data_local = file_data.pop("local", None) or {}
        file_data = file_data | file_data_local | file_data_global
        file_data.pop("platform", None)
        file_data.pop("blocksHash", None)  # TODO: rolling hash? or only good for exact duplicates
        file_data.pop("noPermissions", None)
        file_data.pop("localFlags", None)
        file_data.pop("numBlocks", None)
        file_data.pop("version", None)
        file_data.pop("type", None)
        file_data.pop("name", None)
        file_data.pop("invalid", None)
        file_data.pop("inodeChange", None)

        # TODO: could be interesting to sort with:
        file_data.pop("modifiedBy", None)
        file_data.pop("sequence", None)
        file_data.pop("previousBlocksHash", None)
        file_data.pop("mustRescan", None)
        file_data.pop("ignored", None)
        file_data.pop("deleted", None)

        file_data["path"] = path
        file_data["modified"] = str_utils.isodate2seconds(file_data["modified"])
        data.append(file_data)

    folder_aggregates = aggregate_folders(
        data, ["modified_median", "size_median", "size_sum"], args.min_depth, args.max_depth
    )

    data = sorted(data, key=make_sort_key(folder_aggregates, args.sort))
    SIZE_USED = 0
    for d in data:
        if args.limit_size:
            file_size = d["size"]
            if SIZE_USED + file_size > args.limit_size:
                break
            SIZE_USED += file_size

        # print(make_sort_key(folder_aggregates, args.sort)(d), d["path"])
        pipe_print(d["path"])
