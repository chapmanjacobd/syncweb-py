import time
from pathlib import Path
from unittest import skip

from syncthing import SyncthingCluster
from library.utils import processes


def write_fstree(fstree: dict, base: Path | str):
    for name, value in fstree.items():
        path = Path(base) / name
        if isinstance(value, dict):
            path.mkdir(parents=True, exist_ok=True)
            write_fstree(value, path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                f.write(value)


def read_fstree(base: Path | str) -> dict:
    tree = {}
    for child in Path(base).iterdir():
        if child.name == ".stfolder":
            continue
        elif child.is_dir():
            tree[child.name] = read_fstree(child)
        else:
            with open(child, "r") as f:
                tree[child.name] = f.read()
    return tree


def all_files_exist(tree: dict, base: Path| str) -> bool:
    for name, value in tree.items():
        path = Path(base) / name
        if isinstance(value, dict):
            if not path.is_dir():
                return False
            if not all_files_exist(value, path):
                return False
        else:
            if not path.is_file():
                return False
    return True

def wait_for_fstree(fstree: dict, folder: Path | str, timeout=30) -> bool:
    deadline = time.time() + timeout

    while time.time() < deadline:
        if all_files_exist(fstree, folder):
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


def check_fstree(fstree, folder):
    # Wait for fstree to exist in folder
    if wait_for_fstree(folder, fstree, timeout=60):
        tree2 = read_fstree(folder)
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

        write_fstree({"test.txt": "hello world"}, rw1.folder)
        check_fstree({"test.txt": "hello world"}, rw2.folder)

        write_fstree({"test2.txt": "hello morld"}, rw2.folder)
        check_fstree({"test2.txt": "hello morld"}, rw1.folder)


@skip("Behavior known")
def test_w_r_move():
    with SyncthingCluster(["w", "r"]) as cluster:
        cluster.wait_for_connection()
        w, r = cluster

        # deletes must be ignored in the destination folder
        r.config["folder"]["ignoreDelete"] = "true"
        r.update_config()

        source_fstree = {"test.txt": "hello world"}
        write_fstree(source_fstree, w.folder)
        check_fstree(source_fstree, r.folder)

        processes.cmd(
            "syncthing_send.py",
            "--interval=1",
            "--timeout=30s",
            f"--port={w.gui_port}",
            f"--api-key={w.api_key}",
            w.folder,
            strict=False
        )
        assert read_fstree(Path(w.folder)) == {}
        assert read_fstree(Path(r.folder)) == source_fstree

        # cluster.inspect()
        # input("Continue?")


def test_w_w_r_copy():
    with SyncthingCluster(["w", "w", "r"]) as cluster:
        cluster.wait_for_connection()
        w1, w2, r = cluster

        write_fstree({"test.txt": "node0"}, w1.folder)
        write_fstree({"test.txt": "node1"}, w2.folder)
        # write_fstree({"test.txt": "node2"}, r.folder)

        cluster.inspect()
        input("Continue?")

def test_w_w_rw_copy():
    with SyncthingCluster(["w", "w", "rw"]) as cluster:
        cluster.wait_for_connection()
        w1, w2, rw = cluster

        write_fstree({"test.txt": "node0"}, w1.folder)
        write_fstree({"test.txt": "node1"}, w2.folder)
        write_fstree({"test.txt": "node2"}, rw.folder)

        cluster.inspect()
        input("Continue?")


def test_rw_r_copy():
    with SyncthingCluster(["rw", "r"]) as cluster:
        cluster.wait_for_connection()
        rw, r = cluster

        write_fstree({"test.txt": "hello world"}, rw.folder)

        cluster.inspect()
        input("Continue?")


def test_rw_w_copy():
    with SyncthingCluster(["rw", "w"]) as cluster:
        cluster.wait_for_connection()
        rw, w = cluster

        write_fstree({"test.txt": "hello world"}, rw.folder)

        cluster.inspect()
        input("Continue?")


def test_r_r_copy():
    with SyncthingCluster(["r", "r"]) as cluster:
        cluster.wait_for_connection()
        r1, r2 = cluster

        write_fstree({"test.txt": "hello world"}, r1.folder)
        write_fstree({"test.txt": "hello morld"}, r2.folder)

        cluster.inspect()
        input("Continue?")


def test_w_w_copy():
    with SyncthingCluster(["w", "w"]) as cluster:
        cluster.wait_for_connection()
        w1, w2 = cluster

        write_fstree({"test.txt": "hello world"}, w1.folder)
        write_fstree({"test.txt": "hello morld"}, w2.folder)

        cluster.inspect()
        input("Continue?")
