#!/usr/bin/env python3
import random, shlex
from pathlib import Path

from syncweb import str_utils
from syncweb.cmds.ls import path2fid
from syncweb.consts import APPLICATION_START
from syncweb.log_utils import log
from syncweb.str_utils import pipe_print

# TODO: add support for sorting folders; aggregate (folder-size, median modTime, etc)


def make_sort_key(sort_modes):
    rand_map = {}  # stable random order per file

    def sort_key(file_data):
        availability = len(file_data.get("availability") or [])
        metadata = file_data.get("global", file_data.get("local", {}))
        size = metadata["size"]

        iso_str = metadata["modified"]
        mod_time = str_utils.isodate2seconds(iso_str)
        days = (APPLICATION_START - mod_time) / 86400.0

        key = []
        for mode in sort_modes:
            reverse = False
            if mode.startswith("-"):
                mode = mode[1:]
                reverse = True

            match mode:
                case "popular" | "popularity" | "peers" | "seeds":
                    value = availability
                case "recent" | "date":
                    value = -days
                case "old":
                    value = days
                case "size":
                    value = size
                case "balanced":
                    value = -abs(availability - 3)
                case "frecency":  # popular + recent
                    value = availability - (days / 3)
                case "random":
                    value = rand_map.setdefault(id(file_data), random.random())
                case _:
                    msg = f"mode {mode} not supported"
                    raise ValueError(msg)

            key.append(-value if reverse else value)

        return tuple(key)

    return sort_key


def cmd_sort(args) -> None:
    if not args.sort:
        args.sort = ["balanced", "frecency"]
    args.sort = [s.lower() for s in args.sort]

    data = []
    for path in args.paths:
        abs_path = Path(path).absolute()
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

        file_data["path"] = path
        data.append(file_data)

    data = sorted(data, key=make_sort_key(args.sort))
    for d in data:
        # print(make_sort_key(args.sort)(d), d["path"])
        pipe_print(d["path"])
