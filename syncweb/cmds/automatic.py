#!/usr/bin/env python3
import signal, subprocess, sys
from threading import Event

shutdown = Event()


def handle_signal(signum, frame):
    print(f"[syncweb-daemon] received signal {signum}, shutting down", file=sys.stderr)
    shutdown.set()


def run(cmd, *, stdin=None):
    if shutdown.is_set():
        return

    try:
        subprocess.run(cmd, input=stdin, text=True, check=False)
    except Exception as e:
        print(f"[syncweb-daemon] error running {cmd}: {e}", file=sys.stderr)


def get_download_paths():
    """
    Equivalent to: grep -Fv -f <(syncweb-blocklist.sh) <(syncweb-wishlist.sh)
    """
    try:
        blocklist = subprocess.run(
            ["syncweb-blocklist.sh"], text=True, capture_output=True, check=False
        ).stdout.splitlines()
        wishlist = subprocess.run(
            ["syncweb-wishlist.sh"], text=True, capture_output=True, check=False
        ).stdout.splitlines()

        block_set = set(blocklist)
        return [line for line in wishlist if line and line not in block_set]

    except Exception as e:
        print(f"[syncweb-daemon] wishlist error: {e}", file=sys.stderr)
        return []


def syncweb_automatic():
    SLEEP_ACCEPT = 5
    SLEEP_JOIN = 10

    while not shutdown.is_set():
        # Accept new local peers
        run(["syncweb", "devices", "--local-only", "--pending", "--accept"])
        if shutdown.wait(SLEEP_ACCEPT):
            break

        # Join pending folders from local devices
        run(["syncweb", "folders", "--local-only", "--pending", "--join"])
        if shutdown.wait(SLEEP_JOIN):
            break

        # Mark new downloads via wishlists
        paths = get_download_paths()
        if paths and not shutdown.is_set():
            run(["syncweb", "download", "--yes"], stdin="\n".join(paths) + "\n")


def cmd_automatic(args):
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    syncweb_automatic()
