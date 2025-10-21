import tests.fstree as fstree
from syncweb.cmd_utils import cmd
from syncweb.syncthing import SyncthingCluster

cmd("pkill", "-f", "syncweb-py/syncthing", strict=False)


def test_w_w_copy():
    with SyncthingCluster(["w", "w"]) as cluster:
        cluster.wait_for_connection()
        w1, w2 = cluster

        fstree.write({"test.txt": "hello world"}, w1.home / "data")
        fstree.write({"test.txt": "hello morld"}, w2.home / "data")

        cluster.inspect()
        breakpoint()
