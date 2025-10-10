import time

from syncweb.syncthing import SyncthingNode


def check(st: SyncthingNode, folder_id, rel_paths, timeout=30) -> bool:
    deadline = time.time() + timeout

    while time.time() < deadline:
        for rel_path in list(rel_paths):
            if st.file(folder_id, rel_path):
                rel_paths.remove(rel_path)
        if not rel_paths:
            return True
        time.sleep(1)

    return False
