import shutil
from pathlib import Path

import pytest

import tests.db as db
import tests.fstree as fstree
from syncweb.cmd_utils import cmd
from syncweb.syncthing import SyncthingCluster


def test_rw_rw_copy():
    with SyncthingCluster(["rw", "rw"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        fstree.write({"test.txt": "hello world"}, rw1.local / cluster.folder_id)
        fstree.check({"test.txt": "hello world"}, rw2.local / cluster.folder_id)

        fstree.write({"test2.txt": "hello morld"}, rw2.local / cluster.folder_id)
        fstree.check({"test2.txt": "hello morld"}, rw1.local / cluster.folder_id)

        # cluster.inspect()
        # breakpoint()


def test_w_r_move():
    with SyncthingCluster(["w", "r"]) as cluster:
        cluster.wait_for_connection()
        w, r = cluster

        # deletes must be ignored in the destination folder
        r.config["folder"]["ignoreDelete"] = "true"
        r.xml_update_config()

        source_fstree = {"test.txt": "hello world"}
        fstree.write(source_fstree, w.local / cluster.folder_id)
        fstree.check(source_fstree, r.local / cluster.folder_id)

        cmd(
            "syncthing_send.py",
            "--interval=1",
            "--timeout=30s",
            f"--port={w.api_url.split(":")[-1]}",
            f"--api-key={w.api_key}",
            w.local / cluster.folder_id,
            strict=False,
        )
        assert fstree.read(Path(w.local / cluster.folder_id)) == {}
        assert fstree.read(Path(r.local / cluster.folder_id)) == source_fstree


def test_w_r_r():
    with SyncthingCluster(["w", "r", "r"]) as cluster:
        cluster.wait_for_connection()
        w, r1, r2 = cluster

        r2.stop()

        fstree.write({"test.txt": "hello world"}, w.local / cluster.folder_id)
        fstree.check({"test.txt": "hello world"}, r1.local / cluster.folder_id)

        # let's check that r2 can get a file from r1
        w.stop()
        r2.start()

        fstree.check({"test.txt": "hello world"}, r2.local / cluster.folder_id)


def test_malicious_node():
    with SyncthingCluster(["w", "r", "rw"]) as cluster:
        cluster.wait_for_connection()
        w, r, mal = cluster

        r.set_ignores(cluster.folder_id, ["test.txt"])
        fstree.write({"test.txt": "good world"}, w.local / cluster.folder_id)
        db.check(r, r.local / cluster.folder_id, ["test.txt"])
        w.stop()

        fstree.write({"test.txt": "bad world"}, mal.local / cluster.folder_id)
        r.set_ignores(cluster.folder_id, [])
        fstree.check({"test.txt": "bad world"}, r.local / cluster.folder_id)
        w.start()

        with pytest.raises(ValueError):
            fstree.check({"test.txt": "good world"}, r.local / cluster.folder_id)
        # Syncthing will not prevent other nodes from writing
        # https://github.com/syncthing/syncthing/issues/10420


def test_w_r_r_blocks_across_folders():
    cluster = SyncthingCluster(["w", "r", "r"])
    cluster.setup_peers()
    folder1 = cluster.setup_folder("grape-juice")
    folder2 = cluster.setup_folder("dream-state")
    for st in cluster.nodes:
        st.start()
    cluster.wait_for_connection()
    w, r1, r2 = cluster

    r2.stop()

    r1.set_ignores(folder2, ["test.txt"])
    fstree.write({"test.txt": "hello world"}, w.local / folder1)
    fstree.write({"test.txt": "hello world"}, w.local / folder2)

    fstree.check({"test.txt": "hello world"}, r1.local / folder1)
    fstree.check({}, r1.local / folder2)
    w.stop()

    r1.set_ignores(folder2, [])
    r2.start()
    with pytest.raises(TimeoutError):
        fstree.check({"test.txt": "hello world"}, r2.local / folder2)
    # Syncthing does not share blocks between folders

    for st in cluster.nodes:
        st.stop()
    shutil.rmtree(cluster.tmpdir, ignore_errors=True)


def test_fake():
    cluster = SyncthingCluster(["rw", "rw"])
    cluster.setup_peers()
    cluster.folder_id = cluster.setup_folder(prefix="fake/?files=50&maxsize=100&seed=?&latency=50ms")
    for st in cluster.nodes:
        st.start()
    # cluster.wait_for_connection()
    rw1, rw2 = cluster

    cluster.inspect()
    breakpoint()
