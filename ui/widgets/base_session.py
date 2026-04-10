"""
dental_ai/ui/widgets/base_session.py
======================================
Abstract base classes that power the session management pattern shared
across Chat, Excel, and RAG panels.

BaseSessionTab       — scrollable bubble area + input row
GenericSessionPanel  — sidebar (new/rename/delete/export) + QStackedWidget
"""

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dental_ai.core.constants import BORDER, MUTED, TEAL, TEAL_DARK, TEAL_LIGHT, TEXT
from dental_ai.core.context_manager import ContextManager
from dental_ai.core.history_store import HistoryStore
from dental_ai.core.pdf_export import export_session_to_pdf
from dental_ai.core.utils import new_session_id
from .shared import ChatBubble


# ── BaseSessionTab ─────────────────────────────────────────────────────────────

class BaseSessionTab(QWidget):
    """
    Provides a scrollable bubble area + input row.

    Subclasses **must** implement :meth:`_on_send_clicked` and may call the
    protected helpers ``_add_bubble``, ``_append_to_last_bubble``, and
    ``_finalize``.
    """

    messages_changed    = pyqtSignal()
    token_count_updated = pyqtSignal(int)

    def __init__(
        self,
        session_id: str,
        title: str,
        store: HistoryStore,
        existing_messages: Optional[list[dict]] = None,
        user_label: str  = "You",
        ai_label: str    = "🦷 Dental AI",
        placeholder: str = "Type your question…",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.session_id = session_id
        self.title      = title
        self.store      = store
        self.messages: list[dict]    = list(existing_messages or [])
        self._bubbles: list[ChatBubble] = []
        self._user_label = user_label
        self._ai_label   = ai_label
        self._ctx_mgr    = ContextManager()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
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
        inp.addWidget(self.input_box)
        inp.addWidget(self.send_btn)
        lay.addLayout(inp)

        # Restore existing bubbles from history
        for msg in self.messages:
            lbl = self._user_label if msg["role"] == "user" else self._ai_label
            self._make_bubble(msg["role"], msg["content"], lbl)

    # ── bubble helpers ────────────────────────────────────────────────────────

    def _make_bubble(
        self, role: str, text: str, label: str = ""
    ) -> ChatBubble:
        b = ChatBubble(role, label_override=label, text=text)
        self._bubbles.append(b)
        self.msg_layout.addWidget(b)
        QApplication.processEvents()
        self._scroll_bottom()
        return b

    def _scroll_bottom(self) -> None:
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        )

    def _set_enabled(self, enabled: bool) -> None:
        self.input_box.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)

    def _persist(self) -> None:
        self.store.upsert_session(self.session_id, self.title, self.messages)
        self.messages_changed.emit()

    def _emit_token_count(self) -> None:
        self.token_count_updated.emit(
            self._ctx_mgr.token_count(self.messages)
        )

    def _maybe_compress_and_warn(self) -> bool:
        """Compress context if needed; insert a notice bubble. Returns True if compressed."""
        if not self._ctx_mgr.needs_compression(self.messages):
            return False
        new_msgs, did_compress = self._ctx_mgr.maybe_compress(self.messages)
        if did_compress:
            self.messages = new_msgs
            notice = ChatBubble(
                "assistant",
                label_override="⚙ System",
                text=(
                    "📋 Context compressed — earlier turns summarised to stay "
                    "within the model's context window. Recent messages are intact."
                ),
            )
            notice.text_label.setStyleSheet(
                f"background:#f0fdf4;border:1px dashed {TEAL};"
                "border-radius:10px;padding:8px 12px;font-size:12px;"
                f"color:{TEAL_DARK};"
            )
            self._bubbles.append(notice)
            self.msg_layout.addWidget(notice)
            self._scroll_bottom()
        return did_compress

    def scroll_to_message(self, idx: int) -> None:
        if 0 <= idx < len(self._bubbles):
            self.scroll.ensureWidgetVisible(self._bubbles[idx])
            self._bubbles[idx].flash_highlight()

    def _on_send_clicked(self) -> None:
        raise NotImplementedError

    def export_pdf(self, subtitle: str = "") -> Optional[bytes]:
        if not self.messages:
            return None
        return export_session_to_pdf(self.title, self.messages, subtitle)


# ── GenericSessionPanel ────────────────────────────────────────────────────────

class GenericSessionPanel(QWidget):
    """
    Sidebar (new / rename / delete / export PDF) + right-side QStackedWidget.

    Subclasses **must** implement :meth:`_make_tab`.
    """

    token_count_updated = pyqtSignal(int)

    def __init__(
        self,
        store: HistoryStore,
        sidebar_title: str = "Sessions",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._store = store

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── sidebar ───────────────────────────────────────────────────────────
        sb = QWidget()
        sb.setObjectName("sidebar")
        sb.setFixedWidth(215)
        sb_lay = QVBoxLayout(sb)
        sb_lay.setContentsMargins(10, 10, 10, 10)
        sb_lay.setSpacing(5)

        sb_lay.addWidget(
            QLabel(sidebar_title,
                   styleSheet=f"font-weight:700;color:{TEXT};font-size:13px;")
        )

        new_btn = QPushButton("＋ New Session")
        new_btn.clicked.connect(self.create_session)
        sb_lay.addWidget(new_btn)

        self.session_list = QListWidget()
        self.session_list.currentRowChanged.connect(self._switch_session)
        sb_lay.addWidget(self.session_list, stretch=1)

        for label, slot in [
            ("✏  Rename",      self._rename),
            ("🗑  Delete",      self._delete),
            ("⬇  Export PDF",  self.export_current),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("secondary")
            btn.clicked.connect(slot)
            sb_lay.addWidget(btn)

        lay.addWidget(sb)

        # ── session stack ─────────────────────────────────────────────────────
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)

        self._load_history()
        if self.stack.count() == 0:
            self.create_session()

    # ── to override ───────────────────────────────────────────────────────────

    def _make_tab(
        self, sid: str, title: str, messages: list[dict]
    ) -> BaseSessionTab:
        raise NotImplementedError

    def _new_session_title(self) -> str:
        return f"Session {self.stack.count() + 1}"

    # ── history ───────────────────────────────────────────────────────────────

    def _load_history(self) -> None:
        for sid, data in self._store.all_sessions().items():
            self._add_tab(sid, data.get("title", sid), data.get("messages", []))
        if self.session_list.count():
            self.session_list.setCurrentRow(0)

    def _add_tab(
        self, sid: str, title: str, messages: list[dict]
    ) -> BaseSessionTab:
        tab = self._make_tab(sid, title, messages)
        if hasattr(tab, "token_count_updated"):
            tab.token_count_updated.connect(self.token_count_updated)
        self.stack.addWidget(tab)
        item = QListWidgetItem(f"▸ {title}")
        item.setData(Qt.ItemDataRole.UserRole, sid)
        self.session_list.addItem(item)
        return tab

    # ── session CRUD ──────────────────────────────────────────────────────────

    def create_session(self) -> None:
        sid   = new_session_id()
        title = self._new_session_title()
        self._add_tab(sid, title, [])
        self._store.upsert_session(sid, title, [])
        self.session_list.setCurrentRow(self.session_list.count() - 1)

    def _switch_session(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    def _current_tab(self) -> Optional[BaseSessionTab]:
        idx = self.stack.currentIndex()
        return self.stack.widget(idx) if idx >= 0 else None

    def _rename(self) -> None:
        tab = self._current_tab()
        if not tab:
            return
        new_title, ok = QInputDialog.getText(
            self, "Rename", "New title:", text=tab.title
        )
        if ok and new_title.strip():
            tab.title = new_title.strip()
            row = self.session_list.currentRow()
            self.session_list.item(row).setText(f"▸ {tab.title}")
            self._store.upsert_session(tab.session_id, tab.title, tab.messages)

    def _delete(self) -> None:
        row = self.session_list.currentRow()
        if row < 0:
            return
        tab: BaseSessionTab = self.stack.widget(row)
        if (
            QMessageBox.question(
                self, "Delete", f"Delete '{tab.title}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self._store.delete_session(tab.session_id)
            self.stack.removeWidget(tab)
            self.session_list.takeItem(row)
            tab.deleteLater()

    def restore_session(self, sid: str, msg_index: int) -> None:
        for i in range(self.session_list.count()):
            if self.session_list.item(i).data(Qt.ItemDataRole.UserRole) == sid:
                self.session_list.setCurrentRow(i)
                QApplication.processEvents()
                self.stack.widget(i).scroll_to_message(msg_index)
                return
        data = self._store.get_session(sid)
        if data:
            tab = self._add_tab(
                sid, data.get("title", sid), data.get("messages", [])
            )
            self.session_list.setCurrentRow(self.session_list.count() - 1)
            QApplication.processEvents()
            tab.scroll_to_message(msg_index)

    def export_current(self) -> None:
        tab = self._current_tab()
        if not tab:
            return
        pdf = tab.export_pdf(subtitle=self._store._kind.upper())
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
