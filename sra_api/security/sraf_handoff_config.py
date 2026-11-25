"""Portable private receiver configuration; no startup, network or AuthStore IO.

An explicit operator file is the trust boundary. Relative paths are resolved
against its directory, not the host/IP or the service working directory.
Signing secrets live in separate restricted files, not JSON/Valve/URL/env values.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat

from api.security.sraf_handoff_assertion import HandoffDenied, HandoffKey, HandoffTrust
from api.security.sraf_handoff_mapping import ExternalAccountBinding, HandoffSubjectMap
from api.security.sraf_handoff_replay import HandoffReplayStore
from api.security.sraf_handoff_ingress import HandoffListener
from api.services.sraf_deep_startup_config import validate_chat_public_base

_B64 = re.compile(rb"[A-Za-z0-9_-]+\Z")


def _unique(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError
        obj[k] = v
    return obj


def _exact(obj, keys):
    if type(obj) is not dict or set(obj) != set(keys):
        raise ValueError
    return obj


def _path(root: Path, raw, *, exists: bool = True) -> Path:
    if (type(raw) is not str or not 1 <= len(raw) <= 4096
            or raw != raw.strip() or any(ord(c) < 32 or ord(c) == 127 for c in raw)):
        raise ValueError
    path = Path(raw)
    return (path if path.is_absolute() else root / path).resolve(strict=exists)


def _read(path: Path, limit: int, *, secret: bool = False) -> bytes:
    # No FIFO/device reads. Resolve and verify the opened file as well.
    if not path.is_file():
        raise ValueError
    with path.open("rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= limit:
            raise ValueError
        if secret and os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError
        data = handle.read(limit + 1)
        if not 1 <= len(data) <= limit:
            raise ValueError
        return data


def _key(root: Path, row) -> HandoffKey:
    _exact(row, ("id", "secret_file"))
    raw = _read(_path(root, row["secret_file"]), 256, secret=True).strip()
    if not _B64.fullmatch(raw):
        raise ValueError
    decoded = base64.b64decode(raw + b"=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(decoded).rstrip(b"=") != raw:
        raise ValueError
    return HandoffKey(row["id"], decoded)


@dataclass(frozen=True, repr=False)
class HandoffReceiverConfig:
    trust: HandoffTrust
    mapping: HandoffSubjectMap
    replay: HandoffReplayStore
    listener: HandoffListener
    public_base: str


def load_handoff_receiver_config(env: Mapping[str, str], *,
                                 project_root: Path, require_replay: bool = True) -> HandoffReceiverConfig | None:
    """Absent/0 flag reads nothing else. Invalid enabled configuration fails closed.

    require_replay=False is only for the explicit one-time initialization tool,
    not startup. Loading never creates/resets a replay DB or starts a listener.
    """
    flag = env.get("SRAF_HANDOFF_ENABLED", "0")
    if flag == "0":
        return None
    if flag != "1" or type(require_replay) is not bool:
        raise HandoffDenied("handoff_config_invalid")
    try:
        path = _path(project_root, env.get("SRAF_HANDOFF_CONFIG_FILE"))
        raw = _read(path, 262144)
        obj = _exact(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique),
                     ("schema", "issuer", "audience", "keys", "bindings",
                      "replay_db", "replay_max_active", "listener"))
        if obj["schema"] != "sraf_handoff_receiver_v1":
            raise ValueError
        if (type(obj["keys"]) is not list or not 1 <= len(obj["keys"]) <= 2
                or type(obj["bindings"]) is not list or not 1 <= len(obj["bindings"]) <= 256):
            raise ValueError
        root = path.parent
        trust = HandoffTrust(obj["issuer"], obj["audience"],
                             tuple(_key(root, key) for key in obj["keys"]))
        rows = []
        for item in obj["bindings"]:
            _exact(item, ("external_subject", "owner_id", "account_created_at"))
            rows.append(ExternalAccountBinding(trust.issuer, trust.audience,
                        item["external_subject"], item["owner_id"], item["account_created_at"]))
        mapping = HandoffSubjectMap(tuple(rows))
        listener = obj["listener"]
        if type(listener) is not dict:
            raise ValueError
        mode = listener.get("mode")
        if mode == "local_http":
            _exact(listener, ("mode", "bind_host", "port"))
            cert = key = None
        elif mode == "verified_https":
            _exact(listener, ("mode", "bind_host", "port", "cert_file", "key_file"))
            cert = _path(root, listener["cert_file"])
            key = _path(root, listener["key_file"])
        else:
            raise ValueError
        bind = HandoffListener(mode, listener["bind_host"], listener["port"], cert, key)
        db_path = _path(root, obj["replay_db"], exists=False)
        if not db_path.parent.is_dir() or (db_path.exists() and not db_path.is_file()):
            raise ValueError
        replay = HandoffReplayStore(db_path, max_active=obj["replay_max_active"])
        public_base = validate_chat_public_base(env.get("PUBLIC_API_BASE"))
        if require_replay:
            replay.require_ready()
        return HandoffReceiverConfig(trust, mapping, replay, bind, public_base)
    except HandoffDenied:
        raise
    except Exception:
        raise HandoffDenied("handoff_config_invalid") from None
