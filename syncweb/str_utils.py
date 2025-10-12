import base64, datetime, hashlib, os, re, sys
from contextlib import suppress
from datetime import timezone as tz
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import parse_qsl, quote, unquote, urlparse, urlunparse

import humanize
from idna import decode as puny_decode

from syncweb.consts import FolderRef
from syncweb.log_utils import log


def extract_device_id(value: str) -> str:
    value = value.strip()

    if "://" in value:
        parsed = urlparse(value)

        # Try fragment first (syncweb://host/#<device-id>)
        candidate = parsed.fragment or parsed.netloc
        candidate = candidate.strip("/")

        if not candidate:
            raise ValueError(f"No device ID found in URL: {value}")
    else:
        candidate = value

    # Allow dots or lowercase letters
    candidate = candidate.upper().replace(".", "-")
    compact = candidate.replace("-", "")

    # Validate characters
    if not re.fullmatch(r"[A-Z2-7]+", compact):
        raise ValueError(f"Invalid Syncthing device ID: contains illegal characters: {value}")

    # Validate length
    if len(compact) != 56:
        raise ValueError(f"Invalid Syncthing device ID length ({len(compact)}): must be 56 characters")

    # Return normalized grouped form
    return "-".join(compact[i : i + 7] for i in range(0, 56, 7))


def relativize(p: Path):
    if p.drive.endswith(":"):  # Windows Drives
        p = Path(p.drive.strip(":")) / p.relative_to(p.drive + "\\")
    elif p.drive.startswith("\\\\"):  # UNC paths
        server_share = p.parts[0]
        p = Path(server_share.lstrip("\\").replace("\\", os.sep)) / os.sep.join(p.parts[1:])

    if str(p).startswith("\\"):
        p = p.relative_to("\\")
    if str(p).startswith("/"):
        p = p.relative_to("/")
    return p


def repeat_until_same(fn):  # noqa: ANN201
    def wrapper(*args, **kwargs):
        p = args[0]
        while True:
            p1 = p
            p = fn(p, *args[1:], **kwargs)
            # print(fn.__name__, p)
            if p1 == p:
                break
        return p

    return wrapper


@repeat_until_same
def strip_mount_syntax(path):
    return str(relativize(Path(path)))


def ignore_traversal(user_path):
    if not user_path:
        return None

    user_path = os.path.normpath(user_path)
    user_paths = [s for s in user_path.split(os.sep) if s and s not in [os.curdir, os.pardir]]
    combined = os.sep.join(user_paths)
    combined = strip_mount_syntax(combined)

    if combined and combined.replace(".", "") == "":
        return None

    return combined


def selective_unquote(component, restricted_chars):
    try:
        unquoted = unquote(component, errors="strict")
    except UnicodeDecodeError:
        return component
    # re-quote restricted chars
    return "".join(quote(char, safe="") if char in restricted_chars else char for char in unquoted)


def unquote_query_params(query):
    query_pairs = parse_qsl(query, keep_blank_values=True)
    return "&".join(selective_unquote(key, "=&#") + "=" + selective_unquote(value, "=&#") for key, value in query_pairs)


def parse_syncweb_path(value: str, decode: bool = True) -> FolderRef:
    # TODO: port number in URL?

    value = value.strip()
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")

    # split at the last '#'; folder or subpath can technically contain '#'
    if "#" in value:
        folder_part, device_part = value.rsplit("#", 1)
        device_id = extract_device_id(device_part)
    else:
        try:
            device_id = extract_device_id(value)
            folder_part = device_id
        except ValueError:
            folder_part = value
            device_id = None

    # Handle optional URL scheme
    if "://" in folder_part:  # syncweb://folder_id
        up = urlparse(folder_part)
        # TODO: add file:// scheme?
        if up.scheme not in ("syncweb", "sync", "syncthing", "st", "web+sync"):
            log.warning("Unsupported scheme: %s", up.scheme)

        parts = folder_part[len(up.scheme + "://") :].lstrip("/").split("/", 1)
        folder_id = parts[0]
        subpath = parts[1] if len(parts) > 1 else None

        if decode:
            folder_id = selective_unquote(folder_id, "")
            with suppress(Exception):
                folder_id = puny_decode(folder_id)

            if subpath:
                subpath = selective_unquote(subpath, "")

                path = selective_unquote(up.path, ";?#")
                params = selective_unquote(up.params, "?#")
                query = unquote_query_params(up.query)
                fragment = selective_unquote(up.fragment, "")
                subpath2 = urlunparse(("", "", path, params, query, fragment))
                if subpath != subpath2:
                    log.debug("URL decode different:\n%s\n%s", subpath, subpath2)

    else:  # folder_id/subpath/file
        parts = folder_part.split("/", 1)
        folder_id = parts[0]
        subpath = parts[1] if len(parts) > 1 else None

    folder_id = ignore_traversal(folder_id)
    subpath = ignore_traversal(subpath)

    if folder_id is None:
        if device_id is None:
            msg = f"Nothing could be parsed from {value}"
            raise ValueError(msg)
        folder_id = device_id

    if subpath and folder_part.endswith("/"):
        subpath = f"{subpath}/"

    return FolderRef(folder_id=folder_id, subpath=subpath, device_id=device_id)


def path_hash(path_string: str) -> str:
    abs_path = os.path.abspath(path_string)

    hash_object = hashlib.sha1(abs_path.encode("utf-8"))
    hash_bytes = hash_object.digest()  # 20 bytes
    short_hash = base64.urlsafe_b64encode(hash_bytes).decode("utf-8").rstrip("=")
    return short_hash


def basename(path):
    """A basename() variant which first strips the trailing slash, if present.
    Thus we always get the last component of the path, even for directories.

    e.g.
    >>> os.path.basename('/bar/foo')
    'foo'
    >>> os.path.basename('/bar/foo/')
    ''
    """
    path = os.fspath(path)
    sep = os.path.sep + (os.path.altsep or "")
    return os.path.basename(path.rstrip(sep))


def file_size(n):
    return humanize.naturalsize(n, binary=True).replace(" ", "")


def safe_int(s) -> int | None:
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def safe_float(s) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def isodate2seconds(isodate):
    return int(datetime.datetime.fromisoformat(isodate.replace("Z", "+00:00")).timestamp())


def duration_short(seconds, format_str="%0.1f") -> str:
    seconds = safe_int(seconds)
    if not seconds:
        return ""

    try:
        if seconds < 60:
            return f"{int(seconds)} seconds"

        minutes = seconds / 60
        if minutes < 1.1:
            return "1 minute"
        elif minutes < 60:
            return f"{format_str % minutes} minutes"

        hours = minutes / 60
        if hours < 1.1:
            return "1 hour"
        elif hours < 24:
            return f"{format_str % hours} hours"

        days = hours / 24
        if days < 1.1:
            return "1 day"
        return f"{format_str % days} days"
    except OverflowError:
        return ""


def relative_datetime(seconds) -> str:
    seconds = safe_float(seconds)
    if not seconds:
        return ""

    try:
        dt = datetime.datetime.fromtimestamp(seconds, tz=tz.utc).astimezone()
    except (ValueError, OSError, OverflowError):
        return ""

    now = datetime.datetime.now(tz=tz.utc).astimezone()
    delta = now - dt
    if abs(delta.days) < 45:
        # Today
        if now.date() == dt.date():
            return dt.strftime("today, %H:%M")
        elif now < dt:
            # Tomorrow
            if now.date() == (dt - datetime.timedelta(days=1)).date():
                return dt.strftime("tomorrow, %H:%M")
            # In a few days
            return dt.strftime(f"in {abs(delta.days)} days, %H:%M")
        else:
            # Yesterday
            if now.date() == (dt + datetime.timedelta(days=1)).date():
                return dt.strftime("yesterday, %H:%M")
            # A few days ago
            return dt.strftime(f"{delta.days} days ago, %H:%M")

    return dt.strftime("%Y-%m-%d %H:%M")


def format_time(mod_time: str, long_format: bool = False) -> str:
    if not long_format:
        return ""

    try:
        dt = datetime.datetime.fromisoformat(mod_time.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if dt.year == now.year:
            # This year: show date + time in local time
            return dt.astimezone().strftime("%d %b %H:%M")
        else:
            # Older than this year (or future files!): show date + year
            return dt.astimezone().strftime("%d %b  %Y")
    except (ValueError, AttributeError):
        return mod_time[:16] + mod_time[-6:] if mod_time else ""


def human_to_seconds(input_str):
    if input_str is None:
        return None

    time_units = {
        "s": 1,
        "sec": 1,
        "second": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "h": 3600,
        "hr": 3600,
        "hour": 3600,
        "d": 86400,
        "day": 86400,
        "w": 604800,
        "week": 604800,
        "mo": 2592000,
        "mon": 2592000,
        "month": 2592000,
        "y": 31536000,
        "yr": 31536000,
        "year": 31536000,
    }

    input_str = input_str.strip().lower()

    value = re.findall(r"\d+\.?\d*", input_str)[0]
    unit = re.findall(r"[a-z]+", input_str, re.IGNORECASE)

    if unit:
        unit = unit[0]
        if unit != "s":
            unit = unit.rstrip("s")
    else:
        unit = "m"

    return int(float(value) * time_units[unit])


def human_to_bytes(input_str, binary=True) -> int:
    k = 1024 if binary else 1000
    byte_map = {"b": 1, "k": k, "m": k**2, "g": k**3, "t": k**4, "p": k**5}

    input_str = input_str.strip().lower()

    value = re.findall(r"\d+\.?\d*", input_str)[0]
    unit = re.findall(r"[a-z]+", input_str, re.IGNORECASE)

    unit = unit[0][0] if unit else "m"

    unit_multiplier = byte_map.get(unit, k**2)  # default to MB / MBit
    return int(float(value) * unit_multiplier)


def human_to_lambda_part(var, human_to_x, size):
    if var is None:
        var = 0

    if size.startswith(">"):
        return var > human_to_x(size.lstrip(">"))
    elif size.startswith("<"):
        return var < human_to_x(size.lstrip("<"))
    elif size.startswith("+"):
        return var > human_to_x(size.lstrip("+"))
    elif size.startswith("-"):
        return human_to_x(size.lstrip("-")) >= var
    elif "%" in size:
        size, percent = size.split("%")
        size = human_to_x(size)
        percent = float(percent)
        lower_bound = int(size - (size * (percent / 100)))
        upper_bound = int(size + (size * (percent / 100)))
        return lower_bound <= var and var <= upper_bound
    else:
        return var == human_to_x(size)


def parse_human_to_lambda(human_to_x, sizes):
    if not sizes:
        return lambda _var: True

    def check_all_sizes(var):
        return all(human_to_lambda_part(var, human_to_x, size) for size in sizes)

    return check_all_sizes


def pipe_print(*args, **kwargs) -> None:
    if "flush" not in kwargs:
        kwargs["flush"] = True

    try:
        print(*args, **kwargs)
    except BrokenPipeError:
        sys.stdout = None
        sys.exit(141)


def safe_len(list_):
    if not list_:
        return 0
    try:
        return len(list_)
    except Exception:
        return len(str(list_))


def flatten(xs: Iterable) -> Iterator:
    for x in xs:
        if isinstance(x, dict):
            yield x
        elif isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        elif isinstance(x, bytes):
            yield x.decode("utf-8")
        else:
            yield x
