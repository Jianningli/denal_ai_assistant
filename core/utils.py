"""
dental_ai/core/utils.py
========================
Pure helper functions with no UI or heavy-library dependencies.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import QLabel


def safe_json_parse(raw: str) -> dict:
    """Strip Markdown code fences then parse JSON."""
    return json.loads(re.sub(r"```(?:json)?|```", "", raw).strip())


def new_session_id() -> str:
    """Return a short UUID4 prefix suitable for session keys."""
    return str(uuid.uuid4())[:8]


def now_iso() -> str:
    """Return the current timestamp as an ISO-8601 string (seconds precision)."""
    return datetime.now().isoformat(timespec="seconds")


def heading_label(text: str, color: str = "#0f172a") -> QLabel:
    """Return a styled heading QLabel (font-size 18 px, bold)."""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size:18px;font-weight:700;color:{color};margin-bottom:4px;"
    )
    return lbl
