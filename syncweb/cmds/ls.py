import shlex
from pathlib import Path

from syncweb import str_utils
from syncweb.log_utils import log
from syncweb.str_utils import format_time


def path2fid(args, abs_path):
    for folder in args.st.folders() or []:
        folder_path = Path(folder["path"]).resolve()
        try:
            prefix = abs_path.relative_to(folder_path)
            prefix = str(prefix) if prefix and str(prefix) != "." else None
            folder_id = folder["id"]
            return folder_id, prefix
        except ValueError:
            continue

    return None, None


def is_directory(item: dict) -> bool:
    return item.get("type") == "FILE_INFO_TYPE_DIRECTORY"


def folder_size(item: dict) -> int:
    if not is_directory(item) or "children" not in item:
        return item.get("size", 0)

    total = 0
    for child in item["children"]:
        total += folder_size(child)
    return total


def print_entry(item: dict, long: bool = False, human_readable: bool = False) -> None:
    name = item.get("name", "")

    is_dir = is_directory(item)
    # Add visual indicator for directories
    display_name = f"{name}/" if is_dir else name

    if long:
        type_char = "d" if is_dir else "-"
        size = folder_size(item) if is_dir else item.get("size", 0)
        size_str = str_utils.file_size(size) if human_readable else str(size)
        time_str = format_time(item.get("modTime", ""), long)

        print(f"{type_char:<4} {size_str:>10}  {time_str:>12}  {display_name}")
    else:
        print(display_name)


def calculate_depth(item: dict) -> int:
    if not is_directory(item) or "children" not in item or not item["children"]:
        return 0

    return 1 + max(calculate_depth(child) for child in item["children"])


def print_directory(args, items, current_level: int = 1, indent: int = 0) -> None:
    sorted_items = sorted(
        items,
        key=lambda x: (
            -calculate_depth(x),
            not is_directory(x),
            x.get("name", "").lower(),
        ),
    )

    for item in sorted_items:
        name = item.get("name", "")

        # skip hidden files unless show_all is True
        if not args.show_all and name.startswith("."):
            continue

        # print indentation when recursive listing
        if indent > 0:
            prefix = "  " * indent
            print(prefix, end="")

        print_entry(item, args.long, args.human_readable)

        should_recurse = is_directory(item) and "children" in item and (current_level < args.depth)
        if should_recurse:
            if indent == 0:
                print(f"\n\x1b[4m{name}\x1b[0m:")
            print_directory(args, item["children"], current_level + 1, indent + 1)
            if indent == 0:
                print()


def cmd_ls(args):
    args.folder_size = args.folder_size and args.long

    header_printed = not (args.long and not args.no_header)

    def print_header():
        nonlocal header_printed

        HEADER_FORMAT = "{:<4} {:>10}  {:>12}  {}"
        HEADER_LINE = HEADER_FORMAT.format("Type", "Size", "Modified", "Name")
        print(HEADER_LINE)
        print("-" * len(HEADER_LINE))
        header_printed = True

    for path in args.paths:
        abs_path = Path(path).resolve()
        folder_id, prefix = path2fid(args, abs_path)
        if folder_id is None:
            log.error("Error: %s is not inside of a Syncweb folder", shlex.quote(str(abs_path)))
            continue

        levels = None if args.folder_size else args.depth
        data = args.st.files(folder_id, levels=levels, prefix=prefix)
        log.debug("files: %s top-level data", len(data))

        if not data and prefix:  # must be a file or not exist
            file_data = args.st.file(folder_id, prefix)
            if file_data:
                item = file_data.get("global", file_data.get("local", {}))
                item["modTime"] = item["modified"]
                item["type"] = item.get("type", "FILE_INFO_TYPE_FILE")
                if item:
                    if not header_printed:
                        print_header()
                    print_entry(item, args.long, args.human_readable)
            continue

        if data and not header_printed:
            print_header()
        print_directory(args, data)
