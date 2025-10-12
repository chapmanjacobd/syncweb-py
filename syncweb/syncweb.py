import datetime, fnmatch, os
from pathlib import Path

import requests

from syncweb import str_utils
from syncweb.log_utils import log
from syncweb.syncthing import SyncthingNode


class Syncweb(SyncthingNode):
    def create_folder_id(self, path):
        existing_folders = set(self.folder_stats().keys())

        name = str_utils.basename(path)
        if name not in existing_folders:
            return name

        return str_utils.path_hash(path)

    def cmd_accept(self, device_ids):
        device_count = 0
        for path in device_ids:
            try:
                device_id = str_utils.extract_device_id(path)
                self.add_device(deviceID=device_id)
                device_count += 1
            except ValueError:
                log.error("Invalid Device ID %s", path)

        return device_count

    def cmd_pause(self, device_ids=None):
        if device_ids is None:
            return self.pause()

        device_count = 0
        for path in device_ids:
            try:
                device_id = str_utils.extract_device_id(path)
                self.pause(device_id)
                device_count += 1
            except ValueError:
                log.error("Invalid Device ID %s", path)

        return device_count

    def cmd_resume(self, device_ids=None):
        if device_ids is None:
            return self.resume()

        device_count = 0
        for path in device_ids:
            try:
                device_id = str_utils.extract_device_id(path)
                self.resume(device_id)
                device_count += 1
            except ValueError:
                log.error("Invalid Device ID %s", path)

        return device_count

    def cmd_add(self, urls, decode=True):
        device_count, folder_count = 0, 0
        for url in urls:
            ref = str_utils.parse_syncweb_path(url, decode=decode)
            if ref.device_id:
                self.add_device(deviceID=ref.device_id)
                device_count += 1

            if ref.folder_id:
                default_path = os.path.realpath(".")
                path = os.path.join(default_path, ref.folder_id)
                os.makedirs(path, exist_ok=True)

                folder_id = self.create_folder_id(path)
                if path not in self.folder_roots:
                    self.add_folder(id=folder_id, path=path, type="receiveonly")
                    self.set_ignores(folder_id)
                    folder_count += 1

                if ref.device_id:
                    self.join_folder(ref.folder_id, [ref.device_id])

                if ref.subpath:
                    # TODO: ask to confirm if ref.subpath == "/" ?
                    # or check size first?
                    self.add_ignores(folder_id, [ref.subpath])

            raise

        return device_count, folder_count

    def cmd_init(self, paths):
        folder_count = 0
        for path in paths:
            os.makedirs(path, exist_ok=True)

            folder_id = self.create_folder_id(path)
            self.add_folder(id=folder_id, path=path, type="sendonly")
            self.set_ignores(folder_id)
            folder_count += 1
        return folder_count

    def add_ignores(self, folder_id: str, exclusions: list[str]):
        existing = set(s for s in self.ignores(folder_id)["ignore"] if not s.startswith("// Syncweb-managed"))

        new = set()
        for p in exclusions:
            if p.startswith("//"):
                continue
            if not p.startswith("!/"):
                p = "!/" + p
            new.add(p)

        combined = new.union(existing)
        ordered = (
            ["// Syncweb-managed"]
            + sorted([p for p in combined if p.startswith("!")])
            + sorted([p for p in combined if not p.startswith("!") and p != "*"])
            + ["*"]
        )

        self.set_ignores(folder_id, lines=ordered)

    def device_short2long(self, short):
        matches = [d for d in self.devices_list if d.startswith(short)]
        if len(matches) == 1:
            dev_id = matches[0]
            return dev_id
        return None

    def device_long2name(self, long):
        short = long[:7]

        try:
            name = self.devices_dict[long].get("name")
            if not name or name.lower() in ("syncweb", "syncthing"):
                return short
            return f"{name} ({short})"
        except KeyError:
            return f"{short}-???????"

    def delete_device_peered_folders(self, device_id: str):
        folders = self._get("config/folders")
        if not folders:
            print(f"[{self.name}] No folders in config.")
            return

        target_folders = [f for f in folders if any(d["deviceID"] == device_id for d in f.get("devices", []))]
        if not target_folders:
            print(f"[{self.name}] No folders offered by or linked to {device_id}.")
            return
        for f in target_folders:
            fid = f["id"]
            print(f"[{self.name}] Deleting folder '{fid}' (linked to {device_id})...")
            try:
                self._delete(f"config/folders/{fid}")
            except requests.HTTPError as e:
                print(f"[{self.name}] Failed to delete folder '{fid}': {e}")

    def accept_pending_devices(self):
        pending = self._get("cluster/pending/devices")
        if not pending:
            log.info(f"[%s] No pending devices", self.name)
            return

        existing_devices = self._get("config/devices")
        existing_device_ids = {d["deviceID"] for d in existing_devices}

        for dev_id, info in pending.items():
            if dev_id in existing_device_ids:
                log.info(f"[%s] Device %s already exists!", self.name, dev_id)
                continue

            name = info.get("name", dev_id[:7])
            log.info(f"[%s] Accepting device %s (%s)", self.name, name, dev_id)
            cfg = {
                "deviceID": dev_id,
                "name": name,
                "addresses": info.get("addresses", []),
                "compression": "metadata",
                "introducer": False,
            }
            self._put(f"config/devices/{dev_id}", json=cfg)

    # TODO: break down more composable
    def accept_pending_folders(self, folder_id: str | None = None):
        pending = self._get("cluster/pending/folders")
        if not pending:
            log.info(f"[%s] No pending folders", self.name)
            return
        if folder_id:
            pending = [f for f in pending if f.get("id") == folder_id]
            if not pending:
                log.info(f"[%s] No pending folders matching '%s'", self.name, folder_id)
                return

        existing_folders = self._get("config/folders")
        existing_folder_ids = {f["id"]: f for f in existing_folders}
        pending = [f for f in pending if f.get("id") not in existing_folder_ids]

        for folder in pending:
            fid = folder["id"]
            offered_by = folder.get("offeredBy", {}) or {}
            device_ids = list(offered_by.keys())

            if not device_ids:
                log.info(f"[%s] No devices offering folder '%s'", self.name, fid)
                continue

            if fid in existing_folder_ids:  # folder exists; just add new devices
                self.join_folder(fid, device_ids)
            else:  # folder doesn't exist; create it (with devices)
                log.info(f"[%s] Creating folder '%s'", self.name, fid)
                cfg = {
                    "id": fid,
                    "label": fid,
                    "path": str(self.home_path / fid),
                    "type": "receiveonly",  # TODO: think
                    "devices": [{"deviceID": d} for d in device_ids],
                }
                self._post("config/folders", json=cfg)

    def join_folder(self, folder_id: str, device_ids: list[str]):
        existing_folder = self.folder(folder_id)

        existing_device_ids = {dd["deviceID"] for dd in existing_folder.get("devices", [])}
        new_devices = [{"deviceID": d} for d in device_ids if d not in existing_device_ids]
        if not new_devices:
            log.info(f"[%s] Folder '%s' already available to all requested devices", folder_id, self.name)
            return

        existing_folder["devices"].extend(new_devices)
        log.debug(f"[%s] Patching '%s' with %s new devices", folder_id, self.name, len(new_devices))
        self._patch(f"config/folders/{folder_id}", json=existing_folder)

    def _is_ignored(self, rel_path: Path, patterns: list[str]) -> bool:
        s = str(rel_path)
        for pat in patterns:
            if fnmatch.fnmatch(s, pat):
                return True
            if fnmatch.fnmatch(s + "/", pat):  # match directories
                return True
        return False

    def disk_usage(self) -> list[dict]:
        results = []
        for folder in self._get("config/folders"):
            folder_id = folder["id"]
            folder_path = Path(folder["path"])

            if not folder_path.exists():
                print(f"[{self.name}] Folder '{folder_id}' path not found: {folder_path}")
                continue

            ignore_patterns = self.ignores(folder_id)

            for dirpath, _dirnames, filenames in os.walk(folder_path):
                rel_dir = Path(dirpath).relative_to(folder_path)
                ignored = self._is_ignored(rel_dir, ignore_patterns)

                total_size = 0
                last_mod = 0

                for f in filenames:
                    fpath = Path(dirpath) / f
                    try:
                        stat = fpath.stat()
                    except FileNotFoundError:
                        continue
                    total_size += stat.st_size
                    last_mod = max(last_mod, stat.st_mtime)

                if total_size == 0 and not filenames:
                    continue  # skip empty dirs

                results.append(
                    {
                        "folder": folder_id,
                        "name": str(rel_dir) if rel_dir != Path(".") else ".",
                        "size": total_size,
                        "last_modified": last_mod,
                        "ignored": ignored,
                    }
                )

        return results

    def flatten_files(self, folder_id: str, prefix: str = "", levels: int | None = None):
        def _recurse(entries, path_prefix):
            flat = []
            for e in entries:
                name = e["name"]
                typ = e.get("type")
                full_path = f"{path_prefix}/{name}" if path_prefix else name
                if typ == "FILE_INFO_TYPE_FILE":
                    modtime = datetime.datetime.fromisoformat(e["modTime"])
                    flat.append({"path": full_path, "size": e["size"], "modTime": modtime})
                elif typ == "FILE_INFO_TYPE_DIRECTORY" and "children" in e:
                    flat.extend(_recurse(e["children"], full_path))
            return flat

        tree = self.files(folder_id, prefix=prefix, levels=levels)
        return _recurse(tree, prefix)

    def aggregate_directory(self, folder_id: str, prefix: str = "", levels: int | None = None):
        files = self.flatten_files(folder_id, prefix=prefix, levels=levels)
        if not files:
            return {"total_size": 0, "last_modified": None}

        total_size = sum(f["size"] for f in files)
        last_modified = max(f["modTime"] for f in files)
        return {"total_size": total_size, "last_modified": last_modified}

    def aggregate_files(self, files: list[dict]):
        if not files:
            return {"total_size": 0, "last_modified": None, "count": 0}

        total_size = sum(f["size"] for f in files)
        last_modified = max(f["modTime"] for f in files)
        count = len(files)
        return {"total_size": total_size, "last_modified": last_modified, "count": count}


'''

    def aggregate_ignored(self, folder_id: str):
        ignore_resp = self._get("db/ignores", params={"folder": folder_id})
        ignore_patterns = ignore_resp.get("ignore", [])
        all_files = self.flatten_files(folder_id)

        ignored_files = [
            f for f in all_files if any(fnmatch.fnmatch(f["path"], pattern) for pattern in ignore_patterns)
        ]
        return self.aggregate_files(ignored_files)

    def aggregate_non_ignored(self, folder_id: str):
        ignore_resp = self._get("db/ignores", params={"folder": folder_id})
        ignore_patterns = ignore_resp.get("ignore", [])
        all_files = self.flatten_files(folder_id)

        non_ignored_files = [
            f for f in all_files if not any(fnmatch.fnmatch(f["path"], pattern) for pattern in ignore_patterns)
        ]
        return self.aggregate_files(non_ignored_files)

    def folder_summary(self, folder_id: str, remote_devices: list[str] | None = None):
        summary = {}
        summary["all"] = self.aggregate_non_ignored(folder_id)
        summary["ignored"] = self.aggregate_ignored(folder_id)
        summary["need"] = self.aggregate_need(folder_id)
        summary["remote_need"] = {}
        if remote_devices:
            for dev_id in remote_devices:
                summary["remote_need"][dev_id] = self.aggregate_remote_need(folder_id, dev_id)

        return summary

    def print_folder_summary(self, folder_id: str, remote_devices: list[str] | None = None):
        summary = self.folder_summary(folder_id, remote_devices=remote_devices)
        all_files = self.flatten_files(folder_id)
        ignore_resp = self._get("db/ignores", params={"folder": folder_id})
        ignore_patterns = ignore_resp.get("ignore", [])

        def fmt_agg(agg):
            total_size_mb = agg["total_size"] / (1024 * 1024)
            last_modified = agg["last_modified"].isoformat() if agg["last_modified"] else "N/A"
            return f"{agg['count']:>6} files, {total_size_mb:>10.2f} MB, latest: {last_modified}"

        print(f"\nFolder Summary for '{folder_id}':")
        print("-" * 80)
        print(f"Non-ignored files     : {fmt_agg(summary['all'])}")
        print(f"Ignored files         : {fmt_agg(summary['ignored'])}")
        print(f"Files this node needs : {fmt_agg(summary['need'])}")

        if remote_devices:
            for dev_id in remote_devices:
                remote_agg = summary["remote_need"].get(dev_id, {"count": 0, "total_size": 0, "last_modified": None})
                print(f"\nFiles needed by {dev_id} (remote ignores applied): {fmt_agg(remote_agg)}")

                # Locally ignored files not needed by remote
                locally_ignored_not_needed = [
                    f for f in all_files if any(fnmatch.fnmatch(f["path"], p) for p in ignore_patterns)
                ]
                agg_ignored_remote = self.aggregate_files(locally_ignored_not_needed)
                print(f"Locally ignored files (not needed by {dev_id}): {fmt_agg(agg_ignored_remote)}")
        print("-" * 80)
        print("Notes:")
        print("  - remote_need is already filtered by the remote's ignore rules")
        print("  - locally ignored files are shown separately per remote for context")

    def folder_cluster_summary(self, folder_id: str, remote_devices: list[str]):
        summary = self.folder_summary(folder_id, remote_devices=remote_devices)
        cluster_summary = {
            "all": summary["all"],
            "ignored": summary["ignored"],
            "need": summary["need"],
            "remote_need": summary["remote_need"],
            "remote_need_total": None,
        }

        # Aggregate across all remotes
        total_size = 0
        last_modified = None
        count = 0
        for agg in summary["remote_need"].values():
            total_size += agg["total_size"]
            count += agg["count"]
            if last_modified is None or (agg["last_modified"] and agg["last_modified"] > last_modified):
                last_modified = agg["last_modified"]

        cluster_summary["remote_need_total"] = {
            "total_size": total_size,
            "last_modified": last_modified,
            "count": count,
        }
        return cluster_summary

    def print_folder_cluster_summary(self, folder_id: str, remote_devices: list[str]):
        summary = self.folder_cluster_summary(folder_id, remote_devices)

        def fmt_agg(agg):
            total_size_mb = agg["total_size"] / (1024 * 1024)
            last_modified = agg["last_modified"].isoformat() if agg["last_modified"] else "N/A"
            return f"{agg['count']:>6} files, {total_size_mb:>10.2f} MB, latest: {last_modified}"

        print(f"\nCluster-wide Folder Summary for '{folder_id}':")
        print("-" * 80)
        print(f"Non-ignored files       : {fmt_agg(summary['all'])}")
        print(f"Ignored files           : {fmt_agg(summary['ignored'])}")
        print(f"Files this node needs   : {fmt_agg(summary['need'])}")
        print(f"Files needed by cluster : {fmt_agg(summary['remote_need_total'])}")
        print("-" * 80)
        print("Per-remote breakdown:")
        for dev_id, agg in summary["remote_need"].items():
            print(f"  {dev_id}: {fmt_agg(agg)}")
        print("-" * 80)
        print("Note: remote ignores are already applied in remote_need")

    def set_folder_type(self, folder_id: str, new_type: str) -> None:
        new_type = ROLE_TO_TYPE.get(new_type, new_type)
        valid_types = {"sendreceive", "sendonly", "receiveonly"}
        if new_type not in valid_types:
            raise ValueError(f"Invalid folder type '{new_type}'. Must be one of {valid_types}.")

        folder_cfg = self._get("config/folders/{folder_id}")

        # Update the folder type
        folder_cfg["type"] = new_type

        # PUT replaces the existing folder configuration
        put_resp = self._put(f"config/folders/{folder_id}", json=folder_cfg)

        print(f"[{self.name}] Folder '{folder_id}' changed to type '{new_type}'.")

    @contextmanager
    def temporary_folder_role(self, folder_id: str, new_type: str):
        """Temporarily change a folder's type within a context."""
        old_cfg = self._get("config/folders/{folder_id}")
        old_type = old_cfg["type"]

        try:
            self.set_folder_type(folder_id, new_type)
            yield
        finally:
            self.set_folder_type(folder_id, old_type)

    def list_local_ignored_files(self, folder_id: str):
        if str(self.local).startswith("fake://"):
            raise ValueError("self.folder is None; cannot read fake stfolder.")

        folder_path = self.local / folder_id
        matcher = IgnoreMatcher(folder_path)

        # Ask Syncthing what files it sees (non-ignored)
        resp = self._get("db/browse", params={"folder": folder_id})
        visible = set(resp.get("files", []))

        ignored_files = []
        for path in folder_path.rglob("*"):
            if path.is_dir():
                continue
            rel = str(path.relative_to(folder_path))
            if rel in visible:
                continue
            if matcher.match(rel):
                ignored_files.append(rel)

        return {"folder": folder_id, "ignored": sorted(ignored_files)}

    def list_global_ignored_files(self, folder_id: str):
        if str(self.local).startswith("fake://"):
            raise ValueError("self.folder is None; cannot read fake stfolder.")

        folder_path = self.local / folder_id
        matcher = IgnoreMatcher(folder_path)

        # 1. Get all files visible locally via /db/browse
        resp = self._get("db/browse", params={"folder": folder_id})
        local_files = set(resp.get("files", []))

        # 2. Get all files known to the cluster via /rest/db/status
        # This endpoint contains remote files information, including ignored files
        resp = self._get("db/status", params={"folder": folder_id})
        global_files = {}
        for f in resp.get("globalFiles", []):
            global_files[f["name"]] = {
                "size": f.get("size", 0),
                "modified": f.get("modified", 0),
                "offeredBy": list(f.get("offeredBy", {}).keys()) if "offeredBy" in f else [],
            }

        # 3. Filter out local files and index
        ignored_global = []
        for f, f_stat in global_files.items():
            if f in local_files:
                continue
            if matcher.match(f):
                ignored_global.append({"path": f, **f_stat})

        return {"folder": folder_id, "ignored_global": sorted(ignored_global, key=lambda d: d["path"])}



def mark_unignored(args):
    for path in args.paths:
        try:
            folder_id = self.folder_id(args.folder)
        except FileNotFoundError:
            log.error('"%s" is not inside of a Syncweb folder', quote(path))
            continue

        ignores = self.db_ignores(folder_id)
        new_ignores = [p for p in ignores if p not in args.paths]

        if new_ignores != ignores:
            self.set_ignores(new_ignores)
            log.info(f"Unignored {len(ignores) - len(new_ignores)} entries")
        else:
            log.info("No matching ignored files found.")


def auto_mark_unignored(args):
    result = self._get("db/browse", folder=self.folder_id, prefix="")
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

'''
