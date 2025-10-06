from library.utils import processes
import pytest

import fstree
from syncthing import SyncthingCluster, SyncthingNode

processes.cmd("pkill", "-f", "syncweb-py/syncthing", strict=False)



def test_fake():
    cluster = SyncthingCluster(["rw", "rw"])
    cluster.setup_peers()
    cluster.setup_folder(prefix=f"fake?size={5 * 1000}")
    for st in cluster.nodes:
        st.start()
    cluster.wait_for_connection()
    rw1, rw2 = cluster

    cluster.inspect()
    breakpoint()


def test_globalignore():
    with SyncthingCluster(["rw", "rw"]) as cluster:
        cluster.wait_for_connection()
        w1, w2 = cluster
        w1.db_set_ignores(cluster.folder_id, ["test.txt", "test2.txt"])

        fstree.write({"test.txt": "node0"}, w1.local)
        fstree.write({"test2.txt": "node1"}, w2.local)

        # pprint(w2.db_file(w2.folder_id, 'test2.txt'))

        cluster.inspect()
        breakpoint()


def test_globalignore_w_w():
    with SyncthingCluster(["w", "w"]) as cluster:
        cluster.wait_for_connection()
        w1, w2 = cluster
        w1.db_set_ignores(cluster.folder_id, ["test.txt", "test2.txt"])

        fstree.write({"test.txt": "node0"}, w1.local)
        fstree.write({"test2.txt": "node1"}, w2.local)

        # pprint(w2.db_file(w2.folder_id, 'test.txt'))

        cluster.inspect()
        breakpoint()


def test_events():
    with SyncthingNode("node0") as node0, SyncthingNode("node1") as node1:
        node0.start()
        for event in node0.event_source():
            print(event)

        node1.start()

        evt = node0.wait_for_event("FolderSummary", timeout=15)
        if evt:
            print("Got FolderSummary:", evt)


def test_w_w_r_copy():
    with SyncthingCluster(["w", "w", "r"]) as cluster:
        cluster.wait_for_connection()
        w1, w2, r = cluster

        fstree.write({"test.txt": "node0"}, w1.local)
        fstree.write({"test.txt": "node1"}, w2.local)
        # fstree.write({"test.txt": "node2"}, r.folder)

        cluster.inspect()
        breakpoint()


def test_w_w_rw_copy():
    with SyncthingCluster(["w", "w", "rw"]) as cluster:
        cluster.wait_for_connection()
        w1, w2, rw = cluster

        fstree.write({"test.txt": "node0"}, w1.local)
        fstree.write({"test.txt": "node1"}, w2.local)
        fstree.write({"test.txt": "node2"}, rw.local)

        cluster.inspect()
        breakpoint()


def test_rw_r_copy():
    with SyncthingCluster(["rw", "r"]) as cluster:
        cluster.wait_for_connection()
        rw, r = cluster

        fstree.write({"test.txt": "hello world"}, rw.local)

        cluster.inspect()
        breakpoint()


def test_rw_w_copy():
    with SyncthingCluster(["rw", "w"]) as cluster:
        cluster.wait_for_connection()
        rw, w = cluster

        fstree.write({"test.txt": "hello world"}, rw.local)

        cluster.inspect()
        breakpoint()


def test_r_r_copy():
    with SyncthingCluster(["r", "r"]) as cluster:
        cluster.wait_for_connection()
        r1, r2 = cluster

        fstree.write({"test.txt": "hello world"}, r1.local)
        fstree.write({"test.txt": "hello morld"}, r2.local)

        cluster.inspect()
        breakpoint()


def test_w_w_copy():
    with SyncthingCluster(["w", "w"]) as cluster:
        cluster.wait_for_connection()
        w1, w2 = cluster

        fstree.write({"test.txt": "hello world"}, w1.local)
        fstree.write({"test.txt": "hello morld"}, w2.local)

        cluster.inspect()
        breakpoint()
