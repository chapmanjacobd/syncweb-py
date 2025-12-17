#!/usr/bin/env python3
import signal, subprocess, sys
from threading import Event

shutdown = Event()


def handle_signal(signum, frame):
    print(f"[syncweb-daemon] received signal {signum}, shutting down", file=sys.stderr)
    shutdown.set()


def run(cmd, *, stdin=None, capture_output=False):
    if shutdown.is_set():
        return

    return subprocess.run(cmd, input=stdin, capture_output=capture_output, text=True, check=False)


def get_download_paths():
    """
    Equivalent to: grep -Fv -f <(syncweb-blocklist.sh) <(syncweb-wishlist.sh)
    """
    try:
        blocklist = run(["syncweb-blocklist.sh"], capture_output=True).stdout.splitlines()
        wishlist = run(["syncweb-wishlist.sh"], capture_output=True).stdout.splitlines()

        block_set = set(blocklist)
        return [line for line in wishlist if line and line not in block_set]

    except Exception as e:
        print(f"[syncweb-daemon] wishlist error: {e}", file=sys.stderr)
        return []


def syncweb_automatic():
    SLEEP_ACCEPT = 5
    SLEEP_JOIN = 10

    while not shutdown.is_set():
        # Accept new peer invitations from local devices
        # run(["syncweb", "devices", "--local-only", "--pending", "--accept"])

        # and optionally send out invitations to discovered peers
        run(["syncweb", "devices", "--local-only", "--pending", "--discovered", "--accept"])
        if shutdown.wait(SLEEP_ACCEPT):
            break

        # Join pending folders from local devices
        # run(["syncweb", "folders", "--local-only", "--pending", "--join"])

        # and optionally announce new folders to connected devices
        # run(["syncweb", "folders", "--local-only", "--pending", "--join", "--introduce"])

        # and optionally join new folder ids
        run(["syncweb", "folders", "--local-only", "--pending", "--discovered", "--join", "--introduce"])
        if shutdown.wait(SLEEP_JOIN):
            break

        # Mark new downloads via wishlists
        paths = get_download_paths()
        if paths:
            stdin = "\n".join(paths) + "\n"
            sorted_paths = run(["syncweb", "sort"], stdin=stdin, capture_output=True)

            run(["syncweb", "download", "--yes"], stdin=sorted_paths.stdout)


def cmd_automatic(args):
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    syncweb_automatic()
