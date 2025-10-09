from shlex import quote

from syncweb.log_utils import log


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
