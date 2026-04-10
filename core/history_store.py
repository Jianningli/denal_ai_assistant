"""
dental_ai/core/history_store.py
=================================
Per-user, per-tool session store backed by a single file.

When the ``cryptography`` package is available **and** a Fernet key is
supplied, the file is written as Fernet-encrypted binary (.enc).
Falls back to plain JSON (.json) when encryption is unavailable.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

# Root folder for all per-user history
HISTORY_ROOT = Path("history")
USERS_FILE   = HISTORY_ROOT / "users.json"


def history_path(username: str, kind: str) -> Path:
    """
    Return ``history/<safe_username>/<safe_username>_<kind>.enc``
    (or ``.json`` when encryption is unavailable).
    The directory is created automatically.
    """
    safe   = re.sub(r"[^a-zA-Z0-9_\-]", "_", username.strip())
    folder = HISTORY_ROOT / safe
    folder.mkdir(parents=True, exist_ok=True)
    ext = ".enc" if ENCRYPTION_AVAILABLE else ".json"
    return folder / f"{safe}_{kind}{ext}"


class HistoryStore:
    """
    Generic session store for one (user, kind) combination.

    Each session entry::

        {
            "title":    str,
            "created":  ISO-8601 str,
            "messages": [{"role": ..., "content": ..., "ts": ...}, ...]
        }
    """

    def __init__(
        self,
        path: Path,
        username: str,
        kind: str,
        fernet_key: Optional[bytes] = None,
    ) -> None:
        self._path       = path
        self._username   = username
        self._kind       = kind
        self._fernet_key = fernet_key
        self._data: dict = {"username": username, "kind": kind, "sessions": {}}
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = self._path.read_bytes()
            if self._fernet_key and ENCRYPTION_AVAILABLE:
                raw = Fernet(self._fernet_key).decrypt(raw)
            loaded = json.loads(raw.decode("utf-8"))
            if (
                loaded.get("username") == self._username
                and loaded.get("kind") == self._kind
            ):
                self._data = loaded
        except Exception:
            pass  # wrong key / corrupted / legacy plain-text file

    def save(self) -> None:
        try:
            raw = json.dumps(
                self._data, ensure_ascii=False, indent=2
            ).encode("utf-8")
            if self._fernet_key and ENCRYPTION_AVAILABLE:
                raw = Fernet(self._fernet_key).encrypt(raw)
            self._path.write_bytes(raw)
        except Exception as exc:
            print(f"[HistoryStore:{self._kind}] save error: {exc}")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def all_sessions(self) -> dict:
        return self._data.get("sessions", {})

    def get_session(self, sid: str) -> Optional[dict]:
        return self._data["sessions"].get(sid)

    def upsert_session(
        self,
        sid: str,
        title: str,
        messages: list[dict],
        created: Optional[str] = None,
    ) -> None:
        existing = self._data["sessions"].get(sid, {})
        self._data["sessions"][sid] = {
            "title":    title,
            "created":  created or existing.get(
                "created", datetime.now().isoformat(timespec="seconds")
            ),
            "messages": messages,
        }
        self.save()

    def delete_session(self, sid: str) -> None:
        self._data["sessions"].pop(sid, None)
        self.save()

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        keyword: str,
        date_from: Optional[date] = None,
        date_to:   Optional[date] = None,
    ) -> list[dict]:
        """Full-text keyword search with optional date-range filter."""
        kw      = keyword.strip().lower()
        results: list[dict] = []

        for sid, session in self._data["sessions"].items():
            created_str = session.get("created", "")
            try:
                created_dt = datetime.fromisoformat(created_str).date()
            except ValueError:
                created_dt = None

            if date_from and created_dt and created_dt < date_from:
                continue
            if date_to   and created_dt and created_dt > date_to:
                continue

            for idx, msg in enumerate(session.get("messages", [])):
                content_lower = msg["content"].lower()
                if kw and kw not in content_lower:
                    continue

                pos   = content_lower.find(kw) if kw else 0
                start = max(0, pos - 50)
                snip  = msg["content"][start: start + 160].replace("\n", " ")
                if start > 0:
                    snip = "…" + snip
                if start + 160 < len(msg["content"]):
                    snip += "…"

                results.append({
                    "sid":       sid,
                    "title":     session.get("title", sid),
                    "created":   created_str,
                    "msg_index": idx,
                    "role":      msg["role"],
                    "content":   msg["content"],
                    "snippet":   snip,
                    "keyword":   kw,
                    "kind":      self._kind,
                })

        results.sort(key=lambda r: r["created"], reverse=True)
        return results
