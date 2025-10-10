#!/usr/bin/env python3

import argparse, os, sys
from pathlib import Path

from library.utils import argparse_utils

from syncweb import cmd_utils
from syncweb.cli import SubParser
from syncweb.log_utils import log
from syncweb.syncweb import Syncweb

__version__ = "0.0.1"


def cmd_version(args):
    print(f"Syncweb v{__version__}")
    print("Syncthing", args.st.version["version"])


def cmd_restart(args):
    print("Restarting Syncweb...")
    args.st.restart()


def cmd_shutdown(args):
    print("Shutting down Syncweb...")
    args.st.shutdown()


def cmd_accept(args):
    added = args.st.cmd_accept(args.device_ids)
    print("Added", added, "device" if added == 1 else "devices")


def cmd_init(args):
    added = args.st.cmd_init(args.paths)
    print("Added", added, "folder" if added == 1 else "folders")


def cmd_add(args):
    added_devices, added_folders = args.st.cmd_add(args.urls)
    print("Added", added_devices, "device" if added_devices == 1 else "devices")
    print("Added", added_folders, "folder" if added_folders == 1 else "folders")


def cli():
    parser = argparse.ArgumentParser(prog="syncweb", description="Syncweb: an offline-first distributed web")
    parser.add_argument("--home", type=Path, help="Base directory for syncweb metadata (default: platform-specific)")
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Control the level of logging verbosity; -v for info, -vv for debug",
    )
    parser.add_argument("--version", "-V", action="store_true")

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
    parser.add_argument(
        "--decode",
        help="Decode percent-encoding and punycode in URLs",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--simulate", "--dry-run", action="store_true")
    parser.add_argument("--no-confirm", "--yes", "-y", action="store_true")

    subparsers = SubParser(parser, default_command="help", version=__version__)
    subparsers.add_parser("help", help="Show this help message", func=lambda a: subparsers.print_help())
    subparsers.add_parser("version", help="Show Syncweb version", func=cmd_version)
    subparsers.add_parser("repl", help="Talk to Syncthing API", func=lambda a: (self := a.st) and breakpoint())

    subparsers.add_parser("shutdown", help="Shut down Syncweb", aliases=["stop", "quit"], func=cmd_shutdown)
    subparsers.add_parser("restart", help="Restart Syncweb", aliases=["start"], func=cmd_restart)

    fo_parser = subparsers.add_parser(
        "folders", aliases=["folder", "fo", "init", "in", "create"], help="Create a syncweb folder", func=cmd_init
    )
    fo_parser.add_argument("paths", nargs="*", default=".", help="Path to folder")

    de_parser = subparsers.add_parser(
        "devices", aliases=["device", "de", "accept"], help="Add a device to syncweb", func=cmd_accept
    )
    de_parser.add_argument(
        "device_ids",
        nargs="+",
        action=argparse_utils.ArgparseList,
        help="One or more Syncthing device IDs (space or comma-separated)",
    )

    add_parser = subparsers.add_parser(
        "add", aliases=["import", "join", "clone"], help="Import syncweb folders/devices", func=cmd_add
    )
    add_parser.add_argument(
        "urls",
        nargs="+",
        action=argparse_utils.ArgparseList,
        help="""URL format

        Add a device and folder
        syncweb://folder-id#device-id

        Add a device and folder and mark a subfolder or file for immediate download
        syncweb://folder-id/subfolder/file#device-id
""",
    )

    ls_parser = subparsers.add_parser("list", aliases=["ls"], help="List files at the current directory level")
    ls_parser.add_argument("paths", nargs="*", default=["."], help="Path relative to the root")

    subparsers.add_parser("cd", help="Change directory helper")

    dl_parser = subparsers.add_parser("download", aliases=["dl"], help="Mark files as unignored for download")
    dl_parser.add_argument("paths", nargs="+", help="Paths or globs of files to unignore")

    autodl_parser = subparsers.add_parser(
        "auto-download", aliases=["autodl"], help="Automatically unignore files based on size"
    )
    autodl_parser.add_argument("--min-size", type=int, default=0, help="Minimum file size (bytes)")
    autodl_parser.add_argument("--max-size", type=int, default=None, help="Maximum file size (bytes)")

    args = subparsers.parse()

    log.info("Syncweb v%s :: %s", __version__, os.path.realpath(sys.path[0]))
    if args.home is None:
        args.home = cmd_utils.default_state_dir("syncweb")
        log.debug("syncweb --home not set; using %s", args.home)

    args.st = Syncweb(name="syncweb", base_dir=args.home)
    args.st.start(daemonize=True)
    args.st.wait_for_pong()
    log.info("%s", args.st.version["longVersion"])
    log.info("API %s", args.st.api_url)
    log.info("DATA %s", args.st.home_path)

    return args.run()


if __name__ == "__main__":
    cli()
