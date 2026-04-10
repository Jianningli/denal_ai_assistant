"""
dental_ai/ui/panels/image_panel.py
=====================================
Dental Image Analysis feature — attach an image, ask questions, get
AI-generated observations with full disclaimer.

Classes
-------
ImageSessionTab   — one image-analysis session (one image, multi-turn Q&A)
_ImageInnerPanel  — GenericSessionPanel wired to ImageSessionTabs
ImageSessionPanel — outer widget (header + full disclaimer + inner panel)
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dental_ai.core.constants import (
    BORDER,
    DANGER,
    IMAGE_DISCLAIMER_HTML,
    IMAGE_MODEL,
    MUTED,
    SUPPORTED_IMAGE_EXTS,
    SURFACE,
    TEAL,
    TEAL_DARK,
    TEAL_LIGHT,
    WARNING_CLR,
)
from dental_ai.core.context_manager import ContextManager
from dental_ai.core.history_store import HistoryStore
from dental_ai.core.pdf_export import export_session_to_pdf
from dental_ai.core.utils import heading_label, new_session_id
from dental_ai.ui.widgets.base_session import GenericSessionPanel
from dental_ai.workers import ImageAnalysisWorker


class ImageSessionTab(QWidget):
    """
    One image-analysis session.

    Layout::

        ┌──────────────────────────────────────┐
        │  Disclaimer banner                    │
        │  Attached image thumbnail             │
        │  ──────────────────────────────────── │
        │  Scrollable Q&A bubble area           │
        │  ──────────────────────────────────── │
        │  [📎 Attach Image]  Question  [Send]  │
        └──────────────────────────────────────┘
    """

    messages_changed    = pyqtSignal()
    token_count_updated = pyqtSignal(int)

    def __init__(
        self,
        session_id: str,
        title: str,
        store: HistoryStore,
        existing_messages: Optional[list[dict]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.session_id = session_id
        self.title      = title
        self.store      = store
        self.messages:  list[dict]  = list(existing_messages or [])
        self._bubbles:  list[QFrame] = []
        self._current_image_path: str = ""
        self._worker: Optional[ImageAnalysisWorker] = None
        self._ctx_mgr = ContextManager(model=IMAGE_MODEL)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # ── Disclaimer banner ─────────────────────────────────────────────────
        disc = QLabel(IMAGE_DISCLAIMER_HTML)
        disc.setWordWrap(True)
        disc.setTextFormat(Qt.TextFormat.RichText)
        disc.setStyleSheet(
            f"background:#fffbeb;border:1px solid {WARNING_CLR};"
            f"border-radius:8px;padding:8px 12px;color:#92400e;font-size:12px;"
        )
        outer.addWidget(disc)

        # ── Thumbnail strip ───────────────────────────────────────────────────
        self._thumb_label = QLabel("No image attached.")
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet(
            f"background:{SURFACE};border:1px dashed {BORDER};"
            f"border-radius:8px;color:{MUTED};font-size:12px;padding:6px;"
        )
        self._thumb_label.setFixedHeight(120)
        self._thumb_label.setScaledContents(False)
        outer.addWidget(self._thumb_label)

        # ── Scroll area ───────────────────────────────────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.msg_container = QWidget()
        self.msg_layout    = QVBoxLayout(self.msg_container)
        self.msg_layout.addStretch()
        self.msg_layout.setSpacing(6)
        self.scroll.setWidget(self.msg_container)
        outer.addWidget(self.scroll, stretch=1)

        # ── Input row ─────────────────────────────────────────────────────────
        inp = QHBoxLayout()
        inp.setSpacing(6)

        self.attach_btn = QPushButton("📎 Attach Image")
        self.attach_btn.setFixedHeight(38)
        self.attach_btn.setObjectName("secondary")
        self.attach_btn.clicked.connect(self._attach_image)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Ask a question about the attached image…")
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
            self._make_bubble(
                role=msg["role"],
                text=msg["content"],
                image_path=msg.get("image_path", ""),
            )

    # ── image attachment ──────────────────────────────────────────────────────

    def _attach_image(self) -> None:
        exts = " ".join(f"*{e}" for e in SUPPORTED_IMAGE_EXTS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach Dental Image", "",
            f"Image Files ({exts});;All Files (*)",
        )
        if not path:
            return
        self._current_image_path = path
        self._show_thumbnail(path)

    def _show_thumbnail(self, path: str) -> None:
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

    def _make_bubble(
        self, role: str, text: str, image_path: str = ""
    ) -> QFrame:
        is_user = role == "user"
        frame   = QFrame()
        f_lay   = QVBoxLayout(frame)
        f_lay.setContentsMargins(0, 4, 0, 4)

        # label
        lbl = QLabel("You" if is_user else f"🦷 {IMAGE_MODEL}")
        lbl.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:600;")

        inner = QVBoxLayout()
        inner.setSpacing(4)
        inner.addWidget(lbl)

        # inline thumbnail for user turns
        if is_user and image_path and Path(image_path).exists():
            px = QPixmap(image_path)
            if not px.isNull():
                img_lbl = QLabel()
                img_lbl.setPixmap(
                    px.scaled(
                        260, 180,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                img_lbl.setStyleSheet("border-radius:6px;padding:2px;")
                inner.addWidget(img_lbl)

        # text label
        txt = QLabel(text)
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        txt.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        txt.setStyleSheet(f"""
            background-color: {"#e0fdf4" if is_user else SURFACE};
            border: 1px solid {"#99f6e4" if is_user else BORDER};
            border-radius: 10px;
            padding: 10px 14px; font-size: 13px;
        """)
        inner.addWidget(txt)

        # store refs for updates / highlight
        frame._text_label = txt   # type: ignore[attr-defined]
        frame._base_style = txt.styleSheet()  # type: ignore[attr-defined]

        row = QHBoxLayout()
        if is_user:
            row.addStretch()
            row.addLayout(inner)
        else:
            row.addLayout(inner)
            row.addStretch()

        f_lay.addLayout(row)
        self._bubbles.append(frame)
        self.msg_layout.addWidget(frame)
        QApplication.processEvents()
        self._scroll_bottom()
        return frame

    def _scroll_bottom(self) -> None:
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        )

    def _set_enabled(self, v: bool) -> None:
        self.input_box.setEnabled(v)
        self.send_btn.setEnabled(v)
        self.attach_btn.setEnabled(v)

    def _persist(self) -> None:
        self.store.upsert_session(self.session_id, self.title, self.messages)
        self.messages_changed.emit()

    def scroll_to_message(self, idx: int) -> None:
        if 0 <= idx < len(self._bubbles):
            b = self._bubbles[idx]
            self.scroll.ensureWidgetVisible(b)
            orig = b._text_label.styleSheet()  # type: ignore[attr-defined]
            b._text_label.setStyleSheet(orig + f"border: 2px solid {TEAL};")  # type: ignore[attr-defined]
            QTimer.singleShot(1600, lambda: b._text_label.setStyleSheet(orig))  # type: ignore[attr-defined]

    # ── send ──────────────────────────────────────────────────────────────────

    def _send(self) -> None:
        question = self.input_box.text().strip()
        if not question:
            QMessageBox.warning(self, "No question",
                "Please type a question about the image.")
            return
        if not self._current_image_path:
            QMessageBox.warning(self, "No image",
                "Please attach a dental image first.")
            return

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

        self._ai_bubble = self._make_bubble("assistant", "⏳ Analysing image…")

        self._worker = ImageAnalysisWorker(list(self.messages))
        self._worker.result.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_result(self, text: str) -> None:
        self._ai_bubble._text_label.setText(text)  # type: ignore[attr-defined]
        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "assistant", "content": text, "ts": ts})
        self._persist()
        self.token_count_updated.emit(
            self._ctx_mgr.token_count(self.messages)
        )
        self._set_enabled(True)
        self._scroll_bottom()

    @pyqtSlot(str)
    def _on_error(self, msg: str) -> None:
        self._ai_bubble._text_label.setText(f"⚠️ {msg}")  # type: ignore[attr-defined]
        self._ai_bubble._text_label.setStyleSheet(  # type: ignore[attr-defined]
            f"background:{DANGER}22;border:1px solid {DANGER};"
            "border-radius:10px;padding:10px 14px;"
        )
        self._set_enabled(True)

    def export_pdf(self, subtitle: str = "Image Analysis") -> Optional[bytes]:
        if not self.messages:
            return None
        return export_session_to_pdf(self.title, self.messages, subtitle)


# ── Inner panel ───────────────────────────────────────────────────────────────

class _ImageInnerPanel(GenericSessionPanel):
    def __init__(self, store: HistoryStore, parent=None) -> None:
        super().__init__(store, sidebar_title="🦷 Image Sessions", parent=parent)

    def _make_tab(self, sid, title, messages) -> ImageSessionTab:
        return ImageSessionTab(sid, title, self._store, messages)

    def _new_session_title(self) -> str:
        return f"Image {self.stack.count() + 1}"

    def export_current(self) -> None:
        """Override: ImageSessionTab.export_pdf takes a subtitle arg."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        tab = self._current_tab()
        if not tab or not isinstance(tab, ImageSessionTab):
            return
        pdf = tab.export_pdf(subtitle="Image Analysis")
        if not pdf:
            QMessageBox.information(self, "Export", "No messages to export yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", f"{tab.session_id}.pdf", "PDF Files (*.pdf)"
        )
        if path:
            with open(path, "wb") as fh:
                fh.write(pdf)
            QMessageBox.information(self, "Saved", f"Exported to:\n{path}")


# ── Outer panel ───────────────────────────────────────────────────────────────

class ImageSessionPanel(QWidget):
    """Header + full disclaimer + :class:`_ImageInnerPanel`."""

    token_count_updated = pyqtSignal(int)

    def __init__(self, store: HistoryStore, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── header strip ──────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setObjectName("ctrlStrip")
        hdr.setStyleSheet(
            f"QWidget#ctrlStrip {{ background:{SURFACE};"
            f"border-bottom:1px solid {BORDER}; }}"
        )
        hdr_lay = QVBoxLayout(hdr)
        hdr_lay.setContentsMargins(16, 12, 16, 12)
        hdr_lay.setSpacing(8)

        title_row = QHBoxLayout()
        title_lbl  = heading_label("🦷 Dental Image Analysis")
        model_badge = QLabel(f"model: {IMAGE_MODEL}")
        model_badge.setStyleSheet(
            f"background:{TEAL_LIGHT};color:{TEAL_DARK};border-radius:12px;"
            f"padding:3px 10px;font-size:11px;font-weight:600;"
        )
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(model_badge)
        hdr_lay.addLayout(title_row)

        disc_full = QLabel(
            "This feature uses AI to describe features visible in dental images "
            "(X-rays, photographs, scans). "
            "<b>It does not provide medical diagnoses</b> and is intended for "
            "educational and informational purposes only. "
            "Image data is processed locally via Ollama and never sent to the cloud. "
            "Always consult a qualified dentist or specialist for clinical advice."
        )
        disc_full.setWordWrap(True)
        disc_full.setTextFormat(Qt.TextFormat.RichText)
        disc_full.setStyleSheet(f"color:{MUTED};font-size:12px;line-height:1.5;")
        hdr_lay.addWidget(disc_full)

        hint = QLabel(
            "How to use:  ① Click  📎 Attach Image  in any session tab  "
            "②  Type your question  ③  Press  Analyse ➤"
        )
        hint.setStyleSheet(
            f"background:{TEAL_LIGHT};border-radius:6px;"
            f"padding:5px 10px;color:{TEAL_DARK};font-size:12px;"
        )
        hdr_lay.addWidget(hint)
        outer.addWidget(hdr)

        # ── session panel ─────────────────────────────────────────────────────
        self._session_panel = _ImageInnerPanel(store)
        self._session_panel.token_count_updated.connect(self.token_count_updated)
        outer.addWidget(self._session_panel, stretch=1)

    def restore_session(self, sid: str, msg_index: int) -> None:
        self._session_panel.restore_session(sid, msg_index)

    def export_current(self) -> None:
        self._session_panel.export_current()
