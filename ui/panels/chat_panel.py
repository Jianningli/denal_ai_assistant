"""
dental_ai/ui/panels/chat_panel.py
===================================
Plain conversational chat with streaming Ollama responses.

Classes
-------
ChatTab   — one chat session (streaming)
ChatPanel — sidebar + stacked ChatTabs
"""

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMessageBox

from dental_ai.core.constants import CHAT_MODEL, DANGER
from dental_ai.core.history_store import HistoryStore
from dental_ai.ui.widgets.base_session import BaseSessionTab, GenericSessionPanel
from dental_ai.ui.widgets.shared import ChatBubble
from dental_ai.workers import ChatWorker


class ChatTab(BaseSessionTab):
    """One streaming chat session against ``CHAT_MODEL``."""

    def __init__(
        self,
        session_id: str,
        title: str,
        store: HistoryStore,
        existing_messages: Optional[list[dict]] = None,
        parent=None,
    ) -> None:
        super().__init__(
            session_id, title, store, existing_messages,
            placeholder="Ask me anything about dental health…",
            parent=parent,
        )
        self._worker: Optional[ChatWorker]        = None
        self._current_bubble: Optional[ChatBubble] = None

    def _on_send_clicked(self) -> None:
        text = self.input_box.text().strip()
        if not text:
            return
        self.input_box.clear()
        self._set_enabled(False)

        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "user", "content": text, "ts": ts})
        self._make_bubble("user", text, self._user_label)

        self._maybe_compress_and_warn()

        self._current_bubble = self._make_bubble("assistant", "", self._ai_label)
        self._worker = ChatWorker(CHAT_MODEL, list(self.messages))
        self._worker.token_received.connect(self._on_token)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_token(self, token: str) -> None:
        if self._current_bubble:
            self._current_bubble.append_text(token)
            self._scroll_bottom()

    @pyqtSlot(str)
    def _on_finished(self, full: str) -> None:
        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "assistant", "content": full, "ts": ts})
        self._persist()
        self._emit_token_count()
        self._set_enabled(True)
        self._current_bubble = None

    @pyqtSlot(str)
    def _on_error(self, msg: str) -> None:
        if self._current_bubble:
            self._current_bubble.text_label.setText(f"⚠️ {msg}")
            self._current_bubble.text_label.setStyleSheet(
                f"background:{DANGER}22;border:1px solid {DANGER};"
                "border-radius:10px;padding:10px 14px;"
            )
        self._set_enabled(True)


class ChatPanel(GenericSessionPanel):
    """Sidebar + stacked :class:`ChatTab` instances."""

    token_count_updated = pyqtSignal(int)

    def __init__(self, store: HistoryStore, parent=None) -> None:
        super().__init__(store, sidebar_title="💬 Chat Sessions", parent=parent)

    def _make_tab(self, sid, title, messages) -> ChatTab:
        return ChatTab(sid, title, self._store, messages)

    def _new_session_title(self) -> str:
        return f"Chat {self.stack.count() + 1}"
