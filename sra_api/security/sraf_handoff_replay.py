"""Durable single-use handoff proof for the private backend contract.

Explicit initialization only; no application mount or user credential creation.
All processes accepting an issuer/audience must use the SAME durable DB.
Never restore an old replay DB while old assertions remain acceptable.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from api.security.sraf_handoff_assertion import (
    HandoffDenied, HandoffTrust, VerifiedChatAssertion, verify_chat_assertion,
)


@dataclass(frozen=True, repr=False)
class ConsumedChatAssertion:
    """Internal verified-and-consumed receipt, not an AuthPrincipal."""
    assertion: VerifiedChatAssertion


class HandoffReplayStore:
    def __init__(self, db_path: Path, *, max_active: int = 10000):
        if type(max_active) is not int or not 1 <= max_active <= 100000:
            raise HandoffDenied("handoff_replay_unavailable")
        self._path = Path(db_path).resolve()
        self._max_active = max_active

    def initialize(self) -> None:
        """Operator-only schema setup in an existing private DB directory."""
        try:
            with closing(sqlite3.connect(self._path, timeout=5)) as con, con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("CREATE TABLE IF NOT EXISTS sraf_handoff_clock_v1 ("
                            "namespace TEXT PRIMARY KEY, watermark INTEGER NOT NULL)")
                con.execute("CREATE TABLE IF NOT EXISTS sraf_handoff_nonce_v1 ("
                            "namespace TEXT NOT NULL, nonce_hash TEXT NOT NULL, "
                            "expires_at INTEGER NOT NULL, PRIMARY KEY(namespace,nonce_hash))")
                con.execute("CREATE INDEX IF NOT EXISTS sraf_handoff_nonce_exp_v1 "
                            "ON sraf_handoff_nonce_v1(namespace,expires_at)")
        except sqlite3.Error:
            raise HandoffDenied("handoff_replay_unavailable") from None

    def require_ready(self) -> None:
        """Read-only schema check; never creates a missing replay database."""
        expected = {
            "sraf_handoff_clock_v1": [
                ("namespace", "TEXT", 1), ("watermark", "INTEGER", 0)],
            "sraf_handoff_nonce_v1": [
                ("namespace", "TEXT", 1), ("nonce_hash", "TEXT", 2),
                ("expires_at", "INTEGER", 0)],
        }
        try:
            with closing(sqlite3.connect(self._path.as_uri() + "?mode=ro",
                                         uri=True, timeout=5)) as con:
                for table, columns in expected.items():
                    rows = con.execute("PRAGMA table_info(" + table + ")").fetchall()
                    if [(row[1], row[2].upper(), row[5]) for row in rows] != columns:
                        raise HandoffDenied("handoff_replay_unavailable")
                if not con.execute("SELECT 1 FROM sqlite_master WHERE "
                                   "type='index' AND name='sraf_handoff_nonce_exp_v1' "
                                   "AND tbl_name='sraf_handoff_nonce_v1'").fetchone():
                    raise HandoffDenied("handoff_replay_unavailable")
        except sqlite3.Error:
            raise HandoffDenied("handoff_replay_unavailable") from None

    def initialize_new(self) -> None:
        """Explicit first-time operator action only; never reset an existing DB."""
        try:
            fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except OSError:
            raise HandoffDenied("handoff_replay_create_denied") from None
        # A partial initialization remains visible as a failure, not a silent
        # recreation of a database which might contain consumed assertions.
        self.initialize()
        self.require_ready()

    def verify_once(self, trust: HandoffTrust, token: str, *, body: bytes,
                    method: str, path: str, now: int | None = None) -> ConsumedChatAssertion:
        """Verify exact bytes, then atomically claim once, or fail closed.

        No raw assertion, subject, account, question, key or body stored.
        The optional clock parameter is trusted test/internal input only.
        """
        clock = int(time.time()) if now is None else now
        assertion = verify_chat_assertion(trust, token, body=body, method=method,
                                          path=path, now=clock)
        ns = hashlib.sha256(json.dumps([assertion.issuer, assertion.audience],
                            separators=(",", ":")).encode("ascii")).hexdigest()
        nonce = hashlib.sha256(assertion.nonce.encode("ascii")).hexdigest()
        try:
            # mode=rw: never silently recreate a missing replay database.
            uri = self._path.as_uri() + "?mode=rw"
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as con, con:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute("SELECT watermark FROM sraf_handoff_clock_v1 "
                                  "WHERE namespace=?", (ns,)).fetchone()
                # Never regress the expiry watermark after clock correction.
                effective = max(clock, row[0]) if row else clock
                if assertion.expires_at <= effective:
                    raise HandoffDenied("handoff_replay_denied")
                con.execute("DELETE FROM sraf_handoff_nonce_v1 "
                            "WHERE namespace=? AND expires_at<=?", (ns, effective))
                count = con.execute("SELECT COUNT(*) FROM sraf_handoff_nonce_v1 "
                                    "WHERE namespace=?", (ns,)).fetchone()[0]
                if count >= self._max_active:
                    raise HandoffDenied("handoff_replay_capacity")
                con.execute("INSERT INTO sraf_handoff_nonce_v1 "
                            "(namespace,nonce_hash,expires_at) VALUES (?,?,?)",
                            (ns, nonce, assertion.expires_at))
                con.execute("INSERT INTO sraf_handoff_clock_v1(namespace,watermark) VALUES (?,?) "
                            "ON CONFLICT(namespace) DO UPDATE SET watermark=excluded.watermark",
                            (ns, effective))
        except sqlite3.IntegrityError:
            raise HandoffDenied("handoff_replay_denied") from None
        except sqlite3.Error:
            raise HandoffDenied("handoff_replay_unavailable") from None
        return ConsumedChatAssertion(assertion)
