#!/usr/bin/env python3

import argparse, os, sys
from pathlib import Path

from library.utils import argparse_utils

from syncweb import cmd_utils, syncweb
from syncweb.log_utils import log
from syncweb.syncthing import SyncthingNode

__version__ = "0.0.1"


def cli():
    parser = argparse.ArgumentParser(prog="syncweb", description="Syncweb: an offline-first distributed web")
    parser.add_argument(
        "--home", type=Path, default=None, help="Base directory for syncweb state (default: platform-specific)"
    )
    parser.add_argument(
        "--folder",
        "--cd",
        "-d",
        type=Path,
        default=Path.cwd(),
        help="Syncthing folder to work on (default: current working directory)",
    )
    parser.add_argument(
        "--folder-id", type=str, default=None, help="Syncthing folder-id to work on (default: resolved from --folder)"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="""Control the level of logging verbosity
-v     # info
-vv    # debug
-vvv   # debug, with SQL query printing
-vvvv  # debug, with external libraries logging""",
    )
    parser.add_argument("--no-pdb", action="store_true", help="Exit immediately on error. Never launch debugger")
    parser.add_argument(
        "--ext",
        "--exts",
        "--extensions",
        "-e",
        default=[],
        action=argparse_utils.ArgparseList,
        help="Include only specific file extensions",
    )
    parser.add_argument("--simulate", "--dry-run", action="store_true")
    parser.add_argument("--no-confirm", "--yes", "-y", action="store_true")
    parser.add_argument("--version", "-V", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", aliases=["v"], help="Print Syncweb version")
    subparsers.add_parser("shutdown", aliases=["stop", "quit"], help="Shut down Syncweb")
    subparsers.add_parser("restart", aliases=["start"], help="Restart Syncweb")

    add_parser = subparsers.add_parser("add", aliases=["import", "clone"], help="Import syncweb folders/devices")
    add_parser.add_argument(
        "paths",
        nargs="+",
        action=argparse_utils.ArgparseList,
        help="""URL format

        Add a device and folder
        syncweb://folder-id#device-id

        Add a device and folder and mark a subfolder or file for immediate download
        syncweb://folder-id/subfolder/file#device-id
""",
    )

    in_parser = subparsers.add_parser("init", aliases=["in", "create"], help="Create a syncweb folder")
    in_parser.add_argument("path", nargs="?", default=".", help="Path relative to the root")

    de_parser = subparsers.add_parser("device", aliases=["share"], help="Add a device to syncweb")
    de_parser.add_argument(
        "device_ids",
        nargs="+",
        action=argparse_utils.ArgparseList,
        help="One or more Syncthing device IDs (space or comma-separated)",
    )

    ls_parser = subparsers.add_parser("list", aliases=["ls"], help="List files at the current directory level")
    ls_parser.add_argument("paths", nargs="*", default=["."], help="Path relative to the root")

    dl_parser = subparsers.add_parser("download", aliases=["dl"], help="Mark files as unignored for download")
    dl_parser.add_argument("paths", nargs="+", help="Paths or globs of files to unignore")

    autodl_parser = subparsers.add_parser(
        "auto-download", aliases=["autodl"], help="Automatically unignore files based on size"
    )
    autodl_parser.add_argument("--min-size", type=int, default=0, help="Minimum file size (bytes)")
    autodl_parser.add_argument("--max-size", type=int, default=None, help="Maximum file size (bytes)")
    autodl_parser.add_argument("--dry-run", action="store_true", help="Show what would be unignored without applying")

    args = parser.parse_args()

    if args.version:
        print(__version__)
        exit(0)
    log.info("Syncweb v%s :: %s", __version__, os.path.realpath(sys.path[0]))

    if args.home is None:
        args.home = cmd_utils.default_state_dir("syncweb")
        log.debug("syncweb --home not set; using %s", args.home)

    args.st = SyncthingNode(name="syncweb", base_dir=args.home)
    args.st.start(daemonize=True)
    args.st.wait_for_pong()
    log.info("%s", args.st.version["longVersion"])
    log.info("API %s", args.st.api_url)
    log.info("DATA %s", args.st.home_path)

    # cd command (mkdir, cd)

    match args.command:
        case "version" | "v":
            print(f"Syncweb v{__version__}")
            print("Syncthing", args.st.version["version"])
        case "shutdown" | "stop" | "quit":
            args.st.shutdown()
        case "restart" | "start":
            args.st.restart()
        case "list" | "ls":
            syncweb.list_files(args)
        case "download" | "dl":
            syncweb.mark_unignored(args)
        case "auto-download" | "autodl":
            syncweb.auto_mark_unignored(args)
        case "init" | "in" | "create":
            args.st.set_default_ignore()
            # offer to add devices
        case "accept" | "add":
            # add device
            # add to autojoin folders
            # investigate autoaccept and introducer functions
            # args.st.add_device(args)
            pass
        case _:
            log.error("Subcommand %s not found", args.command)
            hash_value = abs(hash(args.command))
            code = (hash_value % 254) + 1
            exit(code)


if __name__ == "__main__":
    cli()
