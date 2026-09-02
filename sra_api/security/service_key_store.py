from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
from threading import RLock

from .file_lock import exclusive_file_lock
from .scopes import validate_scopes


class ServiceKeyStoreError(RuntimeError):
    pass


class ServiceKeyStore:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("SRA_SERVICE_KEYS_FILE", ".sra_service_keys.json"))
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock = RLock()

    def _read(self):
        if not self.path.exists(): return {"version": 1, "keys": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ServiceKeyStoreError("Service key store is invalid") from exc
        if data.get("version") != 1 or not isinstance(data.get("keys"), list):
            raise ServiceKeyStoreError("Service key store is invalid")
        return data

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            os.chmod(tmp, 0o600); os.replace(tmp, self.path); os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    @staticmethod
    def _public(item):
        return {k: v for k, v in item.items() if k != "token_digest"}

    @staticmethod
    def _expires(value):
        if value is None or value == "":
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("expires_at must be a timezone-aware ISO 8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        return parsed.astimezone(timezone.utc).isoformat()

    def create(self, name, scopes, created_by, expires_at=None):
        scopes = validate_scopes(scopes)
        name = str(name).strip()
        if not name:
            raise ValueError("Service key name must not be empty")
        expires_at = self._expires(expires_at)
        key_id = secrets.token_hex(8)
        raw = f"sra_sk_{key_id}_{secrets.token_urlsafe(32)}"
        now = datetime.now(timezone.utc).isoformat()
        item = {"key_id": key_id, "name": name, "token_digest": hashlib.sha256(raw.encode()).hexdigest(),
                "scopes": sorted(scopes), "status": "active", "created_at": now, "created_by": created_by,
                "expires_at": expires_at, "revoked_at": None, "revoked_by": None, "hint": raw[-4:]}
        with self._lock, exclusive_file_lock(self.lock_path):
            data = self._read(); data["keys"].append(item); self._write(data)
        return self._public(item), raw

    def list_keys(self):
        with self._lock, exclusive_file_lock(self.lock_path):
            return [self._public(x) for x in self._read()["keys"]]

    def resolve(self, raw):
        if not isinstance(raw, str) or not raw.startswith("sra_sk_"): return None
        digest = hashlib.sha256(raw.encode()).hexdigest(); now = datetime.now(timezone.utc)
        with self._lock, exclusive_file_lock(self.lock_path): data = self._read()
        for item in data["keys"]:
            if hmac.compare_digest(str(item.get("token_digest", "")), digest):
                if item.get("status") != "active": return None
                try:
                    expires = self._expires(item.get("expires_at"))
                except ValueError:
                    return None
                if expires and datetime.fromisoformat(expires) <= now: return None
                return self._public(item)
        return None

    def revoke(self, key_id, revoked_by):
        with self._lock, exclusive_file_lock(self.lock_path):
            data = self._read(); found = None
            for item in data["keys"]:
                if item.get("key_id") == key_id:
                    item["status"] = "revoked"; item["revoked_by"] = revoked_by
                    item["revoked_at"] = datetime.now(timezone.utc).isoformat(); found = item; break
            if found is None: raise KeyError(key_id)
            self._write(data); return self._public(found)


SERVICE_KEY_STORE = ServiceKeyStore()
