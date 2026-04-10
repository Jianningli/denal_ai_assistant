"""
dental_ai/auth/auth_store.py
==============================
User credential management using PBKDF2-HMAC-SHA256 for password hashing
and a separate salt for deriving per-user Fernet encryption keys.

Credential registry: ``history/users.json``

Each entry::

    {
        "display_name": str,   # original-casing username
        "auth_salt":    str,   # hex  — salt for password verification
        "auth_hash":    str,   # hex  — PBKDF2(password, auth_salt)
        "enc_salt":     str,   # hex  — salt for Fernet key derivation
    }
"""

import base64
import hashlib
import json
import secrets
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes as _crypto_hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

from dental_ai.core.history_store import HISTORY_ROOT, USERS_FILE

# ── PBKDF2 parameters ─────────────────────────────────────────────────────────
_PBKDF2_ITERS = 260_000
_PBKDF2_HASH  = "sha256"
_SALT_BYTES   = 32


# ── Low-level crypto helpers ──────────────────────────────────────────────────

def _pbkdf2_hash(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte hash from *password* + *salt* (stdlib only)."""
    return hashlib.pbkdf2_hmac(
        _PBKDF2_HASH, password.encode("utf-8"), salt, _PBKDF2_ITERS
    )


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """
    Derive a URL-safe base64-encoded 32-byte AES key suitable for Fernet.
    Uses a *different* salt than the auth hash so the two are independent.
    """
    if not ENCRYPTION_AVAILABLE:
        return b""
    kdf = PBKDF2HMAC(
        algorithm=_crypto_hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


# ── Credential store ──────────────────────────────────────────────────────────

class AuthStore:
    """Process-wide credential registry (singleton via :func:`get_auth_store`)."""

    def __init__(self) -> None:
        HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
        self._path = USERS_FILE
        self._data: dict = {}
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
            except Exception:
                self._data = {}

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)

    # ── public API ────────────────────────────────────────────────────────────

    def user_exists(self, username: str) -> bool:
        return username.lower() in self._data

    def register(self, username: str, password: str) -> bool:
        """Create a new account. Returns *False* if username already taken."""
        key = username.lower()
        if key in self._data:
            return False
        auth_salt = secrets.token_bytes(_SALT_BYTES)
        enc_salt  = secrets.token_bytes(_SALT_BYTES)
        auth_hash = _pbkdf2_hash(password, auth_salt)
        self._data[key] = {
            "display_name": username,
            "auth_salt":    auth_salt.hex(),
            "auth_hash":    auth_hash.hex(),
            "enc_salt":     enc_salt.hex(),
        }
        self._save()
        return True

    def verify(self, username: str, password: str) -> bool:
        """Return *True* iff *password* is correct for *username*."""
        entry = self._data.get(username.lower())
        if not entry:
            return False
        auth_salt = bytes.fromhex(entry["auth_salt"])
        stored    = bytes.fromhex(entry["auth_hash"])
        candidate = _pbkdf2_hash(password, auth_salt)
        return secrets.compare_digest(stored, candidate)  # constant-time

    def get_display_name(self, username: str) -> str:
        return self._data.get(username.lower(), {}).get("display_name", username)

    def fernet_key(self, username: str, password: str) -> Optional[bytes]:
        """Derive the Fernet encryption key for this user's history files."""
        entry = self._data.get(username.lower())
        if not entry:
            return None
        enc_salt = bytes.fromhex(entry["enc_salt"])
        return _derive_fernet_key(password, enc_salt)


# ── Singleton accessor ────────────────────────────────────────────────────────

_auth_store: Optional[AuthStore] = None


def get_auth_store() -> AuthStore:
    """Return the process-wide :class:`AuthStore` singleton."""
    global _auth_store
    if _auth_store is None:
        _auth_store = AuthStore()
    return _auth_store
