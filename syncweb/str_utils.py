import base64, hashlib, os, re
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qsl, quote, unquote, urlparse, urlunparse

from idna import decode as puny_decode

from syncweb.log_utils import log


class FolderRef(NamedTuple):
    folder_id: str | None
    subpath: str | None
    device_id: str | None


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
