#!/usr/bin/env python3
import argparse, signal, subprocess, sys
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
        blocklist = run(["syncweb-blocklist.sh"], capture_output=True).stdout.splitlines()  # type: ignore
        wishlist = run(["syncweb-wishlist.sh"], capture_output=True).stdout.splitlines()  # type: ignore

        block_set = set(blocklist)
        return [line for line in wishlist if line and line not in block_set]

    except Exception as e:
        print(f"[syncweb-daemon] wishlist error: {e}", file=sys.stderr)
        return []


def syncweb_automatic(args):
    SLEEP_ACCEPT = 5
    SLEEP_JOIN = 10

    while not shutdown.is_set():
        # 1. Devices
        devices_cmd = ["syncweb", "devices", "--pending", "--accept"]
        if not args.non_local:
            devices_cmd.append("--local-only")
        if args.folders_include:
            devices_cmd.extend(["--include", ",".join(args.folders_include)])
        if args.folders_exclude:
            devices_cmd.extend(["--exclude", ",".join(args.folders_exclude)])
        # Actions
        if args.devices:
            devices_cmd.append("--discovered")

        run(devices_cmd)
        if shutdown.wait(SLEEP_ACCEPT):
            break

        # 2. Folders
        folders_cmd = ["syncweb", "folders", "--pending", "--join"]
        if not args.non_local:
            folders_cmd.append("--local-only")
        if args.devices_include:
            devices_cmd.extend(["--include", ",".join(args.devices_include)])
        if args.devices_exclude:
            devices_cmd.extend(["--exclude", ",".join(args.devices_exclude)])
        # Actions
        if args.join_new_folders:
            folders_cmd.append("--discovered")
        if args.folders:
            folders_cmd.append("--introduce")

        run(folders_cmd)
        if shutdown.wait(SLEEP_JOIN):
            break

        # 3. Files
        # Mark new downloads via wishlists
        paths = get_download_paths()
        if paths:
            stdin = "\n".join(paths) + "\n"
            sorted_paths = run(["syncweb", "sort", "--sort", args.sort], stdin=stdin, capture_output=True)
            run(["syncweb", "download", "--yes"], stdin=sorted_paths.stdout)  # type: ignore


def cmd_automatic(args):
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    syncweb_automatic(args)


if __name__ == "__main__":
    cmd_automatic(
        argparse.Namespace(
            non_local=False,
            devices=False,
            folders=False,
            join_new_folders=False,
        )
    )
