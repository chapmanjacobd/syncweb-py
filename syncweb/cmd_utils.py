import os, sys
from pathlib import Path


def default_state_dir(appname: str) -> Path:
    home = Path.home()
    platform = sys.platform

    if platform == "win32":
        base = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local")) / appname
    elif platform == "darwin":
        base = home / "Library" / "Application Support" / appname
    elif "iOS" in platform or "PYTHONISTA" in os.environ or "PYTO_APP" in os.environ:
        base = home / "Library" / "Application Support" / appname
    elif "TERMUX_VERSION" in os.environ:
        base = Path(os.getenv("XDG_STATE_HOME", home / ".local" / "state")) / appname
    else:
        base = Path(os.getenv("XDG_STATE_HOME", home / ".local" / "state")) / appname

    # fallback
    if not os.access(base.parent, os.W_OK):
        try:
            prog_dir = Path(sys.argv[0]).resolve().parent
        except Exception:
            prog_dir = Path.cwd()
        base = prog_dir / appname

    return base
