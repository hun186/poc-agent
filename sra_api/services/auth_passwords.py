from __future__ import annotations

import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 260_000


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("密碼至少需要 8 個字元。")


def _hash_password(password: str, *, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_s, salt, expected = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations_s),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


DUMMY_PASSWORD_HASH = _hash_password(
    "sra-auth-dummy-password-for-timing-balance",
    salt="0" * 32,
)
