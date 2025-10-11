#!/usr/bin/env python3

import argparse, os, sys
from pathlib import Path

from syncweb import cmd_utils
from syncweb.cli import ArgparseList, SubParser
from syncweb.find import cmd_find
from syncweb.log_utils import log
from syncweb.ls import cmd_ls
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


def cmd_pause(args):
    if args.all:
        added = args.st.cmd_pause()
        print("Paused all devices")
    else:
        added = args.st.cmd_pause(args.device_ids)
        print("Paused", added, "device" if added == 1 else "devices")


def cmd_resume(args):
    if args.all:
        added = args.st.cmd_resume()
        print("Resumed all devices")
    else:
        added = args.st.cmd_resume(args.device_ids)
        print("Resumed", added, "device" if added == 1 else "devices")


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
        action=ArgparseList,
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

    folders = subparsers.add_parser(
        "folders", aliases=["folder", "fo", "init", "in", "create"], help="Create a syncweb folder", func=cmd_init
    )
    folders.add_argument("paths", nargs="*", default=".", help="Path to folder")

    devices = subparsers.add_parser(
        "devices", aliases=["device", "de", "accept"], help="Add a device to syncweb", func=cmd_accept
    )
    devices.add_argument(
        "device_ids",
        nargs="+",
        action=ArgparseList,
        help="One or more Syncthing device IDs (space or comma-separated)",
    )

    syncweb_urls = subparsers.add_parser(
        "add", aliases=["import", "join", "clone"], help="Import syncweb folders/devices", func=cmd_add
    )
    syncweb_urls.add_argument(
        "urls",
        nargs="+",
        action=ArgparseList,
        help="""URL format

        Add a device and folder
        syncweb://folder-id#device-id

        Add a device and folder and mark a subfolder or file for immediate download
        syncweb://folder-id/subfolder/file#device-id
""",
    )

    pause = subparsers.add_parser("pause", help="Pause data transfer to a device in your syncweb", func=cmd_pause)
    pause.add_argument("--all", "-a", action="store_true", help="All devices")
    pause.add_argument(
        "device_ids",
        nargs="+",
        action=ArgparseList,
        help="One or more Syncthing device IDs (space or comma-separated)",
    )
    resume = subparsers.add_parser("resume", help="Resume data transfer to a device in your syncweb", func=cmd_resume)
    resume.add_argument("--all", "-a", action="store_true", help="All devices")
    resume.add_argument(
        "device_ids",
        nargs="+",
        action=ArgparseList,
        help="One or more Syncthing device IDs (space or comma-separated)",
    )

    ls = subparsers.add_parser("list", aliases=["ls"], help="List files at the current directory level", func=cmd_ls)
    ls.add_argument("--long", "-l", action="store_true", help="use long listing format")
    ls.add_argument(
        "--human-readable",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="print sizes in human readable format",
    )
    ls.add_argument("--show-all", "--all", "-a", action="store_true", help="do not ignore entries starting with .")
    ls.add_argument(
        "--depth", "-D", "--levels", type=int, default=0, metavar="N", help="descend N directory levels deep"
    )
    ls.add_argument("--recursive", "-R", action="store_true", help="list subdirectories recursively")
    ls.add_argument("--no-header", action="store_true", help="suppress header in long format")
    ls.add_argument("paths", nargs="*", default=["."], help="Path relative to the root")

    subparsers.add_parser("cd", help="Change directory helper")
    # TODO: add autocomplete via local metadata

    find = subparsers.add_parser(
        "find", aliases=["fd", "search"], help="Search for files by filename, size, and modified date", func=cmd_find
    )
    find.add_argument('--ignore-case', '-i', action='store_true', help='Case insensitive search')
    find.add_argument('--case-sensitive', '-s', action='store_true', help='Case sensitive search')
    find.add_argument('--hidden', '-H', action='store_true', help='Search hidden files and directories')
    find.add_argument('--type', '-t', choices=['f', 'd'], help='Filter by type: f=file, d=directory')
    find.add_argument('--follow-links', '-L', action='store_true', help='Follow symbolic links')
    find.add_argument('--absolute-path', '-a', action='store_true', help='Print absolute paths')
    find.add_argument(
        "--depth",
        "-d",
        "--levels",
        action='append',
        default=["+0"],
        metavar="N",
        help="""Constrain files by file depth
-d 2         # Show only items at depth 2
-d=+2        # Show items at depth 2 and deeper (min_depth=2)
-d=-2        # Show items up to depth 2 (max_depth=2)
-d=+1 -d=-3  # Show items from depth 1 to 3
""",
    )
    find.add_argument("--min-depth", type=int, default=0, metavar="N", help="Alternative depth notation")
    find.add_argument("--max-depth", type=int, default=None, metavar="N", help="Alternative depth notation")
    find.add_argument(
        "--sizes",
        "--size",
        "-S",
        action="append",
        help="""Constrain files by file size (uses the same syntax as fd-find)
-S 6           # 6 MB exactly (not likely)
-S-6           # less than 6 MB
-S+6           # more than 6 MB
-S 6%%10       # 6 MB ±10 percent (between 5 and 7 MB)
-S+5GB -S-7GB  # between 5 and 7 GB""",
    )
    find.add_argument(
        "--modified-within",
        "--changed-within",
        action="append",
        default=[],
        help="""Constrain files by time_modified (newer than)
--modified-within '3 days'""",
    )
    find.add_argument(
        "--modified-before",
        "--changed-before",
        action="append",
        default=[],
        help="""Constrain files by time_modified (older than)
--modified-before '3 years'""",
    )
    find.add_argument(
            "--time-modified",
            action="append",
            default=[],
            help="""Constrain media by time_modified (alternative syntax)
    --time-modified='-3 days' (newer than)
    --time-modified='+3 days' (older than)""",
    )
    find.add_argument('patterns', nargs='*', default=['.*'], help='Search patterns (default: all files)')
    find.add_argument('root_paths', nargs='*', default=['.'], help='Root directories to search')

    download = subparsers.add_parser("download", aliases=["dl"], help="Mark files as unignored for download")
    download.add_argument("paths", nargs="+", help="Paths or globs of files to unignore")

    autodownload = subparsers.add_parser(
        "auto-download", aliases=["autodl"], help="Automatically download files based on size"
    )
    autodownload.add_argument("--min-size", type=int, default=0, help="Minimum file size (bytes)")
    autodownload.add_argument("--max-size", type=int, default=None, help="Maximum file size (bytes)")

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
