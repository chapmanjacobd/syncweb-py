import fnmatch, os, re, shlex
from pathlib import Path
from typing import List

from syncweb import consts, log_utils
from syncweb.cmds.ls import folder_size, is_directory
from syncweb.log_utils import log
from syncweb.str_utils import human_to_bytes, human_to_seconds, isodate2seconds, parse_human_to_lambda, pipe_print


def parse_depth_constraints(depth_list: List[str], min_depth=0, max_depth=None) -> tuple[int, int | None]:
    for s in depth_list:
        match = re.match(r"([+-])?(\d+)", s)
        if match:
            sign, val_str = match.groups()
            val = int(val_str)

            if sign == "+":
                min_depth = max(min_depth, val)
            elif sign == "-":
                if max_depth is None:
                    max_depth = val
                else:
                    max_depth = min(max_depth, val)
            else:  # Exact depth
                min_depth = val
                max_depth = val

    return min_depth, max_depth


def split_pattern(pattern: str) -> List[str]:
    return shlex.split(pattern) if pattern else []


def regex_match(name: str, patterns: List[str], ignore_case: bool) -> bool:
    flags = re.IGNORECASE if ignore_case else 0

    for pattern in patterns:
        if pattern == ".*":
            continue  # Match-all pattern, skip

        try:
            if not re.search(pattern, name, flags):
                return False
        except re.error:  # invalid regex
            return False

    return True


def exact_match(name: str, patterns: List[str], ignore_case: bool) -> bool:
    search_name = name.lower() if ignore_case else name

    for pattern in patterns:
        search_pattern = pattern.lower() if ignore_case else pattern
        if search_pattern not in search_name:
            return False

    return True


def glob_match(name: str, patterns: List[str], ignore_case: bool) -> bool:
    try:
        for pattern in patterns:
            if ignore_case:
                if not fnmatch.fnmatchcase(name.lower(), pattern.lower()):
                    return False
            else:
                if not fnmatch.fnmatchcase(name, pattern):
                    return False
        return True
    except Exception as e:
        log.debug("glob failed, %s", e)
        return False


def matches_constraints(args, item: dict, current_depth: int, item_path: str = "") -> bool:
    name = item.get("name", "")
    is_dir = is_directory(item)

    # Use full path or just filename for pattern matching
    search_target = item_path if args.full_path else name

    if args.type:
        if args.type == "d" and not is_dir:
            return False
        if args.type == "f" and is_dir:
            return False

    if current_depth < args.min_depth:
        return False
    if args.max_depth is not None and current_depth > args.max_depth:
        return False

    if not args.hidden and name.startswith("."):
        return False
    if args.ext and not name.lower().endswith(args.ext):
        return False

    if args.sizes:
        if is_dir:
            file_size = folder_size(item)
        else:
            file_size = item.get("size", 0)

        if not args.sizes(file_size):
            return False

    if args.time_modified:
        mod_time = isodate2seconds(item["modTime"])
        if not args.time_modified(consts.APPLICATION_START - mod_time):
            return False

    if args.fixed_strings:
        if not exact_match(search_target, args.patterns, args.ignore_case):
            return False
    elif args.glob:
        if not glob_match(search_target, args.patterns, args.ignore_case):
            return False
    else:
        if not regex_match(search_target, args.patterns, args.ignore_case):
            return False

    return True


def find_files(args, items, current_path: str | None = "", current_depth: int = 0):
    for item in items:
        name = item.get("name", "")
        item_path = f"{current_path}/{name}" if current_path else name

        is_dir = is_directory(item)
        if matches_constraints(args, item, current_depth, item_path):
            if is_dir and log_utils.is_terminal:
                yield f"{item_path}/"
            else:
                yield item_path

        if (
            is_dir
            and "children" in item
            and item["children"]
            and (args.max_depth is None or current_depth < args.max_depth)
        ):
            yield from find_files(args, item["children"], item_path, current_depth + 1)


def path2fid_allow_outside(args, abs_path):
    # user_prefix: Path prefix to show to user (any path parts above Syncthing folder)
    for folder in args.st.folders() or []:
        if args.downloadable and folder["type"] == "sendonly":
            continue

        folder_path = Path(folder["path"]).resolve()

        try:
            rel_path = abs_path.relative_to(folder_path)
            # Path is inside Syncthing folder
            user_prefix = ""  # No prefix needed
            prefix = str(rel_path) if rel_path and str(rel_path) != "." else ""
            folder_id = folder["id"]
            yield folder_id, prefix, user_prefix
            break
        except ValueError:
            pass

        try:
            rel_path = folder_path.relative_to(abs_path)
            # Syncthing folder is inside the search path
            user_prefix = str(rel_path)  # relative path to Syncthing folder root
            prefix = ""  # Search API from root of Syncthing folder
            folder_id = folder["id"]
            yield folder_id, prefix, user_prefix
        except ValueError:
            continue


def cmd_find(args) -> None:
    args.ext = tuple(s.lower() for s in args.ext)

    args.min_depth, args.max_depth = parse_depth_constraints(args.depth, args.min_depth, args.max_depth)

    if args.sizes:
        args.sizes = parse_human_to_lambda(human_to_bytes, args.sizes)

    args.time_modified.extend(["-" + s.lstrip("-").lstrip("+") for s in args.modified_within])
    args.time_modified.extend(["+" + s.lstrip("+").lstrip("-") for s in args.modified_before])
    if args.time_modified:
        args.time_modified = parse_human_to_lambda(human_to_seconds, args.time_modified)

    args.patterns = split_pattern(args.pattern)

    if args.case_sensitive:
        args.ignore_case = False
    elif not args.ignore_case:
        # Default behavior: case-insensitive for lowercase patterns
        if re.search("[A-Za-z]", args.pattern):
            args.ignore_case = args.pattern.islower()
        else:
            args.ignore_case = True

    if "/" in args.pattern:
        log.warning(
            """The search pattern '%s' contains a path-separation character ('/') and will not lead to any search results.

If you want to search for all files inside the '%s' directory, use a match-all pattern:

  syncweb find . '%s'
""",
            args.pattern,
            args.pattern,
            args.pattern,
        )

    for path in args.search_paths or ["."]:
        abs_path = Path(path).resolve()
        for folder_id, prefix, user_prefix in path2fid_allow_outside(args, abs_path):
            if folder_id is None:
                continue

            data = args.st.files(folder_id, levels=args.max_depth, prefix=prefix)
            log.debug("files: %s top-level data", len(data))

            if user_prefix:
                prefix = os.path.join(user_prefix, prefix) if prefix else user_prefix

            for p in find_files(args, data, prefix, (prefix.count("/") + 0) if prefix else 0):
                if path != ".":
                    p = os.path.join(path, p)
                if args.absolute_path:
                    p = os.path.realpath(p)
                pipe_print(p)
        else:
            log.error("%s is not inside nor a parent of a Syncweb folder", shlex.quote(str(abs_path)))
