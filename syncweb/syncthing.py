import os, shutil, socket, subprocess, sys, tempfile, time
from functools import cached_property
from pathlib import Path

import requests

from syncweb.cmd_utils import Pclose, cmd
from syncweb.config import ConfigXML
from syncweb.consts import PYTEST_RUNNING
from syncweb.log_utils import log

ROLE_TO_TYPE = {
    "r": "receiveonly",
    "w": "sendonly",
    "rw": "sendreceive",
}


class SyncthingNodeXML:
    def __init__(self, name: str = "st-node", syncthing_exe=None, base_dir=None):
        self.name = name
        self.syncthing_exe = syncthing_exe or self.find_syncthing_bin()
        self.process: subprocess.Popen
        self.sync_port: int
        self.discovery_port: int
        self.local: Path

        if base_dir is None:
            base_dir = tempfile.mkdtemp(prefix="syncthing-node-")
        self.home_path = Path(base_dir)
        self.home_path.mkdir(parents=True, exist_ok=True)
        self.config_path = self.home_path / "config.xml"

        if not self.config_path.exists():
            cmd(self.syncthing_exe, f"--home={self.home_path}", "generate")

        self.config = ConfigXML(self.config_path)
        self.xml_set_default_config(PYTEST_RUNNING)

        lock_path = self.home_path / "syncthing.lock"
        self.running: bool = lock_path.exists()
        if self.running:
            log.debug("Found lockfile, is a Syncweb instance already running? %s", lock_path)
            try:
                if self.wait_for_pong(timeout=15):
                    log.debug("Yes! Good thing we waited")
                    self.running = True
            except TimeoutError:
                log.error("Could not connect to existing(?) Syncweb instance at %s", self.api_url)
                self.running = False
        else:
            self.xml_update_config()

    @staticmethod
    def find_syncthing_bin():
        rel_bin = "./syncthing"
        if os.path.exists(rel_bin):
            default_bin = os.path.realpath(rel_bin)
        else:
            default_bin = shutil.which("syncthing") or "syncthing"
        return default_bin

    def xml_set_default_config(self, testing=False):
        node = self.config["device"]
        # node["@id"] = "DWFH3CZ-6D3I5HE-6LPQAHE-YGO3KQY-PX36X4V-BZORCMN-PC2V7O5-WB3KIAR"
        node["@name"] = self.name  # will use hostname by default
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
        if testing:
            opts["globalAnnounceEnabled"] = "false"
            opts["relaysEnabled"] = "false"
            opts["maxSendKbps"] = "200"
            opts["maxRecvKbps"] = "200"

        opts["startBrowser"] = "false"
        # disable Anonymous Usage Statistics
        opts["urAccepted"] = "-1"
        opts["urSeen"] = "3"
        opts["urInitialDelayS"] = "3600"
        # disable auto update
        opts["autoUpgradeIntervalH"] = "0"
        opts["keepTemporariesH"] = "192"
        opts["progressUpdateIntervalS"] = "-1"
        # opts["maxFolderConcurrency"] = "8"
        # opts["maxConcurrentIncomingRequestKiB"] = "400000"
        # opts["connectionLimitEnough"] = "8000"
        # opts["connectionLimitMax"] = "80000"
        # opts["listenAddress"] = "default"  # will be randomly picked
        # opts["globalAnnounceServer"] = "default"
        # opts["localAnnounceEnabled"] = "true"
        # opts["localAnnouncePort"] = "21027"
        # opts["localAnnounceMCAddr"] = "[ff12::8384]:21027"
        # opts["reconnectionIntervalS"] = "60"
        # opts["relayReconnectIntervalM"] = "10"
        # opts["natEnabled"] = "true"
        # opts["natLeaseMinutes"] = "60"
        # opts["natRenewalMinutes"] = "30"
        # opts["natTimeoutSeconds"] = "10"
        # opts["urUniqueID"] = ""
        # opts["urURL"] = "https://data.syncthing.net/newdata"
        # opts["urPostInsecurely"] = "false"
        # opts["upgradeToPreReleases"] = "false"
        # opts["cacheIgnoredFiles"] = "true"  # TODO: evaluate performance difference
        # opts["limitBandwidthInLan"] = "false"
        # opts["minHomeDiskFree"] = {"@unit": "%", "#text": "1"}
        # opts["releasesURL"] = "https://upgrades.syncthing.net/meta.json"
        # opts["overwriteRemoteDeviceNamesOnConnect"] = "false"
        # opts["tempIndexMinBlocks"] = "10"
        # opts["unackedNotificationID"] = "authenticationUserAndPassword"
        # opts["trafficClass"] = "0"
        # opts["setLowPriority"] = "true"
        # opts["crashReportingURL"] = "https://crash.syncthing.net/newcrash"
        # opts["crashReportingEnabled"] = "true"
        # opts["stunKeepaliveStartS"] = "180"
        # opts["stunKeepaliveMinS"] = "20"
        # opts["stunServer"] = "default"
        # opts["announceLANAddresses"] = "true"
        # opts["sendFullIndexOnUpgrade"] = "false"
        # opts["auditEnabled"] = "false"
        # opts["auditFile"] = ""
        # opts["connectionPriorityTcpLan"] = "10"
        # opts["connectionPriorityQuicLan"] = "20"
        # opts["connectionPriorityTcpWan"] = "30"
        # opts["connectionPriorityQuicWan"] = "40"
        # opts["connectionPriorityRelay"] = "50"
        # opts["connectionPriorityUpgradeThreshold"] = "0"

    def xml_add_devices(self, peer_ids):
        for j, peer_id in enumerate(peer_ids):
            device = self.config.append(
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

    def xml_add_folder(self, folder_id, peer_ids, folder_type="sendreceive", folder_label=None, prefix=None):
        is_fakefs = prefix and prefix.startswith("fake")

        if is_fakefs and prefix:
            self.local = Path(prefix)
        elif prefix:
            self.local = Path(prefix) / self.name
        else:
            self.local = self.home_path / self.name

        if not is_fakefs:
            (self.local / folder_id).mkdir(parents=True, exist_ok=True)

        if folder_label is None:
            folder_label = "SharedFolder"

        folder = self.config.append(
            "folder",
            attrib={
                "id": folder_id,
                "label": folder_label,
                "path": prefix if is_fakefs else str(self.local / folder_id),
                "type": ROLE_TO_TYPE.get(folder_type, folder_type),
                "rescanIntervalS": "3600",
                "fsWatcherEnabled": "false" if is_fakefs else "true",
                "fsWatcherDelayS": "5",
                "fsWatcherTimeoutS": "0",
                "ignorePerms": "true",
                "autoNormalize": "true",
            },
        )
        folder["filesystemType"] = "fake" if is_fakefs else "basic"
        folder["minDiskFree"] = {"@unit": "%", "#text": "1"}
        versioning = folder.append("versioning")
        versioning["cleanupIntervalS"] = "3600"
        versioning["fsPath"] = ""
        versioning["fsType"] = "fake" if is_fakefs else "basic"
        folder["copiers"] = "0"
        folder["pullerMaxPendingKiB"] = "0"
        folder["hashers"] = "0"
        folder["order"] = "random"
        folder["ignoreDelete"] = "false"
        folder["scanProgressIntervalS"] = "-1"
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
        for peer_id in peer_ids:
            folder_device = folder.append("device", attrib={"id": peer_id, "introducedBy": ""})
            folder_device["encryptionPassword"] = ""

        self.xml_update_config()

    def xml_update_config(self):
        was_running = self.running
        if was_running:
            self.stop()  # stop node to be able to write configs

        self.config.save()

        if was_running:
            self.start()

    @staticmethod
    def find_free_port(start_port: int) -> int:
        port = start_port
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    port += 1

    def start(self, daemonize=False):
        if self.running:
            return
        if getattr(self, "process", False) and self.process.poll() is None:
            self.running = True
            return

        gui_port = self.find_free_port(8384)
        self.config["gui"]["address"] = f"127.0.0.1:{gui_port}"
        # self.sync_port = find_free_port(22000)
        # self.config["options"]["listenAddress"] = f"tcp://0.0.0.0:{self.sync_port}"

        self.xml_update_config()

        cmd = [self.syncthing_exe, f"--home={self.home_path}", "--no-browser", "--no-upgrade", "--no-restart"]

        if daemonize:
            z = subprocess.DEVNULL
            self.process = subprocess.Popen(cmd, stdin=z, stdout=z, stderr=z, close_fds=True, start_new_session=True)
        else:
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # Give Syncthing a moment
        time.sleep(0.5)
        self.running = True

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

        self.running = False

    def log(self):
        r = Pclose(self.process)

        if r.returncode != 0:
            print(self.name, "exited", r.returncode)
        if r.stdout:
            print(r.stdout)
        if r.stderr:
            print(r.stderr, file=sys.stderr)

    @property
    def api_url(self):
        return "http://" + str(self.config["gui"]["address"])

    def _get(self, path, **kwargs):
        resp = self.session.get(f"{self.api_url}/rest/{path}", **kwargs)
        if resp.text:
            log.debug(resp.text)
        resp.raise_for_status()
        return resp.json()

    def wait_for_pong(self, timeout: float = 30.0):
        start = time.monotonic()

        while time.monotonic() - start < timeout:
            try:
                if self._get("system/ping", timeout=5) == {"ping": "pong"}:
                    return True
            except Exception as e:
                log.debug("Error waiting for pong %s", e)
            time.sleep(0.5)

        raise TimeoutError

    @property
    def api_key(self):
        return str(self.config["gui"]["apikey"])

    @cached_property
    def session(self):
        s = requests.Session()
        s.headers.update({"X-API-Key": self.api_key})
        return s

    def _put(self, path, **kwargs):
        resp = self.session.put(f"{self.api_url}/rest/{path}", **kwargs)
        if resp.text:
            log.debug(resp.text)
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def _post(self, path, json=None, **kwargs):
        resp = self.session.post(f"{self.api_url}/rest/{path}", json=json, **kwargs)
        if resp.text:
            log.debug(resp.text)
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def _patch(self, path, **kwargs):
        resp = self.session.patch(f"{self.api_url}/rest/{path}", **kwargs)
        if resp.text:
            log.debug(resp.text)
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def _delete(self, path, **kwargs):
        resp = self.session.delete(f"{self.api_url}/rest/{path}", **kwargs)
        if resp.text:
            log.debug(resp.text)
        if resp.status_code == 404:
            log.warning("404 Not Found %s", path)
        else:
            resp.raise_for_status()
        return resp


class SyncthingNode(SyncthingNodeXML):
    def wait_for_node(self, timeout=60):
        deadline = time.time() + timeout

        if getattr(self, "process", False):
            assert self.process.poll() is None

        errors = []
        while time.time() < deadline:
            try:
                r = self.session.get("system/connections")
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

    def shutdown(self):
        return self._post("system/shutdown")

    def restart(self):
        return self._post("system/restart")

    def is_restart_required(self) -> bool:
        resp = self._get("config/restart-required")
        return resp.get("restartRequired", False)

    @cached_property
    def version(self):
        return self._get("system/version")

    def status(self, retries=5, delay=1):
        for _ in range(retries):
            try:
                status = self._get("system/status")
                return status
            except Exception:
                time.sleep(delay)
        raise RuntimeError("Failed to get status of Syncthing node")

    def system_errors(self):
        return self._get("system/error")

    def get_config(self):
        return self._get("config")

    def replace_config(self, config: dict):
        config = self.get_config() | config
        return self._put("config", json=config)

    def get_device_id(self, retries=15, delay=0.5):
        for _ in range(retries):
            try:
                status = self._get("system/status")
                return status["myID"]
            except Exception:
                time.sleep(delay)

        log.warning("Failed to get device ID from Syncthing node")
        raise TimeoutError

    @cached_property
    def device_id(self):
        if not self.running:
            self.start()
        try:
            return self.get_device_id()
        except TimeoutError:
            # relies on initial empty config
            log.warning("GUI Port is not set; relying on XML which may be incorrect")
            return str(self.config["device"]["@id"])

    def devices(self):
        return self._get("config/devices")

    @property
    def devices_list(self):
        return [d["deviceID"] for d in self.devices()]

    @property
    def devices_dict(self):
        return {d["deviceID"]: d for d in self.devices()}

    @property
    def folders_dict(self):
        return {d["id"]: d for d in self.folders()}

    @property
    def folder_roots(self):
        return {d["path"]: d["id"] for d in self.folders()}

    def add_device(self, **kwargs):
        return self._post("config/devices", json=kwargs)

    def delete_device(self, device_id: str):
        return self._delete(f"config/devices/{device_id}")

    def device_stats(self):
        return self._get("stats/device")

    def pause(self, device_id: str | None = None):
        params = {}
        if device_id:  # when omitted pauses all devices
            params["device"] = device_id
        return self._post("system/pause", params=params)

    def resume(self, device_id: str | None = None):
        params = {}
        if device_id:  # when omitted resumes all devices
            params["device"] = device_id
        return self._post("system/resume", params=params)

    def pause_folder(self, folder_id: str):
        existing_folder = self.folder(folder_id)
        existing_folder["paused"] = True
        self._patch(f"config/folders/{folder_id}", json=existing_folder)

    def resume_folder(self, folder_id: str):
        existing_folder = self.folder(folder_id)
        existing_folder["paused"] = False
        self._patch(f"config/folders/{folder_id}", json=existing_folder)

    def folder_status(self, folder_id: str):
        return self._get("db/status", params={"folder": folder_id})

    def default_folder(self):
        return self._get("config/defaults/folder")

    def set_default_folder(self, **folder):
        default_folder = self.default_folder()
        default_folder["name"] = "default"
        default_folder["label"] = "Syncweb Default"
        default_folder["path"] = os.path.realpath(".")
        default_folder["rescanIntervalS"] = 7200
        default_folder["fsWatcherDelayS"] = 5
        default_folder["ignorePerms"] = True
        default_folder["ignoreDelete"] = True
        default_folder["scanProgressIntervalS"] = -1
        default_folder["copyRangeMethod"] = "all"
        folder = default_folder | folder
        return self._put("config/defaults/folder", json=folder)

    def default_ignores(self):
        return self._get("config/defaults/ignores")

    def set_default_ignores(self, lines: list[str] | None = None):
        if lines is None:
            lines = ["*"]
        return self._put("config/defaults/ignores", json={"lines": lines})

    def ignores(self, folder_id: str):
        return self._get("db/ignores", params={"folder": folder_id})

    def set_ignores(self, folder_id: str, lines: list[str] | None = None):
        if lines is None:
            lines = ["*"]
        return self._post("db/ignores", params={"folder": folder_id}, json={"ignore": lines})

    def folder(self, folder_id: str):
        return self._get(f"config/folders/{folder_id}")

    def folders(self):
        return self._get("config/folders")

    def add_folder(self, **kwargs):
        if "label" not in kwargs:
            kwargs["label"] = None

        kwargs = self.default_folder() | kwargs
        return self._post("config/folders", json=kwargs)

    def delete_folder(self, folder_id: str):
        return self._delete(f"config/folders/{folder_id}")

    def reset_folder(self, folder_id: str | None = None):
        params = {}
        if folder_id:  # when omitted resets whole DB
            params["folder"] = folder_id
        return self._post("system/reset", params=params)

    def folder_stats(self):
        return self._get("stats/folder")

    def files(self, folder_id: str, levels: int | None = None, prefix: str | None = None):
        params = {"folder": folder_id}
        if levels is not None:
            params["levels"] = str(levels)
        if prefix is not None:
            params["prefix"] = prefix

        return self._get("db/browse", params=params)

    def file(self, folder_id: str, relative_path: str):
        params = {"folder": folder_id, "file": relative_path}

        resp = self.session.get(f"{self.api_url}/rest/db/file", params=params)
        if resp.status_code == 404:
            log.warning("404 Not Found %s", relative_path)
            return
        else:
            resp.raise_for_status()
        return resp.json()

    def folder_revert(self, receiveonly_folder_id: str):
        return self._post("db/revert", json={"folder": receiveonly_folder_id})

    def folder_override(self, sendonly_folder_id: str):
        return self._post("db/override", json={"folder": sendonly_folder_id})

    def prioritize_file_transfer(self, folder_id: str, file_path: str):
        return self._post(f"db/prio", params={"folder": folder_id, "file": file_path})

    @staticmethod
    def paged_fn(fn, *args, **kwargs):
        page = 1
        per_page = 50000
        all_files = []
        while True:
            resp = fn(*args, **kwargs, page=page, perpage=per_page)
            progress = resp.get("progress") or []
            queued = resp.get("queued") or []
            rest = resp.get("rest") or []
            log.debug("%s got %s progress, %s queued, %s rest", fn.__func__.__qualname__, progress, queued, rest)

            batch = progress + queued + rest
            if not batch:
                break
            all_files.extend(batch)
            # Stop if fewer than per_page items were returned (last page)
            if len(batch) < per_page:
                break
            page += 1

        return all_files

    def _remoteneed(self, **kwargs):
        return self._get("db/remoteneed", params=kwargs)

    def remoteneed(self, folder_id: str):
        return self.paged_fn(self._remoteneed, folder=folder_id)

    def _need(self, **kwargs):
        return self._get("db/need", params=kwargs)

    def need(self, folder_id: str):
        return self.paged_fn(self._need, folder=folder_id)

    def _localchanged(self, **kwargs):
        return self._get("db/localchanged", params=kwargs)

    def localchanged(self, folder_id: str):
        return self.paged_fn(self._localchanged, folder=folder_id)

    def _folder_errors(self, **kwargs):
        return self._get("folder/errors", params=kwargs)

    def folder_errors(self, folder_id: str):
        return self.paged_fn(self._folder_errors, folder=folder_id)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()


class SyncthingCluster:
    def __init__(self, roles, prefix="syncthing-cluster-"):
        self.roles = roles
        self.tmpdir = Path(tempfile.mkdtemp(prefix=prefix))
        self.nodes: list[SyncthingNode] = []
        for i, _role in enumerate(self.roles):
            home = self.tmpdir / f"node{i}"
            home.mkdir(parents=True, exist_ok=True)
            st = SyncthingNode(name=f"node{i}", base_dir=home)
            self.nodes.append(st)

    @property
    def device_ids(self):
        return [st.device_id for st in self.nodes]

    def setup_peers(self):
        for st in self.nodes:
            st.xml_add_devices(self.device_ids)

    def setup_folder(self, folder_id: str | None = None, prefix: str | None = None, folder_type: str = "sendreceive"):
        if folder_id is None:
            folder_id = "data"

        for idx, st in enumerate(self.nodes):
            st.xml_add_folder(
                folder_id, self.device_ids, folder_type=folder_type, prefix=self.increment_seed(prefix, idx)
            )
        return folder_id

    @staticmethod
    def increment_seed(prefix, idx):
        if prefix and "seed=?" in prefix:
            return prefix.replace("seed=?", f"seed={idx}")
        return prefix

    def wait_for_connection(self, timeout=60):
        return [st.wait_for_node(timeout=timeout) for st in self.nodes]

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
        self.folder_id = "data"

        for st in self.nodes:
            for idx, st in enumerate(self.nodes):
                role = self.roles[idx]
                st.xml_add_folder(self.folder_id, peer_ids=self.device_ids, folder_type=role)
            st.start()

        return self

    def __exit__(self, exc_type, exc, tb):
        for st in self.nodes:
            st.stop()

        # only delete tempdir if no exception occurred
        if exc_type is None:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
