#!/usr/bin/python3
import hashlib, json, os, platform, re, shutil, subprocess, tarfile, tempfile, urllib.request
from contextlib import suppress
from functools import total_ordering

from syncweb import consts
from syncweb.log_utils import log


@total_ordering
class Version:
    def __init__(self, version_str):
        # Strip "v" prefix and normalize
        self.original = version_str.strip()
        s = re.sub(r"^v", "", self.original)
        # Extract numeric parts and optional pre-release tag
        m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?([a-zA-Z0-9]+))?", s)
        if not m:
            raise ValueError(f"Invalid version string: {version_str}")
        self.major = int(m.group(1) or 0)
        self.minor = int(m.group(2) or 0)
        self.patch = int(m.group(3) or 0)
        self.prerelease = m.group(4) or ""

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)
        # Handle pre-releases: e.g., 2.0.0-beta < 2.0.0
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        return self.prerelease < other.prerelease

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
            and self.prerelease == other.prerelease
        )

    def __repr__(self):
        return f"Version('{self.original}')"


MIN_VERSION = Version("2.0.1")
API_URL = "https://api.github.com/repos/syncthing/syncthing/releases/latest"
DEST_PATH = os.path.join(consts.SCRIPT_DIR, "syncthing")


def find_syncthing_bin():
    rel_bin = "./syncthing"
    if os.path.exists(rel_bin):
        return os.path.realpath(rel_bin)
    elif os.path.exists(DEST_PATH):
        return os.path.realpath(DEST_PATH)
    else:
        default_bin = shutil.which("syncthing") or "syncthing"
        return default_bin


def get_platform():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        os_name = "linux"
    elif system == "darwin":
        os_name = "macos"
    elif system == "windows":
        os_name = "windows"
    else:
        raise RuntimeError(f"Unsupported OS: {system}")

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine.startswith("arm"):
        arch = "arm"
    elif machine in ("i386", "i686"):
        arch = "386"
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")

    return os_name, arch


def get_latest_assets():
    with urllib.request.urlopen(API_URL) as resp:
        data = json.load(resp)
    assets = {a["name"]: a["browser_download_url"] for a in data["assets"]}
    tag = data["tag_name"]
    return assets, tag


def find_asset_and_checksum(assets, os_name, arch):
    target_name = f"syncthing-{os_name}-{arch}"
    tar_url = None
    sha_url = None
    for name, url in assets.items():
        if "sha256sum.txt.asc" in name:
            sha_url = url
        if target_name in name and name.endswith(".tar.gz"):
            tar_url = url
    return tar_url, sha_url


def compute_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksum(sha_file, archive_name, archive_path):
    with open(sha_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if archive_name in line:
                expected = line.split()[0]
                actual = compute_sha256(archive_path)
                if expected != actual:
                    log.error("SHA256 mismatch for %s\nExpected: %s\nActual:   %s", archive_name, expected, actual)
                return
    log.error("No checksum found for %s", archive_name)


def atomic_replace(src_path, dest_path):
    dest_dir = os.path.dirname(dest_path)
    tmp_fd, tmp_dest_path = tempfile.mkstemp(dir=dest_dir)
    shutil.copy2(src_path, tmp_dest_path)
    os.close(tmp_fd)
    os.replace(tmp_dest_path, dest_path)
    os.unlink(src_path)


def extract_syncthing(archive, dest_path):
    with tarfile.open(archive, "r:gz") as tar:
        for member in reversed(tar.getmembers()):
            if os.path.basename(member.name) == "syncthing":
                member.name = "syncthing"
                tar.extract(member, path=os.path.dirname(archive))
                src_path = os.path.join(os.path.dirname(archive), "syncthing")
                atomic_replace(src_path, dest_path)
                return dest_path
    raise RuntimeError("No syncthing binary found in archive.")


def ensure_syncthing():
    existing_path = find_syncthing_bin()
    with suppress(FileNotFoundError, subprocess.CalledProcessError):
        out = subprocess.check_output([existing_path, "--version"], text=True)
        m = re.search(r"v(\d+\.\d+\.\d+)", out)
        if m:
            current_version = Version(m.group(1))
            if current_version and current_version >= MIN_VERSION:
                return existing_path

    os_name, arch = get_platform()
    assets, tag = get_latest_assets()
    tar_url, sha_url = find_asset_and_checksum(assets, os_name, arch)
    if not tar_url:
        raise RuntimeError(f"No compatible binary found for {os_name}/{arch}")
    if not sha_url:
        log.error("No checksum file found")

    with tempfile.TemporaryDirectory() as tmpdir:
        ar_path = os.path.join(tmpdir, os.path.basename(tar_url))
        checksum_path = os.path.join(tmpdir, "sha256sum.txt.asc")

        log.info("Downloading %s", tar_url)
        urllib.request.urlretrieve(tar_url, ar_path)
        if sha_url:
            urllib.request.urlretrieve(sha_url, checksum_path)
            verify_checksum(checksum_path, os.path.basename(ar_path), ar_path)

        extract_syncthing(ar_path, DEST_PATH)
        print(f"Downloaded Syncthing {tag} to {DEST_PATH}")
        return DEST_PATH


if __name__ == "__main__":
    ensure_syncthing()
