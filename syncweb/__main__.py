#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse, os, sys
from pathlib import Path

from syncweb import cmd_utils
from syncweb.cli import STDIN_DASH, ArgparseArgsOrStdin, ArgparseList, SubParser
from syncweb.cmds.devices import cmd_list_devices
from syncweb.cmds.download import cmd_download
from syncweb.cmds.find import cmd_find
from syncweb.cmds.folders import cmd_list_folders
from syncweb.cmds.ls import cmd_ls
from syncweb.cmds.sort import cmd_sort
from syncweb.cmds.stat import cmd_stat
from syncweb.log_utils import log
from syncweb.syncweb import Syncweb

__version__ = "0.0.3"


def cmd_version(args):
    print(f"Syncweb v{__version__}")
    print("Syncthing", args.st.version["version"])


def cmd_restart(args):
    log.info("Restarting Syncweb...")
    args.st.restart()


def cmd_shutdown(args):
    log.info("Shutting down Syncweb...")
    args.st.shutdown()


def cmd_pause(args):
    if args.all:
        added = args.st.cmd_pause()
        log.info("Paused all devices")
    else:
        added = args.st.cmd_pause(args.device_ids)
        log.info("Paused", added, "device" if added == 1 else "devices")


def cmd_resume(args):
    if args.all:
        added = args.st.cmd_resume()
        log.info("Resumed all devices")
    else:
        added = args.st.cmd_resume(args.device_ids)
        log.info("Resumed", added, "device" if added == 1 else "devices")


def cmd_accept(args):
    added = args.st.cmd_accept(args.device_ids)
    log.info("Added", added, "device" if added == 1 else "devices")


def cmd_init(args):
    added = args.st.cmd_init(args.paths)
    log.info("Added", added, "folder" if added == 1 else "folders")


def cmd_join(args):
    added_devices, added_folders = args.st.cmd_add(args.urls)
    log.info("Added", added_devices, "device" if added_devices == 1 else "devices")
    log.info("Added", added_folders, "folder" if added_folders == 1 else "folders")
    print("Local Device ID:", args.st.device_id)


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
        "--decode",
        help="Decode percent-encoding and punycode in URLs",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--simulate", "--dry-run", action="store_true")
    parser.add_argument("--no-confirm", "--yes", "-y", action="store_true")

    subparsers = SubParser(parser, default_command="help", version=__version__)

    create = subparsers.add_parser(
        "create", aliases=["init", "in", "share"], help="Create a syncweb folder", func=cmd_init
    )
    create.add_argument("paths", nargs="*", default=".", help="Path to folder")

    join = subparsers.add_parser(
        "join", aliases=["import", "clone"], help="Join syncweb folders/devices", func=cmd_join
    )
    join.add_argument(
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

    accept = subparsers.add_parser("accept", aliases=["add"], help="Add a device to syncweb", func=cmd_accept)
    accept.add_argument(
        "device_ids",
        nargs="+",
        action=ArgparseList,
        help="One or more Syncthing device IDs (space or comma-separated)",
    )

    folders = subparsers.add_parser(
        "folders", aliases=["list-folders", "lsf"], help="List Syncthing folders", func=cmd_list_folders
    )
    devices = subparsers.add_parser(
        "devices", aliases=["list-devices", "lsd"], help="List Syncthing devices", func=cmd_list_devices
    )
    devices.add_argument(
        "--xfer", nargs="?", const=5, type=int, default=0, help="Wait to calculate transfer statistics"
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

    ls = subparsers.add_parser("ls", aliases=["list"], help="List files at the current directory level", func=cmd_ls)
    ls.add_argument("--long", "-l", action="store_true", help="use long listing format")
    ls.add_argument(
        "--human-readable",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="print sizes in human readable format",
    )
    ls.add_argument(
        "--folder-size", action=argparse.BooleanOptionalAction, default=True, help="Include accurate subfolder size"
    )
    ls.add_argument("--show-all", "--all", "-a", action="store_true", help="do not ignore entries starting with .")
    ls.add_argument(
        "--depth", "-D", "--levels", type=int, default=0, metavar="N", help="descend N directory levels deep"
    )
    ls.add_argument("--no-header", action="store_true", help="suppress header in long format")
    ls.add_argument("paths", nargs="*", default=["."], help="Path relative to the root")

    # subparsers.add_parser("cd", help="Change directory helper")

    find = subparsers.add_parser(
        "find", aliases=["fd", "search"], help="Search for files by filename, size, and modified date", func=cmd_find
    )
    find.add_argument("--ignore-case", "-i", action="store_true", help="Case insensitive search")
    find.add_argument("--case-sensitive", "-s", action="store_true", help="Case sensitive search")
    find.add_argument("--fixed-strings", "-F", action="store_true", help="Treat all patterns as literals")
    find.add_argument("--glob", "-g", action="store_true", help="Glob-based search")
    find.add_argument("--hidden", "-H", action="store_true", help="Search hidden files and directories")
    find.add_argument("--type", "-t", choices=["f", "d"], help="Filter by type: f=file, d=directory")
    find.add_argument("--follow-links", "-L", action="store_true", help="Follow symbolic links")
    find.add_argument("--absolute-path", "-a", action="store_true", help="Print absolute paths")
    find.add_argument(
        "--depth",
        "-d",
        "--levels",
        action="append",
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
    find.add_argument(
        "--ext",
        "--exts",
        "--extensions",
        "-e",
        default=[],
        action=ArgparseList,
        help="Include only specific file extensions",
    )
    find.add_argument("pattern", nargs="?", default=".*", help="Search patterns (default: all files)")
    find.add_argument("search_paths", nargs="*", help="Root directories to search")

    stat = subparsers.add_parser("stat", help="Display detailed file status information from Syncthing", func=cmd_stat)
    stat.add_argument("--terse", "-t", action="store_true", help="Print information in terse form")
    stat.add_argument(
        "--format",
        "-c",
        metavar="FORMAT",
        help="Use custom format (simplified: %%n=name, %%s=size, %%b=blocks, %%f=perms, %%F=type, %%y=mtime)",
    )
    stat.add_argument(
        "--dereference",
        "-L",
        action="store_true",
        help="Follow symbolic links (placeholder for compatibility; does nothing)",
    )
    stat.add_argument("paths", nargs="+", help="Files or directories to stat")

    sort = subparsers.add_parser("sort", help="Sort Syncthing files by multiple criteria", func=cmd_sort)
    sort.add_argument(
        "--sort",
        "--sort-by",
        "--by",
        "-u",
        default=[],
        action=ArgparseList,
        help="""Sort by popular, balanced, recent, size, frecency, or random.

Use '-' to negate, for example `--sort=-recent,-popular` means old and unpopular

(default: "balanced,frecency")""",
    )
    sort.add_argument("paths", nargs="*", default=STDIN_DASH, action=ArgparseArgsOrStdin, help="File paths to sort")

    download = subparsers.add_parser(
        "download",
        aliases=["dl", "upload", "unignore", "sync"],
        help="Mark file paths for download/sync",
        func=cmd_download,
    )
    download.add_argument("--depth", type=int, help="Maximum depth for directory traversal")
    download.add_argument(
        "paths",
        nargs="*",
        default=STDIN_DASH,
        action=ArgparseArgsOrStdin,
        help="File or directory paths to download (or read from stdin)",
    )

    subparsers.add_parser("shutdown", help="Shut down Syncweb", aliases=["stop", "quit"], func=cmd_shutdown)
    subparsers.add_parser("restart", help="Restart Syncweb", aliases=["start"], func=cmd_restart)

    subparsers.add_parser("repl", help="Talk to Syncthing API", func=lambda a: (self := a.st) and breakpoint())
    subparsers.add_parser("version", help="Show Syncweb version", func=cmd_version)
    subparsers.add_parser("help", help="Show this help message", func=lambda a: subparsers.print_help())

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

    if args.st.default_folder()["label"] != "Syncweb Default":
        args.st.set_default_folder()

    return args.run()


if __name__ == "__main__":
    cli()
