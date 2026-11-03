#!/usr/bin/env python3
"""OFF-2 opt-in, passive PATH/python/uvicorn shebang identity (NOT live runtime).

Do not start, import or interrogate services, read /proc cmdline/environ,
invoke pip, reveal executable paths, or interpret static identity as release.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import site
import stat
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.sraf_airgap_off2_runtime_deps import (
    _InvalidInventory, _open_directory_no_follow,
)
from tools.sraf_airgap_off2_manifest_check import _UnsafeEvidence, _fingerprint

SCHEMA = "sraf_off2_static_launcher_interpreter_v1"
SCOPE = "CURRENT_SHELL_PATH_AND_UVICORN_SCRIPT_ONLY_NOT_RUNNING_SERVICE"
MAX_SCRIPT_BYTES = 64 * 1024
MAX_SHEBANG_BYTES = 256
_SAFE_PATH = re.compile(r"/[A-Za-z0-9_+./-]{1,4095}")


def _same_file(a: str | None, b: str | None) -> bool | None:
    """Compare binary AND environment-selecting parent directory, never exec."""
    if not a or not b or not isinstance(a, str) or not isinstance(b, str):
        return None
    if _SAFE_PATH.fullmatch(a) is None or _SAFE_PATH.fullmatch(b) is None:
        return None
    try:
        left, right = os.stat(a), os.stat(b)
        # Crucial: two independent venv/bin/python symlinks can resolve to
        # the SAME base Python binary, but the entrypoint's parent directory
        # is what selects pyvenv.cfg and sys.prefix. A shared inode by itself
        # therefore cannot establish environment identity.
        left_parent = os.stat(os.path.dirname(a))
        right_parent = os.stat(os.path.dirname(b))
    except (OSError, ValueError, TypeError):
        return None
    if (not stat.S_ISREG(left.st_mode) or not stat.S_ISREG(right.st_mode)
            or not stat.S_ISDIR(left_parent.st_mode)
            or not stat.S_ISDIR(right_parent.st_mode)):
        return None
    return ((left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)
            and (left_parent.st_dev, left_parent.st_ino)
            == (right_parent.st_dev, right_parent.st_ino)
            # Keep the environment-selecting directory spelling stable too:
            # two differently named aliases to the same dir must not silently
            # claim equivalent sys.prefix/pyvenv.cfg resolution.
            and os.path.normpath(os.path.dirname(a))
            == os.path.normpath(os.path.dirname(b)))


def _read_shebang(path: str) -> tuple[str, ...] | None:
    """Safely read only an explicitly selected bounded, regular script."""
    if not isinstance(path, str) or _SAFE_PATH.fullmatch(path) is None:
        return None
    directory, base = os.path.split(path)
    if not directory or not base or base in (".", ".."):
        return None
    fd = -1
    try:
        fd = _open_directory_no_follow(directory)
        _, _, raw = _fingerprint(fd, base, MAX_SCRIPT_BYTES, contents=True)
        if not raw or not raw.startswith(b"#!"):
            return None
        line = raw.split(b"\n", 1)[0]
        if len(line) > MAX_SHEBANG_BYTES or b"\r" in line or b"\x00" in line:
            return None
        # Shebangs with interpreter flags, env -S, quoted/relative paths or
        # shell wrappers are deliberately unsupported instead of assumed.
        tokens = line[2:].decode("ascii").split()
        if len(tokens) not in (1, 2):
            return None
        if _SAFE_PATH.fullmatch(tokens[0]) is None:
            return None
        if len(tokens) == 2:
            if tokens[0] != "/usr/bin/env" or tokens[1] not in (
                    "python", "python3", "python3.10", "python3.11"):
                return None
        return tuple(tokens)
    except (OSError, UnicodeError, _UnsafeEvidence, _InvalidInventory,
            ValueError, TypeError, RuntimeError):
        return None
    finally:
        if fd >= 0:
            os.close(fd)


def _uvicorn_identity(path: str | None, selected: str) -> str:
    script = _read_shebang(path) if path else None
    if not script:
        return "UNVERIFIABLE" if path else "UNAVAILABLE"
    if len(script) == 1:
        same = _same_file(script[0], selected)
        if same is None:
            return "UNVERIFIABLE"
        return "DIRECT_MATCH" if same else "MISMATCH"
    # In exactly #!/usr/bin/env python*, PATH resolves the interpreter at
    # launch time. Check that specific executable, not a hypothetical Python.
    target = shutil.which(script[1])
    same = _same_file(target, selected)
    if same is None:
        return "UNVERIFIABLE"
    return "ENV_MATCH" if same else "MISMATCH"


def observe(*, selected: str | None = None,
            python_path: str | None = None,
            uvicorn_path: str | None = None) -> dict[str, object]:
    selected = sys.executable if selected is None else selected
    python_path = shutil.which("python") if python_path is None else python_path
    uvicorn_path = shutil.which("uvicorn") if uvicorn_path is None else uvicorn_path
    same = _same_file(python_path, selected)
    py_status = "UNVERIFIABLE" if same is None else ("MATCH" if same else "MISMATCH")
    uv_status = _uvicorn_identity(uvicorn_path, selected)
    active_user_site = (
        site.ENABLE_USER_SITE is True
        and not sys.flags.no_user_site
        and isinstance(site.getusersitepackages(), str)
        and site.getusersitepackages() in sys.path
    )
    ok = py_status == "MATCH" and uv_status in ("DIRECT_MATCH", "ENV_MATCH")
    if ok:
        reason = "static_launcher_interpreter_identity_matches_only"
    elif py_status == "MISMATCH":
        reason = "path_python_selected_interpreter_mismatch"
    elif uv_status == "MISMATCH":
        reason = "uvicorn_shebang_selected_interpreter_mismatch"
    else:
        reason = "static_launcher_interpreter_identity_unverifiable"
    return {
        "schema": SCHEMA, "scope": SCOPE,
        "status": "PASS_PARTIAL" if ok else "INCOMPLETE",
        "reason": reason,
        "path_python_identity": py_status,
        "uvicorn_shebang_identity": uv_status,
        "selected_python_user_site_active": active_user_site,
        "api_worker_runtime_verified": False,
        "actual_service_uid_verified": False,
        "running_process_verified": False,
        "package_imports": "NOT_TESTED",
        "native_odbc_load": "NOT_TESTED",
        "production_release_ready": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = observe()
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0 if result["status"] == "PASS_PARTIAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
