#!/usr/bin/env python3

import argparse
from pathlib import Path

from shlex import quote
from time import sleep

from library.utils import argparse_utils

from syncweb import cmd_utils
from syncweb.log_utils import log
from syncweb.syncthing import SyncthingNode

__version__ = "0.0.1"

def get_folder_id(args):
    if args.folder_id is None:
        try:
            args.folder_id = args.st.folder_id(args.folder)
        except FileNotFoundError:
            log.error("--folder-id not set and not inside of an Syncweb folder")
            raise SystemExit(3)
    return args.folder_id


def list_files(args):
    for path in args.paths:
        try:
            folder_id = args.st.folder_id(args.folder)
        except FileNotFoundError:
            log.error('"%s" is not inside of a Syncweb folder', quote(path))
            continue

        result = args.st("db/browse", folder=folder_id, prefix=path)
        files = result.get("files", [])
        dirs = result.get("directories", [])

        log.info(f"Listing under '{path}' (folder: {folder_id})")
        for d in dirs:
            log.info(f"[dir] {d}")
        for f in files:
            log.info(f"      {f}")


def mark_unignored(args):
    for path in args.paths:
        try:
            folder_id = args.st.folder_id(args.folder)
        except FileNotFoundError:
            log.error('"%s" is not inside of a Syncweb folder', quote(path))
            continue

        ignores = args.st.db_ignores(folder_id)
        new_ignores = [p for p in ignores if p not in args.paths]

        if new_ignores != ignores:
            args.st.set_ignores(new_ignores)
            log.info(f"Unignored {len(ignores) - len(new_ignores)} entries")
        else:
            log.info("No matching ignored files found.")


def auto_mark_unignored(args):
    result = args.st._get("db/browse", folder=args.st.folder_id, prefix="")
    files = result.get("files", [])

    eligible = [
        f
        for f in files
        if f.get("size", 0) >= args.min_size and (args.max_size is None or f.get("size", 0) <= args.max_size)
    ]

    log.info(f"Found {len(eligible)} files within size range.")
    if args.dry_run:
        for f in eligible[:50]:
            log.info(f"[dry-run] would unignore {f['name']}")
        return

    paths = [f["name"] for f in eligible]
    # mark_unignored(st, paths)


def main():
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

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("shutdown", aliases=["stop"], help="Shut down Syncweb")
    subparsers.add_parser("restart", aliases=["start"], help="Restart Syncweb")

    in_parser = subparsers.add_parser("init", aliases=["in", "create"], help="Create a syncweb folder")
    in_parser.add_argument("path", nargs="?", default=".", help="Path relative to the root")

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

    if args.home is None:
        args.home = cmd_utils.default_state_dir("syncweb")
        log.debug("syncweb --home not set; using %s", args.home)

    args.st = SyncthingNode(name="syncweb", base_dir=args.home)
    args.st.start(daemonize=False)  # TODO: change to True
    args.st.wait_for_pong()
    log.info("Using %s", args.st.api_url)

    # cd command (mkdir, cd)

    if args.command in ("list", "ls"):
        list_files(args)
    elif args.command in ("download", "dl"):
        mark_unignored(args)
    elif args.command in ("auto-download", "autodl"):
        auto_mark_unignored(args)
    elif args.command in ("shutdown",):
        args.st.shutdown()
    elif args.command in ("restart",):
        args.st.restart()
    elif args.command in ("init", "in", "create"):
        args.st.set_default_ignore()
        # TODO:


if __name__ == "__main__":
    main()
