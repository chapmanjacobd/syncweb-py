import time
from pathlib import Path
from unittest import skip

from syncthing import SyncthingCluster
from library.utils import processes


def write_fstree(base: Path, fstree: dict):
    for name, value in fstree.items():
        path = base / name
        if isinstance(value, dict):
            path.mkdir(parents=True, exist_ok=True)
            write_fstree(path, value)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                f.write(value)


def read_fstree(base: Path) -> dict:
    tree = {}
    for child in base.iterdir():
        if child.name == ".stfolder":
            continue
        elif child.is_dir():
            tree[child.name] = read_fstree(child)
        else:
            with open(child, "r") as f:
                tree[child.name] = f.read()
    return tree


def wait_for_fstree(folder: Path, fstree: dict, timeout=30) -> bool:
    deadline = time.time() + timeout

    def all_files_exist(base: Path, tree: dict) -> bool:
        for name, value in tree.items():
            path = base / name
            if isinstance(value, dict):
                if not path.is_dir():
                    return False
                if not all_files_exist(path, value):
                    return False
            else:
                if not path.is_file():
                    return False
        return True

    while time.time() < deadline:
        if all_files_exist(folder, fstree):
            return True
        time.sleep(1)
    return False


def validate_fstree(expected: dict, actual: dict, prefix=""):
    ok = True
    for name, value in expected.items():
        path = f"{prefix}/{name}" if prefix else name
        if name not in actual:
            print(f"- Missing in actual: {path}")
            ok = False
            continue

        if isinstance(value, dict):
            if not isinstance(actual[name], dict):
                print(f"- Expected directory but found file: {path}")
                ok = False
            else:
                if not validate_fstree(value, actual[name], path):
                    ok = False
        else:
            if not isinstance(actual[name], str):
                print(f"- Expected file but found directory: {path}")
                ok = False
            elif actual[name] != value:
                print(f"- Content mismatch in file {path}")
                ok = False

    return ok


def file_copy(fstree, folder1, folder2):
    folder1 = Path(folder1)
    folder2 = Path(folder2)

    # Ensure nothing from fstree already exists in folder1/folder2
    if validate_fstree(fstree, read_fstree(folder1)):
        raise AssertionError("folder1 already contains target files")
    if validate_fstree(fstree, read_fstree(folder2)):
        raise AssertionError("folder2 already contains target files")

    write_fstree(folder1, fstree)

    # Wait for fstree to exist in folder2
    if wait_for_fstree(folder2, fstree, timeout=60):
        tree2 = read_fstree(folder2)
        if validate_fstree(fstree, tree2):
            print("Files synced successfully")
            return True
        else:
            print("File trees differ")
            raise ValueError("File trees differ")
    else:
        print("Files did not sync in time")
        raise TimeoutError


@skip("Behavior known")
def test_rw_rw_copy():
    with SyncthingCluster(["rw", "rw"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        file_copy({"test.txt": "hello world"}, rw1.folder, rw2.folder)
        file_copy({"test2.txt": "hello morld"}, rw2.folder, rw1.folder)


def test_w_r_move():
    with SyncthingCluster(["w", "r"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        source_fstree = {"test.txt": "hello world"}
        file_copy(source_fstree, rw1.folder, rw2.folder)

        processes.cmd(
            "syncthing_send.py",
            "--interval=1",
            "--timeout=30s",
            f"--port={rw1.gui_port}",
            f"--api-key={rw1.api_key}",
            rw1.folder,
            strict=False
        )
        assert read_fstree(Path(rw1.folder)) == {}
        assert read_fstree(Path(rw2.folder)) == source_fstree

        cluster.inspect()
        input()


def test_r_rw_copy():
    with SyncthingCluster(["r", "rw"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        file_copy({"test.txt": "hello world"}, rw1.folder, rw2.folder)

        cluster.inspect()
        input()


def test_w_rw_copy():
    with SyncthingCluster(["w", "rw"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        file_copy({"test.txt": "hello world"}, rw1.folder, rw2.folder)

        cluster.inspect()
        input()


def test_rw_r_copy():
    with SyncthingCluster(["rw", "r"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        file_copy({"test.txt": "hello world"}, rw1.folder, rw2.folder)

        cluster.inspect()
        input()


def test_rw_w_copy():
    with SyncthingCluster(["rw", "w"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        file_copy({"test.txt": "hello world"}, rw1.folder, rw2.folder)

        cluster.inspect()
        input()


def test_r_r_copy():
    with SyncthingCluster(["r", "r"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        file_copy({"test.txt": "hello world"}, rw1.folder, rw2.folder)
        file_copy({"test.txt": "hello morld"}, rw2.folder, rw1.folder)

        cluster.inspect()
        input()


def test_w_w_copy():
    with SyncthingCluster(["w", "w"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        file_copy({"test.txt": "hello world"}, rw1.folder, rw2.folder)
        file_copy({"test.txt": "hello morld"}, rw2.folder, rw1.folder)

        cluster.inspect()
        input()
