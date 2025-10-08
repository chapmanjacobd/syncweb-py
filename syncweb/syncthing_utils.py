import os, platform
from pathlib import Path

if platform.system() == "Windows":
    import msvcrt
else:
    import fcntl


class LockFile:
    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def acquire(self) -> bool:
        self.fd = open(self.path, "w")
        try:
            if platform.system() == "Windows":
                # Lock the entire file (0, 0x7FFFFFFF)
                msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 0x7FFFFFFF)
            else:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write PID for reference/debugging
            self.fd.write(str(os.getpid()))
            self.fd.flush()
            return True
        except (BlockingIOError, OSError):
            # Lock failed
            self.fd.close()
            self.fd = None
            return False

    def release(self):
        if not self.fd:
            return
        try:
            if platform.system() == "Windows":
                msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 0x7FFFFFFF)
            else:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            self.fd.close()
            self.fd = None
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
