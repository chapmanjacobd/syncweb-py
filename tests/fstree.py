import time
from pathlib import Path


def write(fstree: dict, base: Path | str):
    for name, value in fstree.items():
        path = Path(base) / name
        if isinstance(value, dict):
            path.mkdir(parents=True, exist_ok=True)
            write(value, path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                f.write(value)


def read(base: Path | str) -> dict:
    tree = {}
    for child in Path(base).iterdir():
        if child.name == ".stfolder":
            continue
        elif child.is_dir():
            tree[child.name] = read(child)
        else:
            with open(child, "r") as f:
                tree[child.name] = f.read()
    return tree


def all_files_exist(tree: dict, base: Path | str) -> bool:
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


def wait(fstree: dict, folder: Path | str, timeout=30) -> bool:
    deadline = time.time() + timeout

    while time.time() < deadline:
        if all_files_exist(fstree, folder):
            return True
        time.sleep(1)
    return False


def validate(expected: dict, actual: dict, prefix=""):
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
                if not validate(value, actual[name], path):
                    ok = False
        else:
            if not isinstance(actual[name], str):
                print(f"- Expected file but found directory: {path}")
                ok = False
            elif actual[name] != value:
                print(f"- Content mismatch in file {path}")
                ok = False

    return ok


def check(fstree: dict, folder: Path | str):
    if wait(fstree, folder, timeout=60):
        tree2 = read(folder)
        if validate(fstree, tree2):
            print("Files synced successfully")
            return True
        else:
            print("File trees differ")
            raise ValueError("File trees differ")
    else:
        print("Files did not sync in time")
        raise TimeoutError
