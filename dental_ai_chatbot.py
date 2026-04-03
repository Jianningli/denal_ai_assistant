"""
Dental AI Assistant — PyQt6 Desktop Application  v3
=====================================================
New in this version
-------------------
1. Excel Analysis & Ask Your Document both use a full chat-style interface:
     - Scrollable message bubbles accumulate Q&A without clearing
     - Each tool has its own session sidebar (New / Rename / Delete)
     - Export current session → PDF button in every panel

2. Separate per-user JSON history files:
     - {username}_chat.json    — regular chat sessions
     - {username}_excel.json   — Excel Q&A sessions
     - {username}_rag.json     — RAG / Ask Your Document sessions

3. User isolation: every HistoryStore is scoped to the logged-in user,
   so Dr. Smith never sees Dr. Jones's conversations.

4. Global Search (Ctrl+F) searches across all three stores for the
   current user.
"""

# ── stdlib ────────────────────────────────────────────────────────────────────
import base64
import io
import json
import re
import sys
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ── third-party ───────────────────────────────────────────────────────────────
import faiss
import numpy as np
import ollama
import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# ── PyQt6 ─────────────────────────────────────────────────────────────────────
from PyQt6.QtCore import QDate, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QColor, QKeySequence, QPixmap, QTextCharFormat
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QFileDialog, QFrame,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTextEdit,
    QToolBar, QVBoxLayout, QWidget,
)

# ── constants ─────────────────────────────────────────────────────────────────
CHAT_MODEL       = "personaldentalassistantadvanced_xml"
GENERAL_MODEL    = "llama3:8b"
IMAGE_MODEL      = "gemma4:e4b"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
CHUNK_SIZE       = 500
RAG_TOP_K        = 3
MAX_CONTEXT_CHARS = 5_000

TOOL_STATUS = {
    0: ("💬 Chat",                CHAT_MODEL),
    1: ("📄 PDF Summary",         GENERAL_MODEL),
    2: ("🌐 Website Summary",     GENERAL_MODEL),
    3: ("📊 Excel Analysis",      GENERAL_MODEL),
    4: ("🧠 Ask Your Document",   GENERAL_MODEL),
    5: ("🦷 Dental Image Analysis", IMAGE_MODEL),
}

# System prompt for the image analysis model
IMAGE_SYSTEM_PROMPT = """You are a dental imaging assistant powered by AI. Your role is to help describe and explain features visible in dental images such as X-rays, photographs, or scans.

IMPORTANT DISCLAIMERS — you must follow these at all times:
• You are NOT a licensed dentist or medical professional.
• Your observations are for EDUCATIONAL and INFORMATIONAL purposes ONLY.
• Nothing you say constitutes a medical diagnosis, clinical opinion, or treatment recommendation.
• Always advise the user to consult a qualified dental professional for any clinical decisions.
• Do NOT make definitive statements about disease presence, severity, or prognosis.
• If the image quality is poor or the findings are ambiguous, say so clearly.

When describing an image:
1. Describe what you can objectively observe (e.g., visible structures, regions of interest, tonal differences).
2. Note any areas that may warrant professional attention, using cautious language ("appears to show…", "may suggest…", "could indicate…").
3. End every response with a reminder to consult a dentist or dental specialist.
"""

# ── palette ───────────────────────────────────────────────────────────────────
TEAL        = "#0d9488"
TEAL_LIGHT  = "#ccfbf1"
TEAL_DARK   = "#0f766e"
BG          = "#f8fafc"
SURFACE     = "#ffffff"
BORDER      = "#e2e8f0"
TEXT        = "#0f172a"
MUTED       = "#64748b"
DANGER      = "#ef4444"
WARNING_CLR = "#f59e0b"
SUCCESS     = "#10b981"
HIGHLIGHT   = "#fef08a"

APP_STYLESHEET = f"""
QWidget {{
    font-family: 'Segoe UI', 'DM Sans', Arial, sans-serif;
    font-size: 13px; color: {TEXT}; background-color: {BG};
}}
QMainWindow, QDialog {{ background-color: {BG}; }}
#sidebar {{
    background-color: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QPushButton {{
    background-color: {TEAL}; color: white; border: none;
    border-radius: 8px; padding: 7px 16px;
    font-weight: 600; font-size: 13px;
}}
QPushButton:hover   {{ background-color: {TEAL_DARK}; }}
QPushButton:disabled {{ background-color: #94a3b8; }}
QPushButton#secondary {{
    background-color: {SURFACE}; color: {TEAL};
    border: 1px solid {TEAL};
}}
QPushButton#secondary:hover {{ background-color: {TEAL_LIGHT}; }}
QPushButton#danger {{
    background-color: {DANGER};
}}
/* Scope-toggle buttons in Search dialog */
QPushButton#scopeBtn {{
    background-color: {SURFACE}; color: {MUTED};
    border: 1px solid {BORDER};
    border-radius: 8px; padding: 4px 12px; font-weight: 500;
}}
QPushButton#scopeBtn:hover {{
    background-color: {TEAL_LIGHT}; color: {TEAL_DARK};
    border-color: {TEAL};
}}
QPushButton#scopeBtn:checked {{
    background-color: {TEAL}; color: white;
    border: 1px solid {TEAL_DARK};
}}
/* Buttons inside a ctrl strip widget must not inherit the strip background */
QWidget#ctrlStrip QPushButton {{
    background-color: {TEAL}; color: white; border: none;
    border-radius: 8px; padding: 7px 16px;
    font-weight: 600; font-size: 13px;
}}
QWidget#ctrlStrip QPushButton:hover   {{ background-color: {TEAL_DARK}; }}
QWidget#ctrlStrip QPushButton:disabled {{ background-color: #94a3b8; }}
QLineEdit, QTextEdit, QComboBox, QDateEdit {{
    background-color: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px 10px;
    selection-background-color: {TEAL_LIGHT};
}}
QLineEdit:focus, QTextEdit:focus {{ border: 1.5px solid {TEAL}; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    border: none; padding-right: 8px;
}}
QListWidget {{
    background-color: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; outline: none;
}}
QListWidget::item {{ padding: 7px 10px; border-radius: 6px; }}
QListWidget::item:selected {{
    background-color: {TEAL_LIGHT}; color: {TEAL_DARK};
}}
QListWidget::item:hover {{ background-color: #f1f5f9; }}
QScrollBar:vertical {{
    background: {BG}; width: 8px; border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: #cbd5e1; border-radius: 4px; min-height: 20px;
}}
QProgressBar {{
    background-color: {BORDER}; border-radius: 5px;
    height: 10px; text-align: center;
}}
QProgressBar::chunk {{ background-color: {TEAL}; border-radius: 5px; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px;
    padding: 10px; margin-top: 8px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; color: {MUTED};
}}
QSplitter::handle {{ background: {BORDER}; width: 4px; height: 4px; }}
QStatusBar {{
    background: {SURFACE}; border-top: 1px solid {BORDER};
    color: {MUTED}; font-size: 12px;
}}
QToolBar {{
    background: {SURFACE}; border-bottom: 1px solid {BORDER};
    spacing: 4px; padding: 2px 8px;
}}
QToolBar QToolButton {{
    background: transparent; border: none;
    border-radius: 6px; padding: 4px 12px;
    color: {TEXT}; font-size: 12px;
}}
QToolBar QToolButton:hover {{
    background: {TEAL_LIGHT}; color: {TEAL_DARK};
}}
"""


# =============================================================================
# PERSISTENT HISTORY  — per-user, per-tool JSON store
# =============================================================================

def _history_path(username: str, kind: str) -> Path:
    """
    Returns:  history/<safe_username>/<safe_username>_<kind>.json
    The directory is created automatically if it does not exist.
    """
    safe    = re.sub(r"[^a-zA-Z0-9_\-]", "_", username.strip())
    folder  = Path("history") / safe
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{safe}_{kind}.json"


class HistoryStore:
    """
    Generic session store backed by a single JSON file.

    Schema:
    {
      "username": "<name>",
      "kind":     "chat" | "excel" | "rag",
      "sessions": {
        "<sid>": {
          "title":    "Session title",
          "created":  "ISO-8601",
          "messages": [
            {"role": "user"|"assistant", "content": "...", "ts": "ISO-8601"}
          ]
        }
      }
    }
    """

    def __init__(self, path: Path, username: str, kind: str):
        self._path     = path
        self._username = username
        self._kind     = kind
        self._data: dict = {"username": username, "kind": kind, "sessions": {}}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Safety: only accept data that belongs to this user+kind
                if (loaded.get("username") == self._username and
                        loaded.get("kind") == self._kind):
                    self._data = loaded
            except Exception:
                pass

    def save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[HistoryStore:{self._kind}] save error: {e}")

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def all_sessions(self) -> dict:
        return self._data.get("sessions", {})

    def get_session(self, sid: str) -> Optional[dict]:
        return self._data["sessions"].get(sid)

    def upsert_session(self, sid: str, title: str,
                       messages: list[dict],
                       created: Optional[str] = None):
        existing = self._data["sessions"].get(sid, {})
        self._data["sessions"][sid] = {
            "title":    title,
            "created":  created or existing.get(
                "created", datetime.now().isoformat(timespec="seconds")),
            "messages": messages,
        }
        self.save()

    def delete_session(self, sid: str):
        self._data["sessions"].pop(sid, None)
        self.save()

    # ── Search ───────────────────────────────────────────────────────────────

    def search(self,
               keyword: str,
               date_from: Optional[date] = None,
               date_to:   Optional[date] = None) -> list[dict]:
        kw = keyword.strip().lower()
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
                    "kind":      self._kind,  # 'chat' | 'excel' | 'rag'
                })

        results.sort(key=lambda r: r["created"], reverse=True)
        return results


# =============================================================================
# WORKER THREADS
# =============================================================================

class ChatWorker(QThread):
    token_received = pyqtSignal(str)
    finished       = pyqtSignal(str)
    error          = pyqtSignal(str)

    def __init__(self, model: str, messages: list[dict]):
        super().__init__()
        self.model    = model
        self.messages = messages

    def run(self):
        full = ""
        try:
            stream = ollama.chat(
                model=self.model, messages=self.messages, stream=True)
            for chunk in stream:
                token = chunk["message"]["content"]
                full += token
                self.token_received.emit(token)
        except ollama.ResponseError as e:
            self.error.emit(f"Model error: {e.error}")
            return
        except Exception as e:
            self.error.emit(str(e))
            return
        self.finished.emit(full)


class OllamaWorker(QThread):
    result = pyqtSignal(str)
    error  = pyqtSignal(str)

    def __init__(self, model: str, prompt: str):
        super().__init__()
        self.model  = model
        self.prompt = prompt

    def run(self):
        try:
            resp = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": self.prompt}])
            self.result.emit(resp["message"]["content"])
        except Exception as e:
            self.error.emit(str(e))


class FetchWebWorker(QThread):
    result = pyqtSignal(str)
    error  = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; DentalAI/1.0)"}
            r = requests.get(self.url, headers=headers, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            main = soup.find("article") or soup.find("main") or soup
            text = " ".join(
                p.get_text(" ", strip=True) for p in main.find_all("p"))
            self.result.emit(text[:MAX_CONTEXT_CHARS])
        except requests.exceptions.Timeout:
            self.error.emit("Request timed out.")
        except requests.exceptions.HTTPError as e:
            self.error.emit(f"HTTP error: {e}")
        except Exception as e:
            self.error.emit(str(e))


class RagIndexWorker(QThread):
    done  = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, file_paths: list[str]):
        super().__init__()
        self.file_paths = file_paths

    def run(self):
        try:
            model = _get_embed_model()
            chunks, meta = [], []
            for path in self.file_paths:
                fname = Path(path).name
                with pdfplumber.open(path) as pdf:
                    for pn, page in enumerate(pdf.pages):
                        text = page.extract_text()
                        if not text:
                            continue
                        for i in range(0, len(text), CHUNK_SIZE):
                            c = text[i: i + CHUNK_SIZE].strip()
                            if c:
                                chunks.append(c)
                                meta.append({"source": fname, "page": pn + 1})
            if not chunks:
                self.error.emit("No readable text found.")
                return
            embeddings = model.encode(chunks, show_progress_bar=False)
            index = faiss.IndexFlatL2(embeddings.shape[1])
            index.add(np.array(embeddings, dtype="float32"))
            self.done.emit({
                "chunks": chunks, "metadata": meta,
                "index": index, "embeddings": embeddings,
            })
        except Exception as e:
            self.error.emit(str(e))


class ImageAnalysisWorker(QThread):
    """
    Sends one image (as base64) plus a text question to the multimodal
    Ollama model.  Uses a system-prompt message prepended to the conversation.
    """
    result = pyqtSignal(str)
    error  = pyqtSignal(str)

    def __init__(self, image_path: str, question: str,
                 history: list[dict]):
        """
        history  — previous {role, content} turns (text-only) for context.
        image_path — path to the image file to include in THIS turn.
        question   — user's text question for this turn.
        """
        super().__init__()
        self.image_path = image_path
        self.question   = question
        self.history    = history   # prior turns, no images (model context)

    def run(self):
        try:
            # Read and base64-encode the image
            img_data = Path(self.image_path).read_bytes()
            b64      = base64.b64encode(img_data).decode("utf-8")

            # Build message list:
            #   [system, ...history_text_only, user_with_image]
            messages = [
                {"role": "system", "content": IMAGE_SYSTEM_PROMPT},
            ]
            # Append previous text turns for context (no images — most
            # vision models only accept one image at a time)
            for m in self.history:
                messages.append({"role": m["role"], "content": m["content"]})

            # Current user turn carries the image
            messages.append({
                "role":    "user",
                "content": self.question,
                "images":  [b64],
            })

            resp = ollama.chat(model=IMAGE_MODEL, messages=messages)
            self.result.emit(resp["message"]["content"])
        except FileNotFoundError:
            self.error.emit(f"Image file not found: {self.image_path}")
        except ollama.ResponseError as e:
            self.error.emit(f"Model error: {e.error}")
        except Exception as e:
            self.error.emit(str(e))

_embed_model: Optional[SentenceTransformer] = None

def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def safe_json_parse(raw: str) -> dict:
    return json.loads(re.sub(r"```(?:json)?|```", "", raw).strip())


def new_session_id() -> str:
    return str(uuid.uuid4())[:8]


def _heading(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size:18px;font-weight:700;color:{TEXT};margin-bottom:4px;")
    return lbl


def export_session_to_pdf(title: str, messages: list[dict],
                           subtitle: str = "") -> bytes:
    """Render any list of {role, content} messages as a styled PDF."""
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=20*mm, rightMargin=20*mm,
                             topMargin=20*mm, bottomMargin=20*mm)
    stls = getSampleStyleSheet()
    teal = colors.HexColor("#0d9488")

    story = [
        Paragraph("🦷 Dental AI Assistant",
                  ParagraphStyle("T", parent=stls["Title"],
                                 textColor=teal, fontSize=18, spaceAfter=4)),
        Paragraph(f"Session: <b>{title}</b>" +
                  (f"  <i>({subtitle})</i>" if subtitle else ""),
                  ParagraphStyle("M", parent=stls["Normal"],
                                 textColor=colors.HexColor("#64748b"),
                                 fontSize=9, spaceAfter=4)),
        Paragraph(f"Exported: {datetime.now().strftime('%d %b %Y, %H:%M')}",
                  ParagraphStyle("M2", parent=stls["Normal"],
                                 textColor=colors.HexColor("#64748b"),
                                 fontSize=9, spaceAfter=12)),
        HRFlowable(width="100%", color=teal, thickness=1, spaceAfter=12),
    ]

    lbl_s = ParagraphStyle("L", parent=stls["Normal"], fontSize=8,
                            textColor=colors.HexColor("#94a3b8"), spaceAfter=2)
    usr_s = ParagraphStyle("U", parent=stls["Normal"],
                            backColor=colors.HexColor("#ccfbf1"),
                            borderPadding=(6, 8, 6, 8),
                            fontSize=10, leading=14, spaceAfter=8)
    ast_s = ParagraphStyle("A", parent=stls["Normal"],
                            backColor=colors.HexColor("#f1f5f9"),
                            borderPadding=(6, 8, 6, 8),
                            fontSize=10, leading=14, spaceAfter=8)

    for msg in messages:
        c = (msg["content"]
             .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        # Strip internal role hints that may appear in excel/rag messages
        role = msg.get("role", "user")
        if role == "user":
            story += [Paragraph("You", lbl_s), Paragraph(c, usr_s)]
        else:
            story += [Paragraph("Dental AI", lbl_s), Paragraph(c, ast_s)]

    doc.build(story)
    return buf.getvalue()


# =============================================================================
# CHAT BUBBLE  (shared by Chat, Excel, RAG panels)
# =============================================================================

class ChatBubble(QFrame):
    def __init__(self, role: str, label_override: str = "",
                 text: str = "", parent=None):
        super().__init__(parent)
        is_user = role == "user"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)

        who = label_override or ("You" if is_user else "🦷 Dental AI")
        lbl = QLabel(who)
        lbl.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;")

        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.text_label.setStyleSheet(f"""
            background-color: {"#e0fdf4" if is_user else SURFACE};
            border: 1px solid {"#99f6e4" if is_user else BORDER};
            border-radius: 10px;
            padding: 10px 14px; font-size: 13px;
        """)
        self._base_style = self.text_label.styleSheet()

        wrapper = QVBoxLayout()
        wrapper.addWidget(lbl)
        wrapper.addWidget(self.text_label)
        wrapper.setSpacing(2)

        row = QHBoxLayout()
        if is_user:
            row.addStretch(); row.addLayout(wrapper)
        else:
            row.addLayout(wrapper); row.addStretch()
        lay.addLayout(row)

    def append_text(self, token: str):
        self.text_label.setText(self.text_label.text() + token)

    def flash_highlight(self):
        hi = self._base_style + f"border: 2px solid {TEAL};"
        self.text_label.setStyleSheet(hi)
        QTimer.singleShot(
            1600, lambda: self.text_label.setStyleSheet(self._base_style))


# =============================================================================
# GENERIC SESSION TAB  (base for Chat, Excel, RAG tabs)
# =============================================================================

class BaseSessionTab(QWidget):
    """
    Provides a scrollable bubble area + input row.
    Subclasses implement _handle_send(text) and call
    _add_bubble / _append_to_last_bubble / _finalize.
    """
    messages_changed = pyqtSignal()

    def __init__(self, session_id: str, title: str,
                 store: HistoryStore,
                 existing_messages: Optional[list[dict]] = None,
                 user_label: str = "You",
                 ai_label: str = "🦷 Dental AI",
                 placeholder: str = "Type your question…",
                 parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.title      = title
        self.store      = store
        self.messages: list[dict] = list(existing_messages or [])
        self._bubbles: list[ChatBubble] = []
        self._user_label = user_label
        self._ai_label   = ai_label

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.msg_container = QWidget()
        self.msg_layout    = QVBoxLayout(self.msg_container)
        self.msg_layout.addStretch()
        self.msg_layout.setSpacing(4)
        self.scroll.setWidget(self.msg_container)
        lay.addWidget(self.scroll, stretch=1)

        # input row
        inp = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText(placeholder)
        self.input_box.setMinimumHeight(38)
        self.input_box.returnPressed.connect(self._on_send_clicked)
        self.send_btn = QPushButton("Send ➤")
        self.send_btn.setFixedHeight(38)
        self.send_btn.clicked.connect(self._on_send_clicked)
        inp.addWidget(self.input_box); inp.addWidget(self.send_btn)
        lay.addLayout(inp)

        # Restore existing bubbles
        for msg in self.messages:
            lbl = self._user_label if msg["role"] == "user" else self._ai_label
            self._make_bubble(msg["role"], msg["content"], lbl)

    # ── bubble helpers ────────────────────────────────────────────────────────

    def _make_bubble(self, role: str, text: str,
                     label: str = "") -> ChatBubble:
        b = ChatBubble(role, label_override=label, text=text)
        self._bubbles.append(b)
        self.msg_layout.addWidget(b)
        QApplication.processEvents()
        self._scroll_bottom()
        return b

    def _scroll_bottom(self):
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum())

    def _set_enabled(self, v: bool):
        self.input_box.setEnabled(v)
        self.send_btn.setEnabled(v)

    def _persist(self):
        self.store.upsert_session(self.session_id, self.title, self.messages)
        self.messages_changed.emit()

    def scroll_to_message(self, idx: int):
        if 0 <= idx < len(self._bubbles):
            self.scroll.ensureWidgetVisible(self._bubbles[idx])
            self._bubbles[idx].flash_highlight()

    # Subclasses override this
    def _on_send_clicked(self):
        raise NotImplementedError

    def export_pdf(self, subtitle: str = "") -> Optional[bytes]:
        if not self.messages:
            return None
        return export_session_to_pdf(self.title, self.messages, subtitle)


# =============================================================================
# CHAT TAB  (plain conversation)
# =============================================================================

class ChatTab(BaseSessionTab):
    def __init__(self, session_id: str, title: str,
                 store: HistoryStore,
                 existing_messages: Optional[list[dict]] = None,
                 parent=None):
        super().__init__(session_id, title, store, existing_messages,
                         placeholder="Ask me anything about dental health…",
                         parent=parent)
        self._worker: Optional[ChatWorker]      = None
        self._current_bubble: Optional[ChatBubble] = None

    def _on_send_clicked(self):
        text = self.input_box.text().strip()
        if not text:
            return
        self.input_box.clear()
        self._set_enabled(False)

        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "user", "content": text, "ts": ts})
        self._make_bubble("user", text, self._user_label)

        self._current_bubble = self._make_bubble("assistant", "", self._ai_label)
        self._worker = ChatWorker(CHAT_MODEL, list(self.messages))
        self._worker.token_received.connect(self._on_token)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_token(self, token: str):
        if self._current_bubble:
            self._current_bubble.append_text(token)
            self._scroll_bottom()

    @pyqtSlot(str)
    def _on_finished(self, full: str):
        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "assistant", "content": full, "ts": ts})
        self._persist()
        self._set_enabled(True)
        self._current_bubble = None

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        if self._current_bubble:
            self._current_bubble.text_label.setText(f"⚠️ {msg}")
            self._current_bubble.text_label.setStyleSheet(
                f"background:{DANGER}22;border:1px solid {DANGER};"
                "border-radius:10px;padding:10px 14px;")
        self._set_enabled(True)


# =============================================================================
# EXCEL SESSION TAB  (one Q&A session against a loaded spreadsheet)
# =============================================================================

class ExcelSessionTab(BaseSessionTab):
    """
    Each session is tied to one Excel file.
    The file path is stored in the session metadata so it can be
    displayed on restore (but not re-analysed automatically).
    """

    def __init__(self, session_id: str, title: str,
                 store: HistoryStore,
                 existing_messages: Optional[list[dict]] = None,
                 excel_path: str = "",
                 parent=None):
        super().__init__(session_id, title, store, existing_messages,
                         ai_label="📊 Excel AI",
                         placeholder="Ask a question about the loaded spreadsheet…",
                         parent=parent)
        self._excel_path = excel_path
        self._xls: Optional[pd.ExcelFile] = None
        self._df:  Optional[pd.DataFrame] = None
        self._canvas: Optional["MatplotlibCanvas"] = None
        self._worker: Optional[OllamaWorker] = None
        self._current_bubble: Optional[ChatBubble] = None

        # Try to reload the file if a path was given
        if excel_path:
            self._try_load_excel(excel_path)

    def attach_canvas(self, canvas: "MatplotlibCanvas"):
        """Called by ExcelSessionPanel to give this tab access to the chart."""
        self._canvas = canvas

    def _try_load_excel(self, path: str):
        try:
            self._xls = pd.ExcelFile(path)
            self._excel_path = path
        except Exception:
            self._xls = None

    def load_sheet(self, sheet: str):
        if not self._xls:
            return
        try:
            self._df = pd.read_excel(self._xls, sheet_name=sheet)
        except Exception:
            pass

    def _build_context(self) -> str:
        if not self._xls:
            return ""
        budget = MAX_CONTEXT_CHARS // max(len(self._xls.sheet_names), 1)
        blocks = []
        for n in self._xls.sheet_names:
            try:
                df = pd.read_excel(self._xls, sheet_name=n)
                if not df.empty:
                    blocks.append(
                        f"=== Sheet: {n} ===\n"
                        f"{df.head(50).to_string()[:budget]}")
            except Exception:
                pass
        return "\n\n".join(blocks)

    def _on_send_clicked(self):
        question = self.input_box.text().strip()
        if not question:
            return
        if not self._xls:
            QMessageBox.warning(self, "No file",
                "Please load an Excel file first."); return

        self.input_box.clear()
        self._set_enabled(False)

        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "user", "content": question, "ts": ts})
        self._make_bubble("user", question, self._user_label)
        self._current_bubble = self._make_bubble("assistant", "⏳ Analysing…",
                                                  self._ai_label)

        # ── Chart (sync, quick) ────────────────────────────────────────────
        if self._df is not None and not self._df.empty and self._canvas:
            chart_prompt = (
                "You are a data analyst. Given column names and a user question, "
                "pick the single best chart.\n"
                "Respond ONLY with valid JSON, no markdown:\n"
                '{"x":"<col>","y":"<col>","chart_type":"bar" or "line"}\n\n'
                f"Columns: {list(self._df.columns)}\n"
                f"Question: {question}"
            )
            try:
                raw = ollama.chat(
                    model=GENERAL_MODEL,
                    messages=[{"role": "user", "content": chart_prompt}],
                )["message"]["content"]
                cj = safe_json_parse(raw)
                xc, yc, ct = cj.get("x"), cj.get("y"), cj.get("chart_type", "bar")
                if xc in self._df.columns and yc in self._df.columns:
                    if ct == "line":
                        self._canvas.plot_line(self._df, xc, yc, question[:55])
                    else:
                        self._canvas.plot_bar(self._df, xc, yc, question[:55])
                else:
                    self._canvas.show_message(
                        f"Columns '{xc}'/'{yc}' not found in sheet.")
            except Exception:
                self._canvas.show_message(
                    "Auto-chart not available for this question.")

        # ── LLM answer (async) ─────────────────────────────────────────────
        ctx = self._build_context()
        prompt = (
            "You have access to all sheets of an Excel workbook.\n"
            "Use data from any relevant sheet; state which sheet you draw from.\n\n"
            f"{ctx}\n\nQuestion:\n{question}"
        )
        self._worker = OllamaWorker(GENERAL_MODEL, prompt)
        self._worker.result.connect(self._on_answer)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_answer(self, text: str):
        if self._current_bubble:
            self._current_bubble.text_label.setText(text)
        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "assistant", "content": text, "ts": ts})
        self._persist()
        self._set_enabled(True)
        self._current_bubble = None
        self._scroll_bottom()

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        if self._current_bubble:
            self._current_bubble.text_label.setText(f"⚠️ {msg}")
            self._current_bubble.text_label.setStyleSheet(
                f"background:{DANGER}22;border:1px solid {DANGER};"
                "border-radius:10px;padding:10px 14px;")
        self._set_enabled(True)


# =============================================================================
# RAG SESSION TAB
# =============================================================================

class RagSessionTab(BaseSessionTab):
    def __init__(self, session_id: str, title: str,
                 store: HistoryStore,
                 existing_messages: Optional[list[dict]] = None,
                 parent=None):
        super().__init__(session_id, title, store, existing_messages,
                         ai_label="🧠 RAG AI",
                         placeholder="Ask a question about your indexed documents…",
                         parent=parent)
        self._rag_data: Optional[dict]        = None
        self._worker: Optional[OllamaWorker]  = None
        self._current_bubble: Optional[ChatBubble] = None
        # confidence bar shown at bottom of the tab
        self._build_conf_bar()

    def _build_conf_bar(self):
        conf_grp = QGroupBox("Relevance Score (last answer)")
        cl = QHBoxLayout(conf_grp)
        self.conf_bar = QProgressBar(); self.conf_bar.setRange(0, 100)
        self.conf_lbl = QLabel("—")
        cl.addWidget(self.conf_bar); cl.addWidget(self.conf_lbl)
        # Insert above the input row (which is the last item in the layout)
        self.layout().insertWidget(self.layout().count() - 1, conf_grp)

    def set_rag_data(self, data: dict):
        self._rag_data = data

    def _on_send_clicked(self):
        q = self.input_box.text().strip()
        if not q:
            return
        if not self._rag_data:
            QMessageBox.warning(self, "Not indexed",
                "Please index documents first."); return

        self.input_box.clear()
        self._set_enabled(False)

        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "user", "content": q, "ts": ts})
        self._make_bubble("user", q, self._user_label)
        self._current_bubble = self._make_bubble("assistant", "⏳ Thinking…",
                                                  self._ai_label)

        # RAG retrieval
        emb = _get_embed_model()
        qe  = emb.encode([q], show_progress_bar=False)
        _, idxs = self._rag_data["index"].search(
            np.array(qe, dtype="float32"), k=RAG_TOP_K)

        cks, mts, ems = [], [], []
        for i in idxs[0]:
            if i == -1: continue
            cks.append(self._rag_data["chunks"][i])
            mts.append(self._rag_data["metadata"][i])
            ems.append(self._rag_data["embeddings"][i])

        if not cks:
            if self._current_bubble:
                self._current_bubble.text_label.setText(
                    "No relevant chunks found.")
            self._set_enabled(True)
            return

        sims = cosine_similarity(qe, np.stack(ems))[0]
        conf = round(float(np.mean(sims)) * 100, 1)
        self.conf_bar.setValue(int(conf))
        if conf >= 75:
            clr, lbl = SUCCESS, "High ✅"
        elif conf >= 50:
            clr, lbl = WARNING_CLR, "Medium ⚠️"
        else:
            clr, lbl = DANGER, "Low ❌"
        self.conf_bar.setStyleSheet(
            f"QProgressBar::chunk{{background:{clr};border-radius:5px;}}")
        self.conf_lbl.setText(f"{conf}%  {lbl}")

        ctx = "\n\n".join(
            f"[Source {i+1} | {m['source']} | Page {m['page']}]\n{c}"
            for i, (c, m) in enumerate(zip(cks, mts)))
        prompt = (
            "Answer using ONLY the sources below. Cite like [Source 1].\n"
            "If not found say: \"I don't know based on the provided documents.\"\n\n"
            f"Sources:\n{ctx}\n\nQuestion:\n{q}")
        self._worker = OllamaWorker(GENERAL_MODEL, prompt)
        self._worker.result.connect(self._on_answer)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_answer(self, text: str):
        if self._current_bubble:
            self._current_bubble.text_label.setText(text)
        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "assistant", "content": text, "ts": ts})
        self._persist()
        self._set_enabled(True)
        self._current_bubble = None
        self._scroll_bottom()

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        if self._current_bubble:
            self._current_bubble.text_label.setText(f"⚠️ {msg}")
            self._current_bubble.text_label.setStyleSheet(
                f"background:{DANGER}22;border:1px solid {DANGER};"
                "border-radius:10px;padding:10px 14px;")
        self._set_enabled(True)


# =============================================================================
# GENERIC SESSION PANEL  (sidebar + session stack + export)
# Used by ChatPanel, ExcelSessionPanel, RagSessionPanel
# =============================================================================

class GenericSessionPanel(QWidget):
    """
    Left sidebar: session list + New / Rename / Delete / Export PDF.
    Right: QStackedWidget of session tabs.
    Subclasses provide _make_tab(sid, title, messages) → BaseSessionTab.
    """

    def __init__(self, store: HistoryStore,
                 sidebar_title: str = "Sessions",
                 parent=None):
        super().__init__(parent)
        self._store = store
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── sidebar ───────────────────────────────────────
        sb = QWidget(); sb.setObjectName("sidebar"); sb.setFixedWidth(215)
        sb_lay = QVBoxLayout(sb)
        sb_lay.setContentsMargins(10, 10, 10, 10); sb_lay.setSpacing(5)

        sb_lay.addWidget(QLabel(sidebar_title,
            styleSheet=f"font-weight:700;color:{TEXT};font-size:13px;"))

        new_btn = QPushButton("＋ New Session")
        new_btn.clicked.connect(self.create_session)
        sb_lay.addWidget(new_btn)

        self.session_list = QListWidget()
        self.session_list.currentRowChanged.connect(self._switch_session)
        sb_lay.addWidget(self.session_list, stretch=1)

        rename_btn = QPushButton("✏  Rename")
        rename_btn.setObjectName("secondary")
        rename_btn.clicked.connect(self._rename)
        sb_lay.addWidget(rename_btn)

        del_btn = QPushButton("🗑  Delete")
        del_btn.setObjectName("secondary")
        del_btn.clicked.connect(self._delete)
        sb_lay.addWidget(del_btn)

        self.export_btn = QPushButton("⬇  Export PDF")
        self.export_btn.setObjectName("secondary")
        self.export_btn.clicked.connect(self.export_current)
        sb_lay.addWidget(self.export_btn)

        lay.addWidget(sb)

        # ── session stack ─────────────────────────────────
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)

        # Load persisted history
        self._load_history()
        if self.stack.count() == 0:
            self.create_session()

    # ── must override ─────────────────────────────────────────────────────────

    def _make_tab(self, sid: str, title: str,
                   messages: list[dict]) -> BaseSessionTab:
        raise NotImplementedError

    def _new_session_title(self) -> str:
        return f"Session {self.stack.count() + 1}"

    # ── history ───────────────────────────────────────────────────────────────

    def _load_history(self):
        for sid, data in self._store.all_sessions().items():
            self._add_tab(sid,
                          data.get("title", sid),
                          data.get("messages", []))
        if self.session_list.count():
            self.session_list.setCurrentRow(0)

    def _add_tab(self, sid: str, title: str,
                  messages: list[dict]) -> BaseSessionTab:
        tab = self._make_tab(sid, title, messages)
        self.stack.addWidget(tab)
        item = QListWidgetItem(f"▸ {title}")
        item.setData(Qt.ItemDataRole.UserRole, sid)
        self.session_list.addItem(item)
        return tab

    # ── session ops ───────────────────────────────────────────────────────────

    def create_session(self):
        sid   = new_session_id()
        title = self._new_session_title()
        self._add_tab(sid, title, [])
        self._store.upsert_session(sid, title, [])
        self.session_list.setCurrentRow(self.session_list.count() - 1)

    def _switch_session(self, row: int):
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    def _current_tab(self) -> Optional[BaseSessionTab]:
        idx = self.stack.currentIndex()
        return self.stack.widget(idx) if idx >= 0 else None

    def _rename(self):
        tab = self._current_tab()
        if not tab:
            return
        new_title, ok = QInputDialog.getText(
            self, "Rename", "New title:", text=tab.title)
        if ok and new_title.strip():
            tab.title = new_title.strip()
            row = self.session_list.currentRow()
            self.session_list.item(row).setText(f"▸ {tab.title}")
            self._store.upsert_session(tab.session_id, tab.title, tab.messages)

    def _delete(self):
        row = self.session_list.currentRow()
        if row < 0:
            return
        tab: BaseSessionTab = self.stack.widget(row)
        if QMessageBox.question(
            self, "Delete", f"Delete '{tab.title}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self._store.delete_session(tab.session_id)
            self.stack.removeWidget(tab)
            self.session_list.takeItem(row)
            tab.deleteLater()

    def restore_session(self, sid: str, msg_index: int):
        for i in range(self.session_list.count()):
            if self.session_list.item(i).data(
                    Qt.ItemDataRole.UserRole) == sid:
                self.session_list.setCurrentRow(i)
                QApplication.processEvents()
                self.stack.widget(i).scroll_to_message(msg_index)
                return
        data = self._store.get_session(sid)
        if data:
            tab = self._add_tab(
                sid, data.get("title", sid), data.get("messages", []))
            self.session_list.setCurrentRow(self.session_list.count() - 1)
            QApplication.processEvents()
            tab.scroll_to_message(msg_index)

    def export_current(self):
        tab = self._current_tab()
        if not tab:
            return
        pdf = tab.export_pdf(subtitle=self._store._kind.upper())
        if not pdf:
            QMessageBox.information(self, "Export",
                "No messages to export yet."); return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", f"{tab.session_id}.pdf",
            "PDF Files (*.pdf)")
        if path:
            with open(path, "wb") as f:
                f.write(pdf)
            QMessageBox.information(self, "Saved", f"Exported to:\n{path}")


# =============================================================================
# CHAT PANEL
# =============================================================================

class ChatPanel(GenericSessionPanel):
    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(store, sidebar_title="💬 Chat Sessions", parent=parent)

    def _make_tab(self, sid, title, messages) -> ChatTab:
        return ChatTab(sid, title, self._store, messages)

    def _new_session_title(self) -> str:
        return f"Chat {self.stack.count() + 1}"


# =============================================================================
# MATPLOTLIB CANVAS  (shared by ExcelSessionPanel)
# =============================================================================

class MatplotlibCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(5, 3.2), facecolor=SURFACE)
        self.ax  = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._show_placeholder()

    def _show_placeholder(self):
        self.ax.clear()
        self.ax.text(0.5, 0.5, "Chart will appear here after analysis",
                     ha="center", va="center", color="#94a3b8", fontsize=10,
                     transform=self.ax.transAxes)
        self.ax.set_axis_off(); self.draw()

    def _style(self, title, xlabel, ylabel):
        self.ax.set_title(title, fontsize=10, pad=8)
        self.ax.set_xlabel(xlabel, fontsize=9)
        self.ax.set_ylabel(ylabel, fontsize=9)
        self.ax.tick_params(axis="x", rotation=35, labelsize=8)
        self.ax.tick_params(axis="y", labelsize=8)
        self.ax.spines[["top", "right"]].set_visible(False)
        self.ax.set_axis_on(); self.fig.tight_layout()

    def plot_bar(self, df, x_col, y_col, title=""):
        self.ax.clear()
        (df[[x_col, y_col]].dropna()
         .groupby(x_col, as_index=True)[y_col].mean()
         .plot(kind="bar", ax=self.ax, color=TEAL, edgecolor="white"))
        self._style(title, x_col, y_col); self.draw()

    def plot_line(self, df, x_col, y_col, title=""):
        self.ax.clear()
        sub = df[[x_col, y_col]].dropna().reset_index(drop=True)
        self.ax.plot(sub[x_col].astype(str), sub[y_col],
                     color=TEAL, marker="o", linewidth=2, markersize=5)
        self._style(title, x_col, y_col); self.draw()

    def show_message(self, msg):
        self.ax.clear()
        self.ax.text(0.5, 0.5, msg, ha="center", va="center",
                     color="#94a3b8", fontsize=9,
                     transform=self.ax.transAxes, wrap=True)
        self.ax.set_axis_off(); self.draw()


# =============================================================================
# EXCEL SESSION PANEL
# =============================================================================

class ExcelSessionPanel(QWidget):
    """
    Top section: file picker + sheet selector + data preview + chart.
    Bottom section: GenericSessionPanel (sidebar + chat bubbles).
    The canvas is shared; each ExcelSessionTab gets a reference to it.
    """

    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(parent)
        self._store = store
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── top controls strip ───────────────────────────
        ctrl = QWidget()
        ctrl.setObjectName("ctrlStrip")
        ctrl.setStyleSheet(
            f"QWidget#ctrlStrip {{ background:{SURFACE};"
            f"border-bottom:1px solid {BORDER}; }}")
        ctrl_lay = QVBoxLayout(ctrl)
        ctrl_lay.setContentsMargins(16, 12, 16, 10)
        ctrl_lay.setSpacing(6)

        ctrl_lay.addWidget(_heading("📊 Excel Analysis"))
        ctrl_lay.addWidget(QLabel(
            "Load a spreadsheet, preview sheets, then ask questions across "
            "multiple sessions. A chart is auto-generated per question."))

        # file picker
        fr = QHBoxLayout()
        self.path_lbl = QLineEdit(); self.path_lbl.setReadOnly(True)
        self.path_lbl.setPlaceholderText("No file selected…")
        bb = QPushButton("Browse…"); bb.clicked.connect(self._browse)
        fr.addWidget(self.path_lbl, stretch=1); fr.addWidget(bb)
        ctrl_lay.addLayout(fr)

        # sheet selector
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Preview sheet:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._load_sheet)
        sr.addWidget(self.sheet_combo)
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;")
        sr.addWidget(self.info_lbl); sr.addStretch()
        ctrl_lay.addLayout(sr)
        outer.addWidget(ctrl)

        # ── splitter: preview + chart | session panel ─────
        main_split = QSplitter(Qt.Orientation.Horizontal)

        # Left: data preview + chart
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 4, 8); left_lay.setSpacing(6)

        vert_split = QSplitter(Qt.Orientation.Vertical)

        self.preview = QTextEdit(); self.preview.setReadOnly(True)
        self.preview.setStyleSheet(
            f"font-family:monospace;font-size:11px;background:{SURFACE};")
        vert_split.addWidget(self.preview)

        self.canvas = MatplotlibCanvas()
        self.canvas.setMinimumHeight(180)
        vert_split.addWidget(self.canvas)
        vert_split.setSizes([150, 200])
        left_lay.addWidget(vert_split)
        main_split.addWidget(left)

        # Right: session panel
        self._session_panel = _ExcelInnerPanel(store, self.canvas)
        main_split.addWidget(self._session_panel)
        main_split.setSizes([380, 620])
        outer.addWidget(main_split, stretch=1)

        self._xls: Optional[pd.ExcelFile] = None

    # ── file / sheet ─────────────────────────────────────────────────────────

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Open Excel", "", "Excel Files (*.xlsx *.xls)")
        if not p: return
        self.path_lbl.setText(p)
        try:
            self._xls = pd.ExcelFile(p)
            self.sheet_combo.clear()
            self.sheet_combo.addItems(self._xls.sheet_names)
            self.info_lbl.setText(f"{len(self._xls.sheet_names)} sheet(s)")
            # Notify current session tab
            self._notify_file_loaded(p)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _load_sheet(self):
        if not self._xls: return
        s = self.sheet_combo.currentText()
        if not s: return
        try:
            df = pd.read_excel(self._xls, sheet_name=s)
            self.preview.setText(df.head(20).to_string())
            self._notify_sheet_loaded(df)
        except Exception as e:
            self.preview.setText(f"Error: {e}")

    def _notify_file_loaded(self, path: str):
        tab = self._session_panel._current_tab()
        if tab and isinstance(tab, ExcelSessionTab):
            tab._try_load_excel(path)

    def _notify_sheet_loaded(self, df: pd.DataFrame):
        tab = self._session_panel._current_tab()
        if tab and isinstance(tab, ExcelSessionTab):
            tab._df = df

    def restore_session(self, sid: str, msg_index: int):
        self._session_panel.restore_session(sid, msg_index)

    def export_current(self):
        self._session_panel.export_current()


class _ExcelInnerPanel(GenericSessionPanel):
    """Inner panel wired up to an ExcelSessionTab and a shared canvas."""

    def __init__(self, store: HistoryStore,
                  canvas: MatplotlibCanvas, parent=None):
        self._canvas = canvas
        super().__init__(store, sidebar_title="📊 Excel Sessions", parent=parent)

    def _make_tab(self, sid, title, messages) -> ExcelSessionTab:
        tab = ExcelSessionTab(sid, title, self._store, messages)
        tab.attach_canvas(self._canvas)
        return tab

    def _new_session_title(self) -> str:
        return f"Excel {self.stack.count() + 1}"

    # Override _switch_session to also update canvas reference
    def _switch_session(self, row: int):
        super()._switch_session(row)
        tab = self._current_tab()
        if tab and isinstance(tab, ExcelSessionTab):
            tab.attach_canvas(self._canvas)


# =============================================================================
# RAG SESSION PANEL
# =============================================================================

class RagSessionPanel(QWidget):
    """
    Top: file picker + index button (shared across sessions).
    Bottom: GenericSessionPanel with RagSessionTabs.
    RAG index is rebuilt when new files are indexed and shared with
    the currently active session tab.
    """

    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── top strip ────────────────────────────────────
        ctrl = QWidget()
        ctrl.setObjectName("ctrlStrip")
        ctrl.setStyleSheet(
            f"QWidget#ctrlStrip {{ background:{SURFACE};"
            f"border-bottom:1px solid {BORDER}; }}")
        ctrl_lay = QVBoxLayout(ctrl)
        ctrl_lay.setContentsMargins(16, 12, 16, 10); ctrl_lay.setSpacing(6)

        ctrl_lay.addWidget(_heading("🧠 Ask Your Document (RAG)"))
        ctrl_lay.addWidget(QLabel(
            "Upload and index PDFs, then ask questions across multiple sessions. "
            "Answers cite sources from your documents."))

        row = QHBoxLayout()
        self.files_lbl = QLineEdit(); self.files_lbl.setReadOnly(True)
        self.files_lbl.setPlaceholderText("No files selected…")
        bb = QPushButton("Browse PDFs…"); bb.clicked.connect(self._browse)
        self.idx_btn = QPushButton("Index Documents")
        self.idx_btn.clicked.connect(self._index)
        row.addWidget(self.files_lbl, stretch=1)
        row.addWidget(bb); row.addWidget(self.idx_btn)
        ctrl_lay.addLayout(row)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{MUTED};font-size:12px;")
        ctrl_lay.addWidget(self.status_lbl)
        outer.addWidget(ctrl)

        # ── session panel ─────────────────────────────────
        self._session_panel = _RagInnerPanel(store)
        outer.addWidget(self._session_panel, stretch=1)

        self._files: list[str] = []
        self._rag_data: Optional[dict] = None
        self._iw: Optional[RagIndexWorker] = None

    def _browse(self):
        ps, _ = QFileDialog.getOpenFileNames(
            self, "Open PDFs", "", "PDF Files (*.pdf)")
        if not ps: return
        self._files = ps
        self.files_lbl.setText("; ".join(Path(p).name for p in ps))

    def _index(self):
        if not self._files:
            QMessageBox.warning(self, "No files", "Select PDFs first."); return
        self.status_lbl.setText("⏳ Indexing…")
        self.idx_btn.setEnabled(False)
        self._iw = RagIndexWorker(self._files)
        self._iw.done.connect(self._on_indexed)
        self._iw.error.connect(lambda e: (
            self.status_lbl.setText(f"⚠️ {e}"),
            self.idx_btn.setEnabled(True)))
        self._iw.start()

    @pyqtSlot(dict)
    def _on_indexed(self, data: dict):
        self._rag_data = data
        self.status_lbl.setText(
            f"✅ Indexed {len(self._files)} file(s) "
            f"→ {len(data['chunks'])} chunks. "
            "Ready to answer questions.")
        self.idx_btn.setEnabled(True)
        # Push to all existing tabs and any newly created ones
        self._session_panel.set_rag_data(data)

    def restore_session(self, sid: str, msg_index: int):
        self._session_panel.restore_session(sid, msg_index)

    def export_current(self):
        self._session_panel.export_current()


class _RagInnerPanel(GenericSessionPanel):
    def __init__(self, store: HistoryStore, parent=None):
        self._rag_data: Optional[dict] = None
        super().__init__(store, sidebar_title="🧠 RAG Sessions", parent=parent)

    def _make_tab(self, sid, title, messages) -> RagSessionTab:
        tab = RagSessionTab(sid, title, self._store, messages)
        if self._rag_data:
            tab.set_rag_data(self._rag_data)
        return tab

    def _new_session_title(self) -> str:
        return f"RAG {self.stack.count() + 1}"

    def set_rag_data(self, data: dict):
        self._rag_data = data
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if isinstance(w, RagSessionTab):
                w.set_rag_data(data)

    def create_session(self):
        """Override to inject rag_data into newly created tabs."""
        sid   = new_session_id()
        title = self._new_session_title()
        tab   = self._add_tab(sid, title, [])
        if self._rag_data and isinstance(tab, RagSessionTab):
            tab.set_rag_data(self._rag_data)
        self._store.upsert_session(sid, title, [])
        self.session_list.setCurrentRow(self.session_list.count() - 1)


# =============================================================================
# PDF SUMMARY PANEL  (unchanged in structure, kept for completeness)
# =============================================================================

class PdfSummaryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.addWidget(_heading("📄 PDF Summary"))
        lay.addWidget(QLabel(
            "Upload a dental report, research paper, or any PDF."))

        row = QHBoxLayout()
        self.path_lbl = QLineEdit(); self.path_lbl.setReadOnly(True)
        self.path_lbl.setPlaceholderText("No file selected…")
        b = QPushButton("Browse…"); b.clicked.connect(self._browse)
        row.addWidget(self.path_lbl); row.addWidget(b)
        lay.addLayout(row)

        opt = QHBoxLayout()
        self.length_combo = QComboBox()
        self.length_combo.addItems(
            ["Short (1-2 paragraphs)", "Medium", "Detailed"])
        self.focus_input = QLineEdit()
        self.focus_input.setPlaceholderText("Focus on (optional)…")
        opt.addWidget(QLabel("Length:")); opt.addWidget(self.length_combo)
        opt.addSpacing(16)
        opt.addWidget(QLabel("Focus:")); opt.addWidget(self.focus_input)
        lay.addLayout(opt)

        self.sum_btn = QPushButton("Summarise")
        self.sum_btn.clicked.connect(self._summarise)
        lay.addWidget(self.sum_btn)

        self.output = QTextEdit(); self.output.setReadOnly(True)
        self.output.setPlaceholderText("Summary will appear here…")
        lay.addWidget(self.output)
        self._pdf_text = ""
        self._worker: Optional[OllamaWorker] = None

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf)")
        if not p: return
        self.path_lbl.setText(p)
        try:
            with pdfplumber.open(p) as pdf:
                text = "".join(pg.extract_text() or "" for pg in pdf.pages)
            if not text.strip():
                QMessageBox.warning(self, "Warning",
                    "No extractable text."); return
            self._pdf_text = text
            self.output.setPlaceholderText(
                f"Extracted {len(text):,} chars. Click Summarise.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _summarise(self):
        if not self._pdf_text:
            QMessageBox.warning(self, "No PDF", "Select a PDF first."); return
        lmap = {
            "Short (1-2 paragraphs)": "in 1-2 short paragraphs",
            "Medium": "in 3-4 paragraphs",
            "Detailed": "in a structured, detailed manner with key points",
        }
        instr = lmap[self.length_combo.currentText()]
        focus = self.focus_input.text().strip()
        fc    = f" Focus especially on: {focus}." if focus else ""
        prompt = (f"Summarise the following document {instr}.{fc}\n\n"
                  f"Document:\n{self._pdf_text[:MAX_CONTEXT_CHARS]}")
        self.sum_btn.setEnabled(False)
        self.output.setText("⏳ Summarising…")
        self._worker = OllamaWorker(GENERAL_MODEL, prompt)
        self._worker.result.connect(
            lambda t: (self.output.setText(t), self.sum_btn.setEnabled(True)))
        self._worker.error.connect(
            lambda e: (self.output.setText(f"⚠️ {e}"),
                       self.sum_btn.setEnabled(True)))
        self._worker.start()


# =============================================================================
# WEBSITE SUMMARY PANEL
# =============================================================================

class WebsiteSummaryPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.addWidget(_heading("🌐 Website Summary"))
        lay.addWidget(QLabel("Paste any public URL to get an AI summary."))

        row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/article")
        self.url_input.returnPressed.connect(self._fetch)
        fb = QPushButton("Fetch & Summarise"); fb.clicked.connect(self._fetch)
        row.addWidget(self.url_input); row.addWidget(fb)
        lay.addLayout(row)

        self.output = QTextEdit(); self.output.setReadOnly(True)
        self.output.setPlaceholderText("Summary will appear here…")
        lay.addWidget(self.output)
        self._fw: Optional[FetchWebWorker] = None
        self._lw: Optional[OllamaWorker]   = None

    def _fetch(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "No URL", "Enter a URL."); return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "Invalid",
                "URL must start with http:// or https://"); return
        self.output.setText("⏳ Fetching…")
        self._fw = FetchWebWorker(url)
        self._fw.result.connect(self._on_fetched)
        self._fw.error.connect(lambda e: self.output.setText(f"⚠️ {e}"))
        self._fw.start()

    @pyqtSlot(str)
    def _on_fetched(self, text: str):
        if not text.strip():
            self.output.setText("⚠️ No readable text found."); return
        self.output.setText("⏳ Analysing…")
        self._lw = OllamaWorker(GENERAL_MODEL,
            f"Summarise the following web page content concisely:\n\n{text}")
        self._lw.result.connect(lambda t: self.output.setText(t))
        self._lw.error.connect(lambda e: self.output.setText(f"⚠️ {e}"))
        self._lw.start()


# =============================================================================
# IMAGE ANALYSIS — SESSION TAB
# =============================================================================

SUPPORTED_IMAGE_EXTS = (
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"
)

IMAGE_DISCLAIMER_HTML = (
    "<b>⚠️ Educational use only.</b>  This tool provides AI-generated "
    "observations for informational purposes.  It does <u>not</u> constitute "
    "a medical diagnosis or professional dental opinion.  Always consult a "
    "qualified dentist for clinical decisions."
)


class ImageSessionTab(QWidget):
    """
    One image-analysis session.
    Layout:
      ┌─────────────────────────────────┐
      │  Disclaimer banner              │
      │  Attached image thumbnail       │
      │  ─────────────────────────────  │
      │  Scrollable Q&A bubble area     │
      │  ─────────────────────────────  │
      │  [Attach Image]  Question input │ [Analyse ➤]
      └─────────────────────────────────┘
    """
    messages_changed = pyqtSignal()

    def __init__(self, session_id: str, title: str,
                 store: "HistoryStore",
                 existing_messages: Optional[list[dict]] = None,
                 parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.title      = title
        self.store      = store
        # messages stored as:
        #   user turns:      {"role":"user", "content": text, "ts":...,
        #                     "image_path": path_or_empty}
        #   assistant turns: {"role":"assistant", "content": text, "ts":...}
        self.messages: list[dict] = list(existing_messages or [])
        self._bubbles: list[QFrame] = []
        self._current_image_path: str = ""
        self._worker: Optional[ImageAnalysisWorker] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # ── Disclaimer banner ─────────────────────────────
        disc = QLabel(IMAGE_DISCLAIMER_HTML)
        disc.setWordWrap(True)
        disc.setTextFormat(Qt.TextFormat.RichText)
        disc.setStyleSheet(
            f"background:#fffbeb;border:1px solid {WARNING_CLR};"
            f"border-radius:8px;padding:8px 12px;color:#92400e;font-size:12px;")
        outer.addWidget(disc)

        # ── Image thumbnail strip ─────────────────────────
        self._thumb_label = QLabel("No image attached.")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet(
            f"background:{SURFACE};border:1px dashed {BORDER};"
            f"border-radius:8px;color:{MUTED};font-size:12px;padding:6px;")
        self._thumb_label.setFixedHeight(120)
        self._thumb_label.setScaledContents(False)
        outer.addWidget(self._thumb_label)

        # ── Scroll area (Q&A bubbles) ─────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.msg_container = QWidget()
        self.msg_layout    = QVBoxLayout(self.msg_container)
        self.msg_layout.addStretch()
        self.msg_layout.setSpacing(6)
        self.scroll.setWidget(self.msg_container)
        outer.addWidget(self.scroll, stretch=1)

        # ── Input row ─────────────────────────────────────
        inp = QHBoxLayout(); inp.setSpacing(6)

        self.attach_btn = QPushButton("📎 Attach Image")
        self.attach_btn.setFixedHeight(38)
        self.attach_btn.setObjectName("secondary")
        self.attach_btn.clicked.connect(self._attach_image)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText(
            "Ask a question about the attached image…")
        self.input_box.setMinimumHeight(38)
        self.input_box.returnPressed.connect(self._send)

        self.send_btn = QPushButton("Analyse ➤")
        self.send_btn.setFixedHeight(38)
        self.send_btn.clicked.connect(self._send)

        inp.addWidget(self.attach_btn)
        inp.addWidget(self.input_box, stretch=1)
        inp.addWidget(self.send_btn)
        outer.addLayout(inp)

        # Restore existing bubbles from history
        for msg in self.messages:
            img_path = msg.get("image_path", "")
            self._make_bubble(
                role=msg["role"],
                text=msg["content"],
                image_path=img_path,
            )

    # ── image attachment ─────────────────────────────────────────────────────

    def _attach_image(self):
        exts = " ".join(f"*{e}" for e in SUPPORTED_IMAGE_EXTS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach Dental Image", "",
            f"Image Files ({exts});;All Files (*)")
        if not path:
            return
        self._current_image_path = path
        self._show_thumbnail(path)

    def _show_thumbnail(self, path: str):
        px = QPixmap(path)
        if px.isNull():
            self._thumb_label.setText(f"⚠️ Could not load: {Path(path).name}")
            return
        scaled = px.scaled(
            self._thumb_label.width() - 12,
            self._thumb_label.height() - 12,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_label.setPixmap(scaled)
        self._thumb_label.setToolTip(path)

    # ── bubble helpers ────────────────────────────────────────────────────────

    def _make_bubble(self, role: str, text: str,
                     image_path: str = "") -> QFrame:
        """
        Creates a compound bubble:
          • If image_path set and role==user → thumbnail above text
          • Otherwise plain text bubble
        """
        is_user = role == "user"
        frame   = QFrame()
        f_lay   = QVBoxLayout(frame)
        f_lay.setContentsMargins(0, 4, 0, 4)

        row = QHBoxLayout()

        # who label
        lbl_text = "You" if is_user else f"🦷 {IMAGE_MODEL}"
        lbl = QLabel(lbl_text)
        lbl.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;")

        inner = QVBoxLayout()
        inner.setSpacing(4)
        inner.addWidget(lbl)

        # optional image thumbnail inside bubble
        if is_user and image_path and Path(image_path).exists():
            px = QPixmap(image_path)
            if not px.isNull():
                img_lbl = QLabel()
                img_lbl.setPixmap(px.scaled(
                    260, 180,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                img_lbl.setStyleSheet(
                    "border-radius:6px;padding:2px;")
                inner.addWidget(img_lbl)

        # text label
        txt = QLabel(text)
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        txt.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        txt.setStyleSheet(f"""
            background-color: {"#e0fdf4" if is_user else SURFACE};
            border: 1px solid {"#99f6e4" if is_user else BORDER};
            border-radius: 10px;
            padding: 10px 14px; font-size: 13px;
        """)
        inner.addWidget(txt)

        # store ref for streaming updates
        frame._text_label = txt  # type: ignore[attr-defined]
        frame._base_style = txt.styleSheet()  # type: ignore[attr-defined]

        if is_user:
            row.addStretch(); row.addLayout(inner)
        else:
            row.addLayout(inner); row.addStretch()

        f_lay.addLayout(row)
        self._bubbles.append(frame)
        self.msg_layout.addWidget(frame)
        QApplication.processEvents()
        self._scroll_bottom()
        return frame

    def _scroll_bottom(self):
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum())

    def _set_enabled(self, v: bool):
        self.input_box.setEnabled(v)
        self.send_btn.setEnabled(v)
        self.attach_btn.setEnabled(v)

    def _persist(self):
        self.store.upsert_session(self.session_id, self.title, self.messages)
        self.messages_changed.emit()

    def scroll_to_message(self, idx: int):
        if 0 <= idx < len(self._bubbles):
            self.scroll.ensureWidgetVisible(self._bubbles[idx])
            b = self._bubbles[idx]
            orig = b._text_label.styleSheet()  # type: ignore[attr-defined]
            b._text_label.setStyleSheet(  # type: ignore[attr-defined]
                orig + f"border: 2px solid {TEAL};")
            QTimer.singleShot(
                1600, lambda: b._text_label.setStyleSheet(orig))  # type: ignore[attr-defined]

    # ── send ─────────────────────────────────────────────────────────────────

    def _send(self):
        question = self.input_box.text().strip()
        if not question:
            QMessageBox.warning(self, "No question",
                "Please type a question about the image."); return
        if not self._current_image_path:
            QMessageBox.warning(self, "No image",
                "Please attach a dental image first."); return

        self.input_box.clear()
        self._set_enabled(False)

        ts = datetime.now().isoformat(timespec="seconds")
        user_msg = {
            "role":       "user",
            "content":    question,
            "image_path": self._current_image_path,
            "ts":         ts,
        }
        self.messages.append(user_msg)
        self._make_bubble("user", question, self._current_image_path)

        # placeholder assistant bubble
        self._ai_bubble = self._make_bubble(
            "assistant", "⏳ Analysing image…")

        # Build text-only history for context (strip image_path keys)
        text_history = [
            {"role": m["role"], "content": m["content"]}
            for m in self.messages[:-1]  # exclude the just-added user msg
        ]

        self._worker = ImageAnalysisWorker(
            self._current_image_path, question, text_history)
        self._worker.result.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_result(self, text: str):
        self._ai_bubble._text_label.setText(text)  # type: ignore[attr-defined]
        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append(
            {"role": "assistant", "content": text, "ts": ts})
        self._persist()
        self._set_enabled(True)
        self._scroll_bottom()

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self._ai_bubble._text_label.setText(f"⚠️ {msg}")  # type: ignore[attr-defined]
        self._ai_bubble._text_label.setStyleSheet(  # type: ignore[attr-defined]
            f"background:{DANGER}22;border:1px solid {DANGER};"
            "border-radius:10px;padding:10px 14px;")
        self._set_enabled(True)

    def export_pdf(self, subtitle: str = "Image Analysis") -> Optional[bytes]:
        if not self.messages:
            return None
        return export_session_to_pdf(self.title, self.messages, subtitle)


# =============================================================================
# IMAGE ANALYSIS — INNER SESSION PANEL  (sidebar + stack)
# =============================================================================

class _ImageInnerPanel(GenericSessionPanel):
    def __init__(self, store: "HistoryStore", parent=None):
        super().__init__(store,
                         sidebar_title="🦷 Image Sessions",
                         parent=parent)

    def _make_tab(self, sid, title, messages) -> ImageSessionTab:
        return ImageSessionTab(sid, title, self._store, messages)

    def _new_session_title(self) -> str:
        return f"Image {self.stack.count() + 1}"


# =============================================================================
# IMAGE ANALYSIS — OUTER PANEL  (header + disclaimer + inner panel)
# =============================================================================

class ImageSessionPanel(QWidget):
    """
    Top: model info + full disclaimer.
    Bottom: _ImageInnerPanel (sidebar + session tabs).
    """

    def __init__(self, store: "HistoryStore", parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── header strip ─────────────────────────────────
        hdr = QWidget()
        hdr.setObjectName("ctrlStrip")
        hdr.setStyleSheet(
            f"QWidget#ctrlStrip {{ background:{SURFACE};"
            f"border-bottom:1px solid {BORDER}; }}")
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(16, 12, 16, 12)
        hdr_lay.setSpacing(8)

        title_row = QHBoxLayout()
        title_lbl = _heading("🦷 Dental Image Analysis")
        model_badge = QLabel(f"model: {IMAGE_MODEL}")
        model_badge.setStyleSheet(
            f"background:{TEAL_LIGHT};color:{TEAL_DARK};border-radius:12px;"
            f"padding:3px 10px;font-size:11px;font-weight:600;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(model_badge)
        hdr_lay.addLayout(title_row)

        # Full disclaimer
        disc_full = QLabel(
            "This feature uses AI to describe features visible in dental images "
            "(X-rays, photographs, scans). "
            "<b>It does not provide medical diagnoses</b> and is intended for "
            "educational and informational purposes only. "
            "Image data is processed locally via Ollama and never sent to the cloud. "
            "Always consult a qualified dentist or specialist for clinical advice.")
        disc_full.setWordWrap(True)
        disc_full.setTextFormat(Qt.TextFormat.RichText)
        disc_full.setStyleSheet(
            f"color:{MUTED};font-size:12px;line-height:1.5;")
        hdr_lay.addWidget(disc_full)

        # How-to hint
        hint = QLabel(
            "How to use:  ① Click  📎 Attach Image  in any session tab  "
            "②  Type your question  ③  Press  Analyse ➤")
        hint.setStyleSheet(
            f"background:{TEAL_LIGHT};border-radius:6px;"
            f"padding:5px 10px;color:{TEAL_DARK};font-size:12px;")
        hdr_lay.addWidget(hint)
        outer.addWidget(hdr)

        # ── session panel ─────────────────────────────────
        self._session_panel = _ImageInnerPanel(store)
        outer.addWidget(self._session_panel, stretch=1)

    def restore_session(self, sid: str, msg_index: int):
        self._session_panel.restore_session(sid, msg_index)

    def export_current(self):
        self._session_panel.export_current()


# =============================================================================

class SearchDialog(QDialog):
    open_chat    = pyqtSignal(str, int)
    open_excel   = pyqtSignal(str, int)
    open_rag     = pyqtSignal(str, int)
    open_image   = pyqtSignal(str, int)   # NEW

    def __init__(self, stores: dict[str, "HistoryStore"], parent=None):
        """stores = {'chat': ..., 'excel': ..., 'rag': ..., 'image': ...}"""
        super().__init__(parent)
        self._stores = stores
        self.setWindowTitle("🔍 Search Chat History")
        self.setMinimumSize(760, 580)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16); root.setSpacing(10)

        hdr = QLabel("Search Chat History")
        hdr.setStyleSheet(
            f"font-size:16px;font-weight:700;color:{TEXT};margin-bottom:2px;")
        root.addWidget(hdr)

        sub = QLabel(
            "Searches across Chat, Excel Analysis, RAG, and Image Analysis "
            "sessions for the current user. Double-click a result to open it.")
        sub.setStyleSheet(f"color:{MUTED};font-size:12px;")
        root.addWidget(sub)

        # keyword row
        kw_row = QHBoxLayout()
        self.kw_input = QLineEdit()
        self.kw_input.setPlaceholderText("Type a keyword…")
        self.kw_input.setMinimumHeight(36)
        self.kw_input.returnPressed.connect(self._run_search)
        kw_row.addWidget(self.kw_input, stretch=1)
        search_btn = QPushButton("Search"); search_btn.setFixedHeight(36)
        search_btn.clicked.connect(self._run_search)
        kw_row.addWidget(search_btn)
        clear_btn = QPushButton("Clear"); clear_btn.setFixedHeight(36)
        clear_btn.setObjectName("secondary")
        clear_btn.clicked.connect(self._clear)
        kw_row.addWidget(clear_btn)
        root.addLayout(kw_row)

        # scope filter
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Search in:"))
        self.scope_chat  = QPushButton("💬 Chat");   self.scope_chat.setCheckable(True);  self.scope_chat.setChecked(True)
        self.scope_excel = QPushButton("📊 Excel");  self.scope_excel.setCheckable(True); self.scope_excel.setChecked(True)
        self.scope_rag   = QPushButton("🧠 RAG");    self.scope_rag.setCheckable(True);   self.scope_rag.setChecked(True)
        self.scope_image = QPushButton("🦷 Images"); self.scope_image.setCheckable(True); self.scope_image.setChecked(True)
        for b in (self.scope_chat, self.scope_excel, self.scope_rag, self.scope_image):
            b.setObjectName("scopeBtn"); b.setFixedHeight(30)
            scope_row.addWidget(b)
        scope_row.addStretch()
        root.addLayout(scope_row)

        # date filter
        date_grp = QGroupBox("Date Range Filter")
        d_lay    = QHBoxLayout(date_grp)
        self.use_date_cb = QPushButton("Enable Date Filter")
        self.use_date_cb.setCheckable(True); self.use_date_cb.setChecked(False)
        self.use_date_cb.setObjectName("secondary"); self.use_date_cb.setFixedHeight(28)
        self.use_date_cb.toggled.connect(self._toggle_date)
        d_lay.addWidget(self.use_date_cb)
        d_lay.addSpacing(12); d_lay.addWidget(QLabel("From:"))
        self.date_from = QDateEdit(); self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate(2020, 1, 1))
        self.date_from.setDisplayFormat("dd MMM yyyy"); self.date_from.setEnabled(False)
        d_lay.addWidget(self.date_from)
        d_lay.addSpacing(8); d_lay.addWidget(QLabel("To:"))
        self.date_to = QDateEdit(); self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat("dd MMM yyyy"); self.date_to.setEnabled(False)
        d_lay.addWidget(self.date_to); d_lay.addStretch()
        root.addWidget(date_grp)

        self.count_lbl = QLabel("Enter a keyword and press Search.")
        self.count_lbl.setStyleSheet(f"color:{MUTED};font-size:12px;")
        root.addWidget(self.count_lbl)

        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
        self.results_list.currentRowChanged.connect(self._on_row_changed)
        self.results_list.itemDoubleClicked.connect(
            lambda _: self._open_selected())
        root.addWidget(self.results_list, stretch=1)

        prev_grp = QGroupBox("Message Preview  (keyword highlighted)")
        prev_lay = QVBoxLayout(prev_grp)
        self.preview = QTextEdit(); self.preview.setReadOnly(True)
        self.preview.setFixedHeight(110)
        self.preview.setStyleSheet(
            f"background:{SURFACE};border:1px solid {BORDER};border-radius:8px;")
        prev_lay.addWidget(self.preview)
        root.addWidget(prev_grp)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Open Session  ↗")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_selected)
        btn_row.addStretch(); btn_row.addWidget(self.open_btn)
        close_btn = QPushButton("Close"); close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._results: list[dict] = []

    def _toggle_date(self, checked: bool):
        self.date_from.setEnabled(checked); self.date_to.setEnabled(checked)
        self.use_date_cb.setText(
            "✓ Date Filter Active" if checked else "Enable Date Filter")

    def _run_search(self):
        kw = self.kw_input.text().strip()
        df = dt = None
        if self.use_date_cb.isChecked():
            qf = self.date_from.date(); qt = self.date_to.date()
            df = date(qf.year(), qf.month(), qf.day())
            dt = date(qt.year(), qt.month(), qt.day())

        scope_map = {
            "chat":  self.scope_chat,
            "excel": self.scope_excel,
            "rag":   self.scope_rag,
            "image": self.scope_image,
        }
        self._results = []
        for kind, store in self._stores.items():
            if scope_map.get(kind, self.scope_chat).isChecked():
                self._results.extend(store.search(kw, df, dt))

        self._results.sort(key=lambda r: r["created"], reverse=True)
        self.results_list.clear(); self.preview.clear()
        self.open_btn.setEnabled(False)

        if not self._results:
            self.count_lbl.setText("No results found."); return

        n_sess = len({r["sid"] for r in self._results})
        self.count_lbl.setText(
            f"{len(self._results)} result(s) across {n_sess} session(s).")

        kind_icons = {"chat": "💬", "excel": "📊", "rag": "🧠", "image": "🦷"}
        for i, r in enumerate(self._results):
            created  = r["created"][:10] if r["created"] else "?"
            role_ico = "👤" if r["role"] == "user" else "🤖"
            tool_ico = kind_icons.get(r.get("kind", "chat"), "💬")
            item = QListWidgetItem(
                f"{tool_ico} {role_ico}  [{created}]  {r['title']}   —   "
                f"{r['snippet'][:85]}")
            item.setToolTip(r["snippet"])
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.results_list.addItem(item)

    def _on_row_changed(self, row: int):
        if row < 0 or row >= len(self._results): return
        r   = self._results[row]
        kw  = r.get("keyword", "")
        self.open_btn.setEnabled(True)
        self.preview.clear()
        cursor   = self.preview.textCursor()
        fmt_norm = QTextCharFormat()
        fmt_hi   = QTextCharFormat()
        fmt_hi.setBackground(QColor(HIGHLIGHT))
        fmt_hi.setFontWeight(700)
        content = r["content"]
        if kw:
            lower = content.lower(); last = 0
            for m in re.finditer(re.escape(kw), lower):
                cursor.insertText(content[last: m.start()], fmt_norm)
                cursor.insertText(content[m.start(): m.end()], fmt_hi)
                last = m.end()
            cursor.insertText(content[last:], fmt_norm)
        else:
            self.preview.setPlainText(content)

    def _open_selected(self):
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self._results): return
        r    = self._results[row]
        kind = r.get("kind", "chat")
        if kind == "chat":
            self.open_chat.emit(r["sid"], r["msg_index"])
        elif kind == "excel":
            self.open_excel.emit(r["sid"], r["msg_index"])
        elif kind == "rag":
            self.open_rag.emit(r["sid"], r["msg_index"])
        else:
            self.open_image.emit(r["sid"], r["msg_index"])
        self.close()

    def _clear(self):
        self.kw_input.clear(); self.results_list.clear()
        self.preview.clear()
        self.count_lbl.setText("Enter a keyword and press Search.")
        self._results = []; self.open_btn.setEnabled(False)

    def show_and_focus(self):
        self.show(); self.raise_(); self.activateWindow()
        self.kw_input.setFocus()


# =============================================================================
# LOGIN DIALOG
# =============================================================================

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dental AI Assistant")
        self.setFixedSize(420, 340)
        self.setModal(True)
        self.username = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 32, 40, 32); lay.setSpacing(16)

        ico = QLabel("🦷")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet("font-size:52px;")
        lay.addWidget(ico)

        t = QLabel("Dental AI Assistant")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"font-size:22px;font-weight:700;color:{TEXT};")
        lay.addWidget(t)

        s = QLabel("Private · Local · Powered by Ollama")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setStyleSheet(f"color:{MUTED};font-size:12px;")
        lay.addWidget(s)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(
            "Your name / alias (e.g. Dr. Müller)")
        self.name_input.setMinimumHeight(38)
        self.name_input.returnPressed.connect(self._login)
        lay.addWidget(self.name_input)

        btn = QPushButton("Enter →"); btn.setMinimumHeight(40)
        btn.clicked.connect(self._login); lay.addWidget(btn)

        n = QLabel("All data stays on your machine.")
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        n.setStyleSheet("color:#94a3b8;font-size:11px;")
        lay.addWidget(n)

    def _login(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Required", "Please enter a name.")
            return
        self.username = name
        self.accept()


# =============================================================================
# MAIN WINDOW
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self, username: str):
        super().__init__()
        self.username = username
        self.setWindowTitle(f"🦷 Dental AI Assistant  —  {username}")
        self.setMinimumSize(1200, 750)
        self._search_dlg: Optional[SearchDialog] = None

        # ── Per-user stores ───────────────────────────────
        self._stores = {
            "chat":  HistoryStore(_history_path(username, "chat"),  username, "chat"),
            "excel": HistoryStore(_history_path(username, "excel"), username, "excel"),
            "rag":   HistoryStore(_history_path(username, "rag"),   username, "rag"),
            "image": HistoryStore(_history_path(username, "image"), username, "image"),
        }

        # ── Toolbar ──────────────────────────────────────
        tb = QToolBar("Main"); tb.setMovable(False)
        self.addToolBar(tb)

        search_act = QAction("🔍  Search History  (Ctrl+F)", self)
        search_act.setShortcut(QKeySequence("Ctrl+F"))
        search_act.triggered.connect(self._open_search)
        tb.addAction(search_act); tb.addSeparator()

        export_act = QAction("⬇  Export Current Session PDF", self)
        export_act.triggered.connect(self._export_current)
        tb.addAction(export_act)

        # ── Central layout ───────────────────────────────
        central = QWidget(); self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────
        sb_w = QWidget(); sb_w.setObjectName("sidebar"); sb_w.setFixedWidth(215)
        sb = QVBoxLayout(sb_w)
        sb.setContentsMargins(12, 16, 12, 16); sb.setSpacing(5)

        brand = QLabel("🦷 DentalAI")
        brand.setStyleSheet(f"font-size:20px;font-weight:700;color:{TEAL};")
        ulbl = QLabel(f"Logged in as  {username}")
        ulbl.setStyleSheet(f"color:{MUTED};font-size:11px;")
        sb.addWidget(brand); sb.addWidget(ulbl)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};"); sb.addWidget(sep)

        _nav_style = f"""
            QPushButton#navBtn {{
                background:transparent; color:{TEXT};
                border:none; border-radius:8px;
                padding:8px 12px; text-align:left; font-weight:500;
            }}
            QPushButton#navBtn:hover {{
                background:{TEAL_LIGHT}; color:{TEAL_DARK};
            }}
            QPushButton#navBtn:checked {{
                background:{TEAL_LIGHT}; color:{TEAL_DARK}; font-weight:700;
            }}
        """
        self._nav_btns: list[QPushButton] = []
        for label, idx in [
            ("💬 Chat",                 0),
            ("📄 PDF Summary",          1),
            ("🌐 Website Summary",      2),
            ("📊 Excel Analysis",       3),
            ("🧠 Ask Your Document",    4),
            ("🦷 Image Analysis",       5),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True); btn.setObjectName("navBtn")
            btn.setStyleSheet(_nav_style)
            btn.clicked.connect(lambda _, i=idx: self._switch_tool(i))
            sb.addWidget(btn); self._nav_btns.append(btn)

        sb.addStretch()
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color:{BORDER};"); sb.addWidget(sep2)

        lo_btn = QPushButton("← Log out")
        lo_btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{MUTED};
                border:1px solid {BORDER}; border-radius:8px;
                padding:7px 12px; font-weight:500;
            }}
            QPushButton:hover {{
                background:#fee2e2; color:{DANGER};
                border-color:{DANGER};
            }}
        """)
        lo_btn.clicked.connect(self._logout); sb.addWidget(lo_btn)

        # ── Tool panels ───────────────────────────────────
        self._chat_panel  = ChatPanel(self._stores["chat"])
        self._excel_panel = ExcelSessionPanel(self._stores["excel"])
        self._rag_panel   = RagSessionPanel(self._stores["rag"])
        self._image_panel = ImageSessionPanel(self._stores["image"])

        self.stack = QStackedWidget()
        self.stack.addWidget(self._chat_panel)       # 0
        self.stack.addWidget(PdfSummaryPanel())       # 1
        self.stack.addWidget(WebsiteSummaryPanel())   # 2
        self.stack.addWidget(self._excel_panel)       # 3
        self.stack.addWidget(self._rag_panel)         # 4
        self.stack.addWidget(self._image_panel)       # 5

        root.addWidget(sb_w); root.addWidget(self.stack)

        self._status_bar = self.statusBar()
        self._switch_tool(0)

    # ── routing ───────────────────────────────────────────────────────────────

    def _switch_tool(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        label, model = TOOL_STATUS.get(idx, ("", ""))
        self._status_bar.showMessage(
            f"Ready  ·  {label}  ·  model: {model}  ·  user: {self.username}")

    # ── search ────────────────────────────────────────────────────────────────

    def _open_search(self):
        if self._search_dlg is None:
            self._search_dlg = SearchDialog(self._stores, self)
            self._search_dlg.open_chat.connect(
                lambda sid, idx: (self._switch_tool(0),
                                  self._chat_panel.restore_session(sid, idx)))
            self._search_dlg.open_excel.connect(
                lambda sid, idx: (self._switch_tool(3),
                                  self._excel_panel.restore_session(sid, idx)))
            self._search_dlg.open_rag.connect(
                lambda sid, idx: (self._switch_tool(4),
                                  self._rag_panel.restore_session(sid, idx)))
            self._search_dlg.open_image.connect(
                lambda sid, idx: (self._switch_tool(5),
                                  self._image_panel.restore_session(sid, idx)))
        self._search_dlg.show_and_focus()

    # ── export (context-aware) ────────────────────────────────────────────────

    def _export_current(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            self._chat_panel.export_current()
        elif idx == 3:
            self._excel_panel.export_current()
        elif idx == 4:
            self._rag_panel.export_current()
        elif idx == 5:
            self._image_panel.export_current()
        else:
            QMessageBox.information(
                self, "Export",
                "PDF export is available for Chat, Excel Analysis, "
                "Ask Your Document, and Image Analysis sessions.")

    # ── logout ────────────────────────────────────────────────────────────────

    def _logout(self):
        if QMessageBox.question(
            self, "Log out", "Log out and return to login?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.close()
            _start_login()


# =============================================================================
# ENTRY POINT
# =============================================================================

_app: Optional[QApplication] = None
_main_win: Optional[MainWindow] = None


def _start_login():
    dlg = LoginDialog()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        global _main_win
        _main_win = MainWindow(dlg.username)
        _main_win.setStyleSheet(APP_STYLESHEET)
        _main_win.show()


def main():
    global _app
    _app = QApplication(sys.argv)
    _app.setStyle("Fusion")
    _app.setStyleSheet(APP_STYLESHEET)
    # PyQt6: High-DPI always on by default
    _start_login()
    sys.exit(_app.exec())


if __name__ == "__main__":
    main()
