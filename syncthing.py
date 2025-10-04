import os, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

import requests
from library.utils import processes

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

        self.write_config()

        self.name = name
        self.role = role
        # TODO: relies on intial empty config; replace with REST API call for any non-temporary use
        self.device_id = str(self.config["device"]["@id"])
        self.bin = bin
        self.process: subprocess.Popen
        self.gui_port: int
        self.sync_port: int
        self.discovery_port: int
        self.folder: str

    def write_config(self):
        # stop nodes to be able to write configs
        self.stop()
        self.config.save()

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
        # self.sync_port = find_free_port(22000)
        # self.discovery_port = find_free_port(21027)

        self.config["gui"]["address"] = f"127.0.0.1:{self.gui_port}"
        # self.config["options"]["listenAddress"] = f"tcp://0.0.0.0:{self.sync_port}"
        self.write_config()

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

    def get_device_id(self, retries=5, delay=0.5):  # TODO: dead code
        url = f"{self.api_url}/rest/system/status"
        for _ in range(retries):
            try:
                r = self.session.get(url)
                r.raise_for_status()
                return r.json()["myID"]
            except Exception:
                time.sleep(delay)
        raise RuntimeError("Failed to get device ID from Syncthing instance")
        # shutil.rmtree(self.home_path, ignore_errors=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cleanup()


ROLE_TO_TYPE = {
    "r": "receiveonly",
    "w": "sendonly",
    "rw": "sendreceive",
}


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
        self._active = False

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

    def setup_folder(self):
        folder_id = "iwk3n-vemaq"
        folder_label = "SharedFolder"
        for st in self.nodes:
            st.folder = str(self.tmpdir / st.name / "data")
            Path(st.folder).mkdir(parents=True, exist_ok=True)
            folder = st.config.append(
                "folder",
                attrib={
                    "id": folder_id,
                    "label": folder_label,
                    "path": st.folder,
                    "type": ROLE_TO_TYPE.get(st.role, st.role),
                    "rescanIntervalS": "3600",
                    "fsWatcherEnabled": "true",
                    "fsWatcherDelayS": "10",
                    "fsWatcherTimeoutS": "0",
                    "ignorePerms": "false",
                    "autoNormalize": "true",
                },
            )
            folder["filesystemType"] = "basic"
            folder["minDiskFree"] = {"@unit": "%", "#text": "1"}
            versioning = folder.append("versioning")
            versioning["cleanupIntervalS"] = "3600"
            versioning["fsPath"] = ""
            versioning["fsType"] = "basic"
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

            st.write_config()

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
            print("cat", node.config_path)
            print("ls", node.folder)
            print()

    def __iter__(self):
        yield from self.nodes

    def __enter__(self):
        self.setup_peers()
        self.setup_folder()

        for st in self.nodes:
            st.start()

        self._active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        for st in self.nodes:
            st.cleanup()

        # only delete tempdir if no exception occurred
        if exc_type is None:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

        self._active = False
