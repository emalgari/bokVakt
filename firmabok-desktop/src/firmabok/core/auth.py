"""Local authentication for the desktop app (optional app password).

The password hash lives in settings.json (auth.*). scrypt + per-user salt,
constant-time compare — same scheme as the reference web app.
"""
from __future__ import annotations

import hashlib
import hmac
import os

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return dk.hex(), salt.hex()


def verify_password(password: str, password_hash: str, salt_hex: str) -> bool:
    if not password_hash or not salt_hex:
        return False
    try:
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), password_hash)
