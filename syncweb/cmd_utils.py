import os, shlex, subprocess, sys
from pathlib import Path
from shutil import which

from syncweb.consts import IS_WINDOWS, PYTEST_RUNNING
from syncweb.log_utils import log


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


def os_bg_kwargs() -> dict:
    # prevent ctrl-c from affecting subprocesses first

    if hasattr(os, "setpgrp"):
        return {"start_new_session": True}
    else:
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        # DETACHED_PROCESS = 0x00000008
        # os_kwargs = dict(creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        return {}


def cmd(
    *command, strict=True, cwd=None, quiet=True, error_verbosity=1, ignore_regexps=None, limit_ram=False, **kwargs
) -> subprocess.CompletedProcess:
    command = [str(s) for s in command]

    if limit_ram:
        cmd_prefix = []
        if which("systemd-run"):
            cmd_prefix += ["systemd-run"]
            if not "SUDO_UID" in os.environ:
                cmd_prefix += ["--user"]
            cmd_prefix += [
                "-p",
                "MemoryMax=4G",
                "-p",
                "MemorySwapMax=1G",
                "--pty",
                "--pipe",
                "--same-dir",
                "--wait",
                "--collect",
                "--service-type=exec",
                "--quiet",
                "--",
            ]
        command = cmd_prefix + command

    def print_std(s, is_success):
        if ignore_regexps is not None:
            s = "\n".join(line for line in s.splitlines() if not any(r.match(line) for r in ignore_regexps))

        s = s.strip()
        if s:
            if quiet and is_success:
                log.debug(s)
            elif PYTEST_RUNNING:
                log.warning(s)
            elif error_verbosity == 0:
                log.debug(s)
            elif error_verbosity == 1:
                log.info(s)
            else:
                log.warning(s)
        return s

    try:
        r = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd,
            errors=sys.getfilesystemencodeerrors(),
            **os_bg_kwargs(),
            **kwargs,
            check=False,
        )
    except UnicodeDecodeError:
        print(repr(command))
        raise

    log.debug(r.args)
    print_std(r.stdout, r.returncode == 0)
    print_std(r.stderr, r.returncode == 0)
    if r.returncode != 0:
        if error_verbosity == 0:
            log.debug("[%s] exited %s", shlex.join(command), r.returncode)
        elif error_verbosity == 1:
            log.info("[%s] exited %s", shlex.join(command), r.returncode)
        else:
            log.warning("[%s] exited %s", shlex.join(command), r.returncode)

        if strict:
            raise subprocess.CalledProcessError(r.returncode, shlex.join(command), r.stdout, r.stderr)

    return r


def Pclose(process) -> subprocess.CompletedProcess:  # noqa: N802
    try:
        stdout, stderr = process.communicate(input)
    except subprocess.TimeoutExpired as exc:
        log.debug("subprocess.TimeoutExpired")
        process.kill()
        if IS_WINDOWS:
            exc.stdout, exc.stderr = process.communicate()
        else:
            process.wait()
        raise
    except Exception as excinfo:
        log.debug(excinfo)
        process.kill()
        raise
    return_code = process.poll()
    return subprocess.CompletedProcess(process.args, return_code, stdout, stderr)
