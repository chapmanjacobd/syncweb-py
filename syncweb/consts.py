import os, sys
from datetime import datetime, timezone
from typing import NamedTuple

APPLICATION_START = int(datetime.now(tz=timezone.utc).timestamp())
IS_WINDOWS = os.name == "nt" or sys.platform in ("win32", "cygwin", "msys")
PYTEST_RUNNING = "pytest" in sys.modules


class FolderRef(NamedTuple):
    folder_id: str | None
    subpath: str | None
    device_id: str | None
