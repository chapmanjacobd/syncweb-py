import datetime, fnmatch, os, re, shutil, socket, subprocess, sys, tempfile, threading, time, urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterable, List, Optional

import requests
from library.utils import processes
from library.utils.log_utils import log

from config import ConfigXML


def find_free_port(start_port: int) -> int:
    port = start_port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1


rel_bin = "./syncthing"
if os.path.exists(rel_bin):
    default_bin = os.path.realpath(rel_bin)
else:
    default_bin = shutil.which("syncthing") or "syncthing"


class IgnorePattern:
    def __init__(self, pattern: str, ignored=True, casefold=False, deletable=False):
        self.pattern = pattern
        self.ignored = ignored
        self.casefold = casefold
        self.deletable = deletable

        # Convert Syncthing-style pattern to Python regex
        pat = pattern.lstrip("/")
        # escape, then restore wildcards
        pat = re.escape(pat)
        pat = pat.replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", ".")
        anchor = pattern.startswith("/")
        self.regex = re.compile(f"^{pat}$" if anchor else f"(^|.*/)({pat})$", re.IGNORECASE if casefold else 0)

    def match(self, relpath: str) -> bool:
        return bool(self.regex.search(relpath))


class IgnoreMatcher:
    # see interface in syncthing/lib/ignore/matcher.go

    def __init__(self, folder_path: Path):
        self.folder_path = Path(folder_path)
        self.patterns: List[IgnorePattern] = []
        self.load(self.folder_path / ".stignore")

    def load(self, file: Path):
        if not file.exists():
            return
        seen = set()
        for line in file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            if line in seen:
                continue
            seen.add(line)
            self.patterns.extend(self.parse_line(line))

    def parse_line(self, line: str) -> List[IgnorePattern]:
        ignored = True
        casefold = False
        deletable = False

        # parse prefixes
        while True:
            if line.startswith("!"):
                ignored = not ignored
                line = line[1:]
            elif line.startswith("(?i)"):
                casefold = True
                line = line[4:]
            elif line.startswith("(?d)"):
                deletable = True
                line = line[4:]
            else:
                break

        if not line:
            return []

        pats = []
        # rooted vs unrooted handling
        if line.startswith("/"):
            pats.append(IgnorePattern(line, ignored, casefold, deletable))
        else:
            # both direct and recursive match
            pats.append(IgnorePattern(line, ignored, casefold, deletable))
            pats.append(IgnorePattern("**/" + line, ignored, casefold, deletable))
        return pats

    def match(self, relpath: str) -> bool:
        relpath = relpath.replace("\\", "/")
        result = False
        for p in self.patterns:
            if p.match(relpath):
                result = p.ignored
        return result


class EventSource:
    def __init__(
        self,
        node: "SyncthingNode",
        event_types: Optional[Iterable[str]] = None,
        since: int = 0,
        start: Optional[datetime.datetime] = None,
        timeout: int = 60,
        limit: int = 0,
    ):
        self.node = node
        self.event_types = list(event_types or [])
        self.since = since
        self.start = start or datetime.datetime.now(datetime.timezone.utc)
        self.timeout = timeout
        self.limit = limit

    def fetch_once(self) -> list[dict]:
        params = {"since": str(self.since), "timeout": str(self.timeout)}
        if self.limit:
            params["limit"] = str(self.limit)
        if self.event_types:
            params["events"] = ",".join(self.event_types)

        try:
            resp = self.node.session.get(f"{self.node.api_url}/rest/events", params=params, timeout=self.timeout + 10)
        except requests.RequestException as e:
            log.warning("[%s] request failed: %s", self.node.name, e)
            return []

        if resp.status_code in (400, 404):
            # Syncthing probably restarted or dropped event buffer
            log.warning("[%s] Event buffer reset (status %s)", self.node.name, resp.status_code)
            self.since = 0
            return []

        resp.raise_for_status()
        events = resp.json()

        filtered = []
        for e in events:
            try:
                t = datetime.datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
            except Exception:
                continue
            if t >= self.start:
                filtered.append(e)
            self.since = max(self.since, e.get("id", self.since))
        return filtered

    def __iter__(self) -> Generator[dict, None, None]:
        last_id = self.since
        while True:
            events = self.fetch_once()
            for e in events:
                cur_id = e.get("id", 0)
                if last_id and cur_id > last_id + 1:
                    log.warning("[%s] Missed events: gap from %s → %s", self.node.name, last_id, cur_id)
                last_id = cur_id
                yield e


ROLE_TO_TYPE = {
    "r": "receiveonly",
    "w": "sendonly",
    "rw": "sendreceive",
}


class SyncthingNode:
    def __init__(self, name: str = "st-node", role: str = "sendreceive", bin: str = default_bin, base_dir=None):
        if base_dir is None:
            base_dir = tempfile.mkdtemp(prefix="syncthing-node-")
        self.home_path = Path(base_dir)
        self.config_path = self.home_path / "config.xml"

        processes.cmd(bin, f"--home={self.home_path}", "generate")

        self.config = ConfigXML(self.config_path)

        node = self.config["device"]
        # node["@id"] = "DWFH3CZ-6D3I5HE-6LPQAHE-YGO3KQY-PX36X4V-BZORCMN-PC2V7O5-WB3KIAR"
        node["@name"] = name  # will use hostname by default
        # node["@compression"] = "metadata"
        # node["@introducer"] = "false"
        # node["@skipIntroductionRemovals"] = "false"
        # node["@introducedBy"] = ""
        # node["address"] = "dynamic"
        # node["paused"] = "false"
        # node["autoAcceptFolders"] = "false"
        # node["maxSendKbps"] = "0"
        # node["maxRecvKbps"] = "0"
        # node["maxRequestKiB"] = "0"
        # node["untrusted"] = "false"
        # node["remoteGUIPort"] = "0"
        # node["numConnections"] = "0"

        # gui = self.config["gui"]
        # gui["@enabled"] = "true"
        # gui["@tls"] = "false"
        # gui["@sendBasicAuthPrompt"] = "false"
        # gui["address"] = "0.0.0.0:8384"
        # gui["metricsWithoutAuth"] = "false"
        # gui["apikey"] = "yQzanLVcNw2Rr2bQRH75Ncds3XStomR7"
        # gui["theme"] = "default"

        opts = self.config["options"]
        # opts["listenAddress"] = "default"  # will be randomly picked
        # opts["globalAnnounceServer"] = "default"
        opts["globalAnnounceEnabled"] = "false"  # just for test purposes
        # opts["localAnnounceEnabled"] = "true"
        # opts["localAnnouncePort"] = "21027"
        # opts["localAnnounceMCAddr"] = "[ff12::8384]:21027"
        # opts["maxSendKbps"] = "0"
        # opts["maxRecvKbps"] = "0"
        # opts["reconnectionIntervalS"] = "60"
        # opts["relaysEnabled"] = "true"
        # opts["relayReconnectIntervalM"] = "10"
        # opts["startBrowser"] = "true"
        # opts["natEnabled"] = "true"
        # opts["natLeaseMinutes"] = "60"
        # opts["natRenewalMinutes"] = "30"
        # opts["natTimeoutSeconds"] = "10"
        # disable Anonymous Usage Statistics
        opts["urAccepted"] = "-1"
        opts["urSeen"] = "3"
        # opts["urUniqueID"] = ""
        # opts["urURL"] = "https://data.syncthing.net/newdata"
        # opts["urPostInsecurely"] = "false"
        # opts["urInitialDelayS"] = "1800"
        # opts["autoUpgradeIntervalH"] = "12"
        # opts["upgradeToPreReleases"] = "false"
        # opts["keepTemporariesH"] = "24"
        # opts["cacheIgnoredFiles"] = "false"
        # opts["progressUpdateIntervalS"] = "5"
        # opts["limitBandwidthInLan"] = "false"
        # opts["minHomeDiskFree"] = {"@unit": "%", "#text": "1"}
        # opts["releasesURL"] = "https://upgrades.syncthing.net/meta.json"
        # opts["overwriteRemoteDeviceNamesOnConnect"] = "false"
        # opts["tempIndexMinBlocks"] = "10"
        # opts["unackedNotificationID"] = "authenticationUserAndPassword"
        # opts["trafficClass"] = "0"
        # opts["setLowPriority"] = "true"
        # opts["maxFolderConcurrency"] = "0"
        # opts["crashReportingURL"] = "https://crash.syncthing.net/newcrash"
        # opts["crashReportingEnabled"] = "true"
        # opts["stunKeepaliveStartS"] = "180"
        # opts["stunKeepaliveMinS"] = "20"
        # opts["stunServer"] = "default"
        # opts["maxConcurrentIncomingRequestKiB"] = "0"
        # opts["announceLANAddresses"] = "true"
        # opts["sendFullIndexOnUpgrade"] = "false"
        # opts["auditEnabled"] = "false"
        # opts["auditFile"] = ""
        # opts["connectionLimitEnough"] = "0"
        # opts["connectionLimitMax"] = "0"
        # opts["connectionPriorityTcpLan"] = "10"
        # opts["connectionPriorityQuicLan"] = "20"
        # opts["connectionPriorityTcpWan"] = "30"
        # opts["connectionPriorityQuicWan"] = "40"
        # opts["connectionPriorityRelay"] = "50"
        # opts["connectionPriorityUpgradeThreshold"] = "0"

        self.update_config()

        self.name = name
        self.role = role
        # TODO: relies on intial empty config; replace with REST API call for any non-temporary use
        self.device_id = str(self.config["device"]["@id"])
        self.bin = bin
        self.process: subprocess.Popen
        self.gui_port: int
        self.sync_port: int
        self.discovery_port: int
        self.local: Path

    def update_config(self):
        was_running = self.running
        if was_running:
            # stop nodes to be able to write configs
            self.stop()

        self.config.save()

        if was_running:
            self.start()

    @property
    def running(self):
        return getattr(self, "process", None) and self.process.poll() is None

    @property
    def api_key(self):
        return str(self.config["gui"]["apikey"])

    @property
    def api_url(self):
        return f"http://127.0.0.1:{self.gui_port}"

    @property
    def session(self):
        s = requests.Session()
        s.headers.update({"X-API-Key": self.api_key})
        return s

    def start(self):
        self.gui_port = find_free_port(8384)
        self.config["gui"]["address"] = f"127.0.0.1:{self.gui_port}"
        # self.sync_port = find_free_port(22000)
        # self.config["options"]["listenAddress"] = f"tcp://0.0.0.0:{self.sync_port}"
        self.update_config()

        self.process = subprocess.Popen(
            [self.bin, f"--home={self.home_path}", "--no-browser", "--no-upgrade", "--no-restart"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # Give Syncthing a moment
        time.sleep(0.5)

    def stop(self):
        if not getattr(self, "process", None):
            return

        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        else:
            print(self.name, "exited already")

        if self.process.stdout and not self.process.stdout.closed:
            self.log()

    def log(self):
        r = processes.Pclose(self.process)

        if r.returncode != 0:
            print(self.name, "exited", r.returncode)
        if r.stdout:
            print(r.stdout)
        if r.stderr:
            print(r.stderr, file=sys.stderr)

    def cleanup(self):
        self.stop()

    def wait_for_connection(self, timeout=60):
        deadline = time.time() + timeout

        assert self.process.poll() is None

        errors = []
        while time.time() < deadline:
            try:
                r = self.session.get(f"{self.api_url}/rest/system/connections")
                r.raise_for_status()
                data = r.json()
                for _dev, info in data.get("connections", {}).items():
                    if info.get("connected"):
                        return True
            except Exception as e:
                errors.append(e)
            time.sleep(2)

        print(f"Timed out waiting for {self.name} device to connect on", self.api_url, file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        raise TimeoutError

    def event_source(
        self,
        event_types: Iterable[str] | None = None,
        start: datetime.datetime | None = None,
        limit: int = 100,
    ) -> EventSource:
        return EventSource(self, event_types=event_types, start=start, limit=limit)

    def wait_for_event(self, event_type: str, timeout: float = 10.0) -> dict | None:
        start = time.monotonic()
        for evt in self.event_source([event_type]):
            if evt.get("type") == event_type:
                return evt
            if time.monotonic() - start > timeout:
                print(f"[{self.name}] Timed out waiting for {event_type}")
                return None

    def _get(self, path, **kwargs):
        resp = self.session.get(f"{self.api_url}/rest/{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, json=None, **kwargs):
        resp = self.session.post(f"{self.api_url}/rest/{path}", json=json, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def _put(self, path, **kwargs):
        resp = self.session.put(f"{self.api_url}/rest/{path}", **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def _patch(self, path, **kwargs):
        resp = self.session.patch(f"{self.api_url}/rest/{path}", **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def _delete(self, path, **kwargs):
        resp = self.session.delete(f"{self.api_url}/rest/{path}", **kwargs)
        if resp.status_code == 404:
            log.warning("404 Not Found %s", path)
        else:
            resp.raise_for_status()
        return resp

    def status(self, retries=5, delay=1):
        for _ in range(retries):
            try:
                status = self._get("system/status")
                return status
            except Exception:
                time.sleep(delay)
        raise RuntimeError("Failed to get status of Syncthing node")

    def get_device_id(self, retries=15, delay=0.5):  # TODO: dead code
        for _ in range(retries):
            try:
                status = self._get("system/status")
                return status["myID"]
            except Exception:
                time.sleep(delay)
        raise RuntimeError("Failed to get device ID from Syncthing node")

    def delete_device(self, device_id: str):
        print(f"[{self.name}] Deleting device '{device_id}'...")
        self._delete(f"config/devices/{device_id}")

    def delete_folder(self, folder_id: str):
        print(f"[{self.name}] Deleting folder '{folder_id}'...")
        self._delete(f"config/folders/{folder_id}")

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

    def folder_stats(self):
        return self._get("stats/folder")

    def device_stats(self):
        return self._get("stats/device")

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

            if fid in existing_folder_ids:
                # folder exists; just add new devices
                existing_folder = existing_folder_ids[fid]
                existing_device_ids = {dd["deviceID"] for dd in existing_folder.get("devices", [])}
                new_devices = [{"deviceID": d} for d in device_ids if d not in existing_device_ids]
                if not new_devices:
                    log.info(f"[%s] Folder '%s' already available to all known devices", self.name, fid)
                    continue

                existing_folder["devices"].extend(new_devices)
                log.info(f"[%s] Patching '%s' with %s new devices", self.name, fid, len(new_devices))
                self._patch(f"config/folders/{fid}", json=existing_folder)
            else:
                # folder doesn't exist; create it ?
                log.info(f"[%s] Creating folder '%s'", self.name, fid)
                cfg = {
                    "id": fid,
                    "label": fid,
                    "path": str(self.home_path / fid),
                    "type": "receiveonly",  # TODO: think
                    "devices": [{"deviceID": d} for d in device_ids],
                }
                self._post("config/folders", json=cfg)

    def db_status(self, folder_id: str):
        return self._get("db/status", params={"folder": folder_id})

    def db_local_changed(self, folder_id: str, page: int = 1, per_page: int = 0):
        params = {"folder": folder_id}
        if page > 0:
            params["page"] = str(page)
        if per_page > 0:
            params["perpage"] = str(per_page)
        return self._get("db/localchanged", params=params)

    def db_local_changed_all(self, folder_id: str):
        all_files = []
        page = 1
        per_page = 50

        while True:
            resp = self.db_local_changed(folder_id, page=page, per_page=per_page)
            batch = resp.get("progress", []) + resp.get("queued", []) + resp.get("rest", [])
            if not batch:
                break
            all_files.extend(batch)

            if len(batch) < per_page:
                break
            page += 1

        return all_files

    def folder_errors(self, folder_id: str, page: int = 1, per_page: int = 0):
        params = {"folder": folder_id}
        if page > 0:
            params["page"] = str(page)
        if per_page > 0:
            params["perpage"] = str(per_page)
        return self._get("folder/errors", params=params)

    def folder_errors_all(self, folder_id: str):
        all_errors = []
        page = 1
        per_page = 50

        while True:
            resp = self.folder_errors(folder_id, page=page, per_page=per_page)
            batch = resp.get("errors", [])
            if not batch:
                break
            all_errors.extend(batch)

            if len(batch) < per_page:
                break
            page += 1

        return all_errors

    def db_remote_need(self, folder_id: str, device_id: str, page: int = 1, per_page: int = 0):
        params = {"folder": folder_id, "device": device_id}
        if page > 0:
            params["page"] = str(page)
        if per_page > 0:
            params["perpage"] = str(per_page)
        return self._get("db/remoteneed", params=params)

    def db_need(self, folder_id: str, page: int = 1, per_page: int = 0):
        params = {"folder": folder_id}
        if page > 0:
            params["page"] = str(page)
        if per_page > 0:
            params["perpage"] = str(per_page)
        return self._get("db/need", params=params)

    def db_need_all(self, folder_id: str):
        all_files = []
        page = 1
        per_page = 50

        while True:
            resp = self.db_need(folder_id, page=page, per_page=per_page)
            # Combine progress + queued + rest
            batch = resp.get("progress", []) + resp.get("queued", []) + resp.get("rest", [])
            if not batch:
                break
            all_files.extend(batch)

            # Stop if fewer than per_page items were returned (last page)
            if len(batch) < per_page:
                break
            page += 1

        return all_files

    def db_remote_need_all(self, folder_id: str, device_id: str):
        all_files = []
        page = 1
        per_page = 50

        while True:
            resp = self.db_remote_need(folder_id, device_id, page=page, per_page=per_page)
            batch = resp.get("progress", []) + resp.get("queued", []) + resp.get("rest", [])
            if not batch:
                break
            all_files.extend(batch)

            if len(batch) < per_page:
                break
            page += 1

        return all_files

    def system_errors(self):
        return self._get("system/error")

    def db_ignores(self, folder_id: str):
        return self._get("db/ignores", params={"folder": folder_id})

    def db_set_ignores(self, folder_id: str, ignore_lines: list[str] | None = None):
        if ignore_lines is None:
            ignore_lines = ["*"]
        return self._post("db/ignores", params={"folder": folder_id}, json={"ignore": ignore_lines})

    def db_set_default_ignore(self, folder_id: str, ignore_lines: list[str] | None = None):
        if ignore_lines is None:
            ignore_lines = ["*"]
        return self._put("config/defaults/ignores", params={"folder": folder_id}, json={"ignore": ignore_lines})

    def _read_stignore(self, folder_path: Path) -> list[str]:
        ignore_file = folder_path / ".stignore"
        if not ignore_file.exists():
            return []
        patterns = []
        with ignore_file.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
        return patterns

    def _is_ignored(self, rel_path: Path, patterns: list[str]) -> bool:
        s = str(rel_path)
        for pat in patterns:
            if fnmatch.fnmatch(s, pat):
                return True
            if fnmatch.fnmatch(s + "/", pat):  # match directories
                return True
        return False

    def ignore_all_files(self, folder_id: str, exceptions: list[str] | None = None):
        if str(self.local).startswith("fake?"):
            raise ValueError("self.folder is None; cannot construct .stignore path.")

        stignore_path = self.local / folder_id / ".stignore"
        stignore_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing lines, strip comments and blanks
        existing = set()
        if stignore_path.exists():
            with open(stignore_path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#"):
                        existing.add(s)

        # Always include "*" (ignore everything)
        patterns = {"*"}
        if exceptions:
            for p in exceptions:
                if not p.startswith("!"):
                    p = "!" + p
                patterns.add(p)

        # Merge with existing
        combined = patterns.union(existing)

        # Preserve order: * first, then exceptions (!), then other patterns (if any)
        ordered = (
            ["# Ignore everything by default", "*"]
            + sorted([p for p in combined if p.startswith("!")])
            + sorted([p for p in combined if not p.startswith("!") and p != "*"])
        )

        # Write to a temp file first
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as temp:
            temp.write("\n".join(ordered) + "\n")
            temp.flush()
            os.fsync(temp.fileno())
        shutil.move(temp.name, stignore_path)
        print(f"[{self.name}] Updated .stignore at {stignore_path}")

    def start_error_monitor(self, poll_interval: float = 1.0):
        def monitor():
            seen_errors = set()
            while getattr(self, "_monitoring_errors", True):
                errors = self.system_errors() or []
                for e in errors:
                    eid = e.get("id")
                    if eid not in seen_errors:
                        seen_errors.add(eid)
                        print(f"[{self.name}] Error: {e}")
                time.sleep(poll_interval)

        self._monitoring_errors = True
        t = threading.Thread(target=monitor, daemon=True)
        t.start()
        self._error_monitor_thread = t

    def stop_error_monitor(self):
        self._monitoring_errors = False
        if hasattr(self, "_error_monitor_thread"):
            self._error_monitor_thread.join()

    def get_config(self):
        return self._get("config")

    def replace_config(self, config: dict):
        return self._put("config", json=config)

    def revert_folder(self, receiveonly_folder_id: str):
        print(f"[%s] Reverting folder '%s' (receive-only)...", self.name, receiveonly_folder_id)
        resp = self._post("db/revert", json={"folder": receiveonly_folder_id})
        return resp

    def override_folder(self, sendonly_folder_id: str):
        print("[%s] Overriding folder '%s' (send-only)...", self.name, sendonly_folder_id)
        resp = self._post("db/override", json={"folder": sendonly_folder_id})
        return resp

    def db_prio(self, folder_id: str, file_path: str):
        print(f"[{self.name}] Moving file '{file_path}' to top of download queue in folder '{folder_id}'")
        self._post(f"db/prio", params={"folder": folder_id, "file": file_path})

    def db_reset(self, folder_id: str | None = None):
        params = {}
        if folder_id:
            params["folder"] = folder_id

        print(f"[{self.name}] Resetting {'folder '+folder_id if folder_id else 'entire database'}")
        self._post("system/reset", params=params)

    def pause(self, device_id: str | None = None):
        params = {}
        if device_id:
            params["device"] = device_id

        print(f"[{self.name}] Pausing {'device '+device_id if device_id else 'all devices'}")
        self._post("system/pause", params=params)

    def resume(self, device_id: str | None = None):
        params = {}
        if device_id:
            params["device"] = device_id

        print(f"[{self.name}] Resuming {'device '+device_id if device_id else 'all devices'}")
        self._post("system/resume", params=params)

    def db_file(self, folder_id: str, relative_path: str):
        params = {"folder": folder_id, "file": urllib.parse.quote(relative_path, safe="")}

        resp = self.session.get(f"{self.api_url}/rest/db/file", params=params)
        if resp.status_code == 404:
            log.warning("404 Not Found %s", relative_path)
        else:
            resp.raise_for_status()
        return resp

    def db_browse(self, folder_id: str, levels: int | None = None, prefix: str | None = None):
        params = {"folder": folder_id}
        if levels is not None:
            params["levels"] = str(levels)
        if prefix is not None:
            params["prefix"] = prefix

        return self._get("db/browse", params=params)

    def browse(self, current: str | None = None):
        params = {}
        if current is not None:
            params["current"] = current
        return self._get("system/browse", params=params)

    def disk_usage(self) -> list[dict]:
        results = []
        for folder in self._get("config/folders"):
            folder_id = folder["id"]
            folder_path = Path(folder["path"])

            if not folder_path.exists():
                print(f"[{self.name}] Folder '{folder_id}' path not found: {folder_path}")
                continue

            ignore_patterns = self._read_stignore(folder_path)

            for dirpath, dirnames, filenames in os.walk(folder_path):
                rel_dir = Path(dirpath).relative_to(folder_path)
                ignored = self._is_ignored(rel_dir, ignore_patterns)

                total_size = 0
                last_mod = 0

                for f in filenames:
                    fpath = Path(dirpath) / f
                    try:
                        st = fpath.stat()
                    except FileNotFoundError:
                        continue
                    total_size += st.st_size
                    last_mod = max(last_mod, st.st_mtime)

                if total_size == 0 and not filenames:
                    continue  # skip empty dirs

                results.append(
                    {
                        "folder": folder_id,
                        "name": str(rel_dir) if rel_dir != Path(".") else ".",
                        "size": total_size,
                        "last_modified": datetime.datetime.fromtimestamp(last_mod),
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

        tree = self.db_browse(folder_id, prefix=prefix, levels=levels)
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

    def aggregate_need(self, folder_id: str):
        files_needed = self.db_need_all(folder_id)
        files = [
            {"size": f.get("size", 0), "modTime": datetime.datetime.fromisoformat(f["modTime"])} for f in files_needed
        ]
        return self.aggregate_files(files)

    def aggregate_remote_need(self, folder_id: str, device_id: str):
        files_needed = self.db_remote_need_all(folder_id, device_id)
        files = [
            {"size": f.get("size", 0), "modTime": datetime.datetime.fromisoformat(f["modTime"])} for f in files_needed
        ]
        return self.aggregate_files(files)

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

        resp = self.session.get(f"{self.api_url}/rest/config/folders/{folder_id}")
        resp.raise_for_status()
        folder_cfg = resp.json()

        # Update the folder type
        folder_cfg["type"] = new_type

        # PUT replaces the existing folder configuration
        put_resp = self.session.put(f"{self.api_url}/rest/config/folders/{folder_id}", json=folder_cfg)
        put_resp.raise_for_status()

        # Reload config (optional, ensures it applies immediately)
        reload_resp = self.session.post(f"{self.api_url}/rest/system/config/reload")
        reload_resp.raise_for_status()

        print(f"[{self.name}] Folder '{folder_id}' changed to type '{new_type}'.")

    @contextmanager
    def temporary_folder_role(self, folder_id: str, new_type: str):
        """Temporarily change a folder's type within a context."""
        resp = self.session.get(f"{self.api_url}/rest/config/folders/{folder_id}")
        resp.raise_for_status()
        old_cfg = resp.json()
        old_type = old_cfg["type"]

        try:
            self.set_folder_type(folder_id, new_type)
            yield
        finally:
            self.set_folder_type(folder_id, old_type)

    def list_local_ignored_files(self, folder_id: str):
        if str(self.local).startswith("fake?"):
            raise ValueError("self.folder is None; cannot read fake stfolder.")

        folder_path = self.local / folder_id
        matcher = IgnoreMatcher(folder_path)

        # Ask Syncthing what files it sees (non-ignored)
        resp = self.session.get(f"{self.api_url}/rest/db/browse", params={"folder": folder_id})
        resp.raise_for_status()
        visible = set(resp.json().get("files", []))

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
        if str(self.local).startswith("fake?"):
            raise ValueError("self.folder is None; cannot read fake stfolder.")

        folder_path = self.local / folder_id
        matcher = IgnoreMatcher(folder_path)

        # 1. Get all files visible locally via /db/browse
        resp = self.session.get(f"{self.api_url}/rest/db/browse", params={"folder": folder_id})
        resp.raise_for_status()
        local_files = set(resp.json().get("files", []))

        # 2. Get all files known to the cluster via /rest/db/status
        # This endpoint contains remote files information, including ignored files
        resp = self.session.get(f"{self.api_url}/rest/db/status", params={"folder": folder_id})
        resp.raise_for_status()
        global_files = {}
        for f in resp.json().get("globalFiles", []):
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

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cleanup()


class SyncthingCluster:
    def __init__(self, roles, prefix="syncthing-cluster-"):
        self.roles = roles
        self.tmpdir = Path(tempfile.mkdtemp(prefix=prefix))
        self.nodes: list[SyncthingNode] = []
        for i, role in enumerate(self.roles):
            home = self.tmpdir / f"node{i}"
            home.mkdir(parents=True, exist_ok=True)
            st = SyncthingNode(name=f"node{i}", role=role, base_dir=home)
            self.nodes.append(st)

    @property
    def device_ids(self):
        return [st.device_id for st in self.nodes]

    def setup_peers(self):
        for st in self.nodes:
            for j, peer_id in enumerate(self.device_ids):
                device = st.config.append(
                    "device",
                    attrib={
                        "id": peer_id,
                        "name": f"node{j}",
                        "compression": "metadata",
                        "introducer": "false",
                        "skipIntroductionRemovals": "false",
                        "introducedBy": "",
                    },
                )
                device["address"] = "dynamic"
                # device["address"] = "http://localhost:22000"
                device["paused"] = "false"
                device["autoAcceptFolders"] = "false"
                device["maxSendKbps"] = "0"
                device["maxRecvKbps"] = "0"
                device["maxRequestKiB"] = "0"
                device["untrusted"] = "false"
                device["remoteGUIPort"] = "0"
                device["numConnections"] = "0"

    def setup_folder(self, folder_id: str | None = None, folder_label: str | None = None, prefix: str | None = None):
        if folder_id is None:
            folder_id = "data"
        if folder_label is None:
            folder_label = "SharedFolder"

        for st in self.nodes:
            if prefix is None:
                st.local = self.tmpdir / st.name
            elif prefix.startswith("fake?"):
                st.local = Path(prefix)
            else:
                st.local = Path(prefix) / st.name

            if st.local:
                (st.local / folder_id).mkdir(parents=True, exist_ok=True)

            folder = st.config.append(
                "folder",
                attrib={
                    "id": folder_id,
                    "label": folder_label,
                    "path": prefix if prefix and prefix.startswith("fake?") else str(st.local / folder_id),
                    "type": ROLE_TO_TYPE.get(st.role, st.role),
                    "rescanIntervalS": "3600",
                    "fsWatcherEnabled": "true",
                    "fsWatcherDelayS": "10",
                    "fsWatcherTimeoutS": "0",
                    "ignorePerms": "false",
                    "autoNormalize": "true",
                },
            )
            folder["filesystemType"] = "fake" if prefix and prefix.startswith("fake?") else "basic"
            folder["minDiskFree"] = {"@unit": "%", "#text": "1"}
            versioning = folder.append("versioning")
            versioning["cleanupIntervalS"] = "3600"
            versioning["fsPath"] = ""
            versioning["fsType"] =  "fake" if prefix and prefix.startswith("fake?") else "basic"
            folder["copiers"] = "0"
            folder["pullerMaxPendingKiB"] = "0"
            folder["hashers"] = "0"
            folder["order"] = "random"
            folder["ignoreDelete"] = "false"
            folder["scanProgressIntervalS"] = "0"
            folder["pullerPauseS"] = "0"
            folder["pullerDelayS"] = "1"
            folder["maxConflicts"] = "10"
            folder["disableSparseFiles"] = "false"
            folder["paused"] = "false"
            folder["markerName"] = ".stfolder"
            folder["copyOwnershipFromParent"] = "false"
            folder["modTimeWindowS"] = "0"
            folder["maxConcurrentWrites"] = "16"
            folder["disableFsync"] = "false"
            folder["blockPullOrder"] = "standard"
            folder["copyRangeMethod"] = "standard"
            folder["caseSensitiveFS"] = "false"
            folder["junctionsAsDirs"] = "false"
            folder["syncOwnership"] = "false"
            folder["sendOwnership"] = "false"
            folder["syncXattrs"] = "false"
            folder["sendXattrs"] = "false"
            xattrFilter = folder.append("xattrFilter")
            xattrFilter["maxSingleEntrySize"] = "1024"
            xattrFilter["maxTotalSize"] = "4096"

            # add devices to folder
            for peer_id in self.device_ids:
                folder_device = folder.append("device", attrib={"id": peer_id, "introducedBy": ""})
                folder_device["encryptionPassword"] = ""

            st.update_config()
        return folder_id

    def wait_for_connection(self, timeout=60):
        return [st.wait_for_connection(timeout=timeout) for st in self.nodes]

    def start(self):
        [st.start() for st in self.nodes]

    def stop(self):
        [st.stop() for st in self.nodes]

    def inspect(self):
        print(len(self.nodes), "nodes")
        for node in self.nodes:
            print("###", node.name)
            print("open", node.api_url)
            print("ls", node.local)
            print()

    def __iter__(self):
        yield from self.nodes

    def __enter__(self):
        self.setup_peers()
        self.folder_id = self.setup_folder()

        for st in self.nodes:
            st.start()

        return self

    def __exit__(self, exc_type, exc, tb):
        for st in self.nodes:
            st.cleanup()

        # only delete tempdir if no exception occurred
        if exc_type is None:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
