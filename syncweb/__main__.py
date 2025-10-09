#!/usr/bin/env python3

import argparse, os, sys
from pathlib import Path

from library.utils import argparse_utils

from syncweb import cmd_utils, str_utils
from syncweb.cli import SubParser
from syncweb.log_utils import log
from syncweb.syncthing import SyncthingNode

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

def cmd_add(args):
    args.st.set_default_ignore()

    for path in args.paths:
        ref = str_utils.parse_syncweb_path(path, decode=args.decode)

        if ref.device_id:
            args.st = SyncthingNode()
            args.st.add_device(deviceID=ref.device_id)
            devices = args.st.get_devices()
            raise

def cmd_init(args):
    args.st.set_default_ignore()

    # if :// in args.path
    # if folder exists
    # if file, add parent folder and unignore only the file?
    # hash args.path to create folder-id? or folder-id provided by Syncthing if not set?

    ref = str_utils.parse_syncweb_path(args.path, decode=args.decode)
    if ref.folder_id:
        args.st = SyncthingNode()
        args.st.add_folder(path=args.path, type="sendonly")
        raise

"""
        case "accept" | "add":
            # add device
            # add to autojoin folders
            # investigate autoaccept and introducer functions
            # args.st.add_device(args)
            pass

        case "list" | "ls":
            syncweb.list_files(args)
        case "download" | "dl":
            syncweb.mark_unignored(args)
        case "auto-download" | "autodl":
            syncweb.auto_mark_unignored(args)
        case _:
            log.error("Subcommand %s not found", args.command)
            hash_value = abs(hash(args.command))
            code = (hash_value % 254) + 1
            exit(code)

    magic wormhole like copy and move

"""


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
    parser.add_argument("--decode", help="Decode percent-encoding and punycode in URLs", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--simulate", "--dry-run", action="store_true")
    parser.add_argument("--no-confirm", "--yes", "-y", action="store_true")

    subparsers = SubParser(parser, default_command="help", version=__version__)
    subparsers.add_parser("help", help="Show this help message", func=lambda a: subparsers.print_help())
    subparsers.add_parser("version", help="Show Syncweb version", func=cmd_version)

    subparsers.add_parser("shutdown", help="Shut down Syncweb", aliases=["stop", "quit"], func=cmd_shutdown)
    subparsers.add_parser("restart", help="Restart Syncweb", aliases=["start"], func=cmd_restart)

    add_parser = subparsers.add_parser("add", aliases=["import", "clone"], help="Import syncweb folders/devices", func=cmd_add)
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

    in_parser = subparsers.add_parser("init", aliases=["in", "create"], help="Create a syncweb folder", func=cmd_init)
    in_parser.add_argument("path", nargs="?", default=".", help="Path to folder")

    de_parser = subparsers.add_parser("device", aliases=["share"], help="Add a device to syncweb")
    de_parser.add_argument(
        "device_ids",
        nargs="+",
        action=argparse_utils.ArgparseList,
        help="One or more Syncthing device IDs (space or comma-separated)",
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
    autodl_parser.add_argument("--dry-run", action="store_true", help="Show what would be unignored without applying")

    args = subparsers.parse()

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

    return args.run()


if __name__ == "__main__":
    cli()
