import shutil
from pathlib import Path

import pytest

import tests.db as db
import tests.fstree as fstree
from syncweb.cmd_utils import cmd
from syncweb.syncthing import SyncthingCluster, SyncthingNode


def test_rw_rw_copy():
    with SyncthingCluster(["rw", "rw"]) as cluster:
        cluster.wait_for_connection()
        rw1, rw2 = cluster

        fstree.write({"test.txt": "hello world"}, rw1.home / "data" / cluster.folder_id)
        fstree.check({"test.txt": "hello world"}, rw2.home / "data" / cluster.folder_id)

        fstree.write({"test2.txt": "hello morld"}, rw2.home / "data" / cluster.folder_id)
        fstree.check({"test2.txt": "hello morld"}, rw1.home / "data" / cluster.folder_id)

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
        fstree.write(source_fstree, w.home / "data" / cluster.folder_id)
        fstree.check(source_fstree, r.home / "data" / cluster.folder_id)

        cmd(
            "syncthing_send.py",
            "--interval=1",
            "--timeout=30s",
            f"--port={w.api_url.split(":")[-1]}",
            f"--api-key={w.api_key}",
            w.home / "data" / cluster.folder_id,
            strict=False,
        )
        assert fstree.read(Path(w.home / "data" / cluster.folder_id)) == {}
        assert fstree.read(Path(r.home / "data" / cluster.folder_id)) == source_fstree


def test_w_r_r():
    with SyncthingCluster(["w", "r", "r"]) as cluster:
        cluster.wait_for_connection()
        w, r1, r2 = cluster

        r2.stop()

        fstree.write({"test.txt": "hello world"}, w.home / "data" / cluster.folder_id)
        fstree.check({"test.txt": "hello world"}, r1.home / "data" / cluster.folder_id)

        # let's check that r2 can get a file from r1
        w.stop()
        r2.start()

        fstree.check({"test.txt": "hello world"}, r2.home / "data" / cluster.folder_id)


def test_malicious_node():
    with SyncthingCluster(["w", "r", "rw"]) as cluster:
        cluster.wait_for_connection()
        w, r, mal = cluster

        r.set_ignores(cluster.folder_id, ["test.txt"])
        fstree.write({"test.txt": "good world"}, w.home / "data" / cluster.folder_id)
        db.check(r, r.home / "data" / cluster.folder_id, ["test.txt"])
        w.stop()

        fstree.write({"test.txt": "bad world"}, mal.home / "data" / cluster.folder_id)
        r.set_ignores(cluster.folder_id, [])
        fstree.check({"test.txt": "bad world"}, r.home / "data" / cluster.folder_id)
        w.start()

        with pytest.raises(ValueError):
            fstree.check({"test.txt": "good world"}, r.home / "data" / cluster.folder_id)
        # Syncthing will not prevent other nodes from writing
        # https://github.com/syncthing/syncthing/issues/10420


def test_malicious_node2():
    # 2 writers, 1 reader using the same folder for read and write
    # keeping everything sendonly but using receiveonly only for receiving from known sources
    writer = SyncthingNode("writer")
    reader = SyncthingNode("reader")
    reader2 = SyncthingNode("reader2")
    mal = SyncthingNode("mal")

    nodes = (writer, reader, reader2, mal)
    device_ids = [st.device_id for st in nodes]
    for st in nodes:
        st.xml_add_devices(device_ids)

    send_fid = "send"
    [st.xml_add_folder(send_fid, device_ids, folder_type="readwrite" if st == mal else "sendonly") for st in nodes]
    [st.start() for st in nodes]
    [st.wait_for_node(timeout=60) for st in nodes]

    read_fid = "read"
    writer.add_folder(id=read_fid, path=str(writer.home / "data" / send_fid), type="sendonly")
    for read_node in [reader, reader2, mal]:
        # we only link a receiveonly folder with the known good source
        read_node.add_folder(id=read_fid, path=str(read_node.home / "data" / send_fid), type="receiveonly")
        read_node.add_folder_devices(read_fid, [st.device_id for st in [writer, read_node]])
        # add same devices to writer read_fid folder
        writer.add_folder_devices(read_fid, [st.device_id for st in [writer, read_node]])

    reader2.stop()

    fstree.write({"test.txt": "good world"}, writer.home / "data" / send_fid)
    fstree.write({"test.txt": "bad world"}, mal.home / "data" / send_fid)

    db.check(reader, read_fid, ["test.txt"])
    fstree.check({"test.txt": "good world"}, reader.home / "data" / send_fid)
    # good but it seems dependent on the specific writer node(s), so kind of useless

    writer.stop()
    reader2.start()
    reader2.wait_for_node(timeout=60)

    db.check(reader2, read_fid, ["test.txt"])
    with pytest.raises(TimeoutError):
        fstree.check({"test.txt": "good world"}, reader2.home / "data" / send_fid)
    # blocks really aren't shared between folders, I guess!


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
    fstree.write({"test.txt": "hello world"}, w.home / "data" / folder1)
    fstree.write({"test.txt": "hello world"}, w.home / "data" / folder2)

    fstree.check({"test.txt": "hello world"}, r1.home / "data" / folder1)
    fstree.check({}, r1.home / "data" / folder2)
    w.stop()

    r1.set_ignores(folder2, [])
    r2.start()
    with pytest.raises(TimeoutError):
        fstree.check({"test.txt": "hello world"}, r2.home / "data" / folder2)
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
