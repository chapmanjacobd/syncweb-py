from pathlib import Path
import shlex
from syncweb import log_utils
from syncweb.log_utils import log
from syncweb import consts
from syncweb.ls import is_directory
from syncweb.str_utils import human_to_bytes, human_to_seconds, parse_human_to_lambda, pipe_print
import os
import re
from typing import List
import shlex
from pathlib import Path


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


def matches_pattern(name: str, pattern: str, ignore_case: bool) -> bool:
    if pattern == '.*':
        return True

    flags = re.IGNORECASE if ignore_case else 0

    try:
        if re.search(pattern, name, flags):
            return True
    except re.error:
        # If pattern is invalid regex, try literal match
        if ignore_case:
            if pattern.lower() in name.lower():
                return True
        else:
            if pattern in name:
                return True

    return False


def matches_constraints(args, item: dict, current_depth: int) -> bool:
    name = item.get('name', '')

    if not args.hidden and name.startswith('.'):
        return False

    if current_depth < args.min_depth:
        return False
    if args.max_depth is not None and current_depth > args.max_depth:
        return False

    if args.type:
        is_dir = is_directory(item)
        if args.type == 'd' and not is_dir:
            return False
        if args.type == 'f' and is_dir:
            return False

    if args.sizes:
        file_size = item.get('size', 0)
        if not args.sizes(file_size):
            return False

    if args.time_modified:
        mod_time = item.get('modTime', '')
        if not args.time_modified(consts.APPLICATION_START - mod_time):
            return False

    if not matches_pattern(name, args.pattern, args.ignore_case):
        return False

    return True


def find_files(args, items=None, current_path: str | None = "", current_depth: int = 0):
    if items is None:
        items = args.st.files()

    for item in items:
        name = item.get('name', '')
        item_path = f"{current_path}/{name}" if current_path else name

        is_dir = is_directory(item)
        if matches_constraints(args, item, current_depth):
            if is_dir and log_utils.is_terminal:
                yield f"{item_path}/"
            else:
                yield item_path

        if (
            is_dir
            and 'children' in item
            and item['children']
            and (args.max_depth is None or current_depth < args.max_depth)
        ):
            yield from find_files(args, item['children'], item_path, current_depth + 1)


def path2fid_allow_outside(args, abs_path):
    # user_prefix: Path prefix to show to user (any path parts above Syncthing folder)
    for folder in args.st.folders() or []:
        folder_path = Path(folder["path"]).resolve()

        try:
            rel_path = abs_path.relative_to(folder_path)
            # Path is inside Syncthing folder
            user_prefix = ""  # No prefix needed
            prefix = str(rel_path) if rel_path and str(rel_path) != "." else ""
            folder_id = folder["id"]
            return folder_id, prefix, user_prefix
        except ValueError:
            pass

        try:
            rel_path = folder_path.relative_to(abs_path)
            # Syncthing folder is inside the search path
            user_prefix = str(rel_path)  # relative path to Syncthing folder root
            prefix = ""  # Search API from root of Syncthing folder
            folder_id = folder["id"]
            return folder_id, prefix, user_prefix
        except ValueError:
            continue

    return None, "", ""


def cmd_find(args) -> None:
    args.min_depth, args.max_depth = parse_depth_constraints(args.depth, args.min_depth, args.max_depth)

    if args.sizes:
        args.sizes = parse_human_to_lambda(human_to_bytes, args.sizes)

    args.time_modified.extend(["-" + s.lstrip("-").lstrip("+") for s in args.modified_within])
    args.time_modified.extend(["+" + s.lstrip("+").lstrip("-") for s in args.modified_before])
    if args.time_modified:
        args.time_modified = parse_human_to_lambda(human_to_seconds, args.time_modified)

    if args.case_sensitive:
        args.ignore_case = False
    elif not args.ignore_case:
        # Default behavior: case-insensitive for lowercase patterns
        if re.search('[A-Za-z]', args.pattern):
            args.ignore_case = args.pattern.islower()
        else:
            args.ignore_case = True

    for path in args.search_paths or ["."]:
        abs_path = Path(path).resolve()
        folder_id, prefix, user_prefix = path2fid_allow_outside(args, abs_path)
        if folder_id is None:
            log.error("%s is not inside of a Syncweb folder", shlex.quote(str(abs_path)))
            continue

        data = args.st.files(folder_id, levels=args.max_depth, prefix=prefix)
        log.debug("files: %s top-level data", len(data))

        # TODO: or should it be PurePosixPath?
        if user_prefix:
            prefix = os.path.join(user_prefix, prefix) if prefix else user_prefix

        for path in find_files(args, data, prefix, (prefix.count("/") + 0) if prefix else 0):
            pipe_print(path)


"""

def _search_item(

    patterns: List[str],
    item: Dict[str, Any],
    base_path: str,
    current_depth: int
) -> Iterator[str]:
    item_path = os.path.join(base_path, item['name'])

    # Check if this item matches any pattern
    if _matches_any_pattern(patterns, item['name'], item_path):
        yield _format_path(item_path)

    # Recursively search children if it's a directory
    if item['type'] == 'FILE_INFO_TYPE_DIRECTORY' and 'children' in item:
        for child in item['children']:
            yield from _search_item(
                patterns, child, item_path, current_depth + 1
            )

def _should_process_item( item: Dict[str, Any], path: str, depth: int) -> bool:
    # Depth filtering
    if min_depth is not None and depth < min_depth:
        return False
    if max_depth is not None and depth > max_depth:
        return False

    # Hidden file filtering
    if not hidden and item['name'].startswith('.'):
        return False

    # Type filtering
    if type_filter == 'f' and item['type'] != 'FILE_INFO_TYPE_FILE':
        return False
    if type_filter == 'd' and item['type'] != 'FILE_INFO_TYPE_DIRECTORY':
        return False

    return True

def _matches_any_pattern( patterns: List[str], name: str, full_path: str) -> bool:
    for pattern in patterns:
        if _matches_pattern(pattern, name, full_path):
            return True
    return False

def _matches_pattern( pattern: str, name: str, full_path: str) -> bool:
    # Try glob matching first
    if _glob_match(pattern, name, full_path):
        return True

    # Try regex matching
    if _regex_match(pattern, name, full_path):
        return True

    # Simple substring matching as fallback
    if _substring_match(pattern, name, full_path):
        return True

    return False

def _glob_match( pattern: str, name: str, full_path: str) -> bool:
    try:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(full_path, pattern):
            return True
    except:
        pass
    return False

def _regex_match( pattern: str, name: str, full_path: str) -> bool:
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        if re.search(pattern, name, flags):
            return True
        if re.search(pattern, full_path, flags):
            return True
    except re.error:
        pass
    return False

def _substring_match( pattern: str, name: str, full_path: str) -> bool:
    if case_sensitive:
        return pattern in name or pattern in full_path
    else:
        return pattern.lower() in name.lower() or pattern.lower() in full_path.lower()

def _format_path( path: str) -> str:
    if absolute_path:
        return os.path.abspath(path)
    return path





def matches_pattern(pattern: str, name: str, full_path: str, case_sensitive: bool = False) -> bool:
    # Try glob matching first
    if glob_match(pattern, name, full_path, case_sensitive):
        return True

    # Try regex matching
    if regex_match(pattern, name, full_path, case_sensitive):
        return True

    # Simple substring matching as fallback
    if substring_match(pattern, name, full_path, case_sensitive):
        return True

    return False


def glob_match(pattern: str, name: str, full_path: str, case_sensitive: bool) -> bool:
    try:
        if not case_sensitive:
            pattern = pattern.lower()
            name_check = name.lower()
            path_check = full_path.lower()
        else:
            name_check = name
            path_check = full_path

        if fnmatch.fnmatch(name_check, pattern):
            return True
        if fnmatch.fnmatch(path_check, pattern):
            return True
    except Exception:
        pass
    return False


def regex_match(pattern: str, name: str, full_path: str, case_sensitive: bool) -> bool:
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        if re.search(pattern, name, flags):
            return True
        if re.search(pattern, full_path, flags):
            return True
    except re.error:
        pass
    return False


def substring_match(pattern: str, name: str, full_path: str, case_sensitive: bool) -> bool:
    if case_sensitive:
        return pattern in name or pattern in full_path
    else:
        pattern_lower = pattern.lower()
        return pattern_lower in name.lower() or pattern_lower in full_path.lower()


def format_path(path: str) -> str:
    global ABSOLUTE_PATHS
    if ABSOLUTE_PATHS:
        return os.path.abspath(path)
    return path


def search_item(patterns: List[str], item: Dict[str, Any], base_path: str, current_depth: int, case_sensitive: bool) -> Iterator[str]:
    item_path = os.path.join(base_path, item['name'])

    # Check if we should process this item
    if not should_process_item(item, item_path, current_depth):
        return

    # Check if this item matches any pattern
    if matches_any_pattern(patterns, item['name'], item_path, case_sensitive):
        yield format_path(item_path)

    # Recursively search children if it's a directory
    if item['type'] == 'FILE_INFO_TYPE_DIRECTORY' and 'children' in item:
        for child in item['children']:
            yield from search_item(patterns, child, item_path, current_depth + 1, case_sensitive)


def cmd_find(
    patterns: List[str],
    search_paths: List[str],
    syncthing_client,
    case_sensitive: bool = False,
    hidden: bool = False,
    type_filter: Optional[str] = None,
    max_depth: Optional[int] = None,
    min_depth: Optional[int] = None,
    follow_links: bool = False,
    absolute_path: bool = False,
    size_filters: Optional[List[str]] = None,
    modified_within: Optional[List[str]] = None,
    modified_before: Optional[List[str]] = None
) -> Iterator[str]:


    case_sensitive = args.case_sensitive
    if args.ignore_case:
        case_sensitive = False

    # Parse size filters
    SIZE_FILTERS = []
    if size_filters:
        for size_filter in size_filters:
            try:
                SIZE_FILTERS.append(parse_size_filter(size_filter))
            except Exception as e:
                print(f"Error parsing size filter '{size_filter}': {e}", file=sys.stderr)

    # Parse time filters
    MODIFIED_WITHIN = []
    if modified_within:
        for time_str in modified_within:
            try:
                MODIFIED_WITHIN.append(parse_time_filter(time_str))
            except Exception as e:
                print(f"Error parsing time filter '--modified-within {time_str}': {e}", file=sys.stderr)

    MODIFIED_BEFORE = []
    if modified_before:
        for time_str in modified_before:
            try:
                MODIFIED_BEFORE.append(parse_time_filter(time_str))
            except Exception as e:
                print(f"Error parsing time filter '--modified-before {time_str}': {e}", file=sys.stderr)

    for root_path in search_paths:
        yield from search_in_path(patterns, root_path, case_sensitive, syncthing_client)







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


"""
