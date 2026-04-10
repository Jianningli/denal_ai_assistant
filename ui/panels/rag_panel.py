"""
dental_ai/ui/panels/rag_panel.py
==================================
RAG (Retrieval-Augmented Generation) panel — index PDFs with FAISS and
answer questions by citing source chunks.

Classes
-------
RagSessionTab   — one Q&A session against the shared FAISS index
_RagInnerPanel  — GenericSessionPanel wired to RagSessionTabs
RagSessionPanel — outer widget (file picker + index button + inner panel)
"""

from datetime import datetime
from typing import Optional

import numpy as np
from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sklearn.metrics.pairwise import cosine_similarity

from dental_ai.core.constants import (
    BORDER,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DANGER,
    GENERAL_MODEL,
    MUTED,
    RAG_TOP_K,
    SUCCESS,
    SURFACE,
    WARNING_CLR,
)
from dental_ai.core.history_store import HistoryStore
from dental_ai.core.utils import heading_label
from dental_ai.ui.widgets.base_session import BaseSessionTab, GenericSessionPanel
from dental_ai.ui.widgets.shared import ChatBubble
from dental_ai.workers import OllamaWorker, RagIndexWorker, get_embed_model


class RagSessionTab(BaseSessionTab):
    """One Q&A session that retrieves context from a FAISS index."""

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
            ai_label="🧠 RAG AI",
            placeholder="Ask a question about your indexed documents…",
            parent=parent,
        )
        self._rag_data: Optional[dict]         = None
        self._worker:   Optional[OllamaWorker]  = None
        self._current_bubble: Optional[ChatBubble] = None
        self._build_conf_bar()

    def _build_conf_bar(self) -> None:
        conf_grp = QGroupBox("Relevance Score (last answer)")
        cl = QHBoxLayout(conf_grp)
        self.conf_bar = QProgressBar()
        self.conf_bar.setRange(0, 100)
        self.conf_lbl = QLabel("—")
        cl.addWidget(self.conf_bar)
        cl.addWidget(self.conf_lbl)
        # Insert above the input row (last item in the layout)
        self.layout().insertWidget(self.layout().count() - 1, conf_grp)

    def set_rag_data(self, data: dict) -> None:
        self._rag_data = data

    def _on_send_clicked(self) -> None:
        q = self.input_box.text().strip()
        if not q:
            return
        if not self._rag_data:
            QMessageBox.warning(self, "Not indexed", "Please index documents first.")
            return

        self.input_box.clear()
        self._set_enabled(False)

        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "user", "content": q, "ts": ts})
        self._make_bubble("user", q, self._user_label)
        self._current_bubble = self._make_bubble(
            "assistant", "⏳ Thinking…", self._ai_label
        )
        self._maybe_compress_and_warn()

        # RAG retrieval
        emb   = get_embed_model()
        qe    = emb.encode([q], show_progress_bar=False)
        _, idxs = self._rag_data["index"].search(
            np.array(qe, dtype="float32"), k=RAG_TOP_K
        )

        cks, mts, ems = [], [], []
        for i in idxs[0]:
            if i == -1:
                continue
            cks.append(self._rag_data["chunks"][i])
            mts.append(self._rag_data["metadata"][i])
            ems.append(self._rag_data["embeddings"][i])

        if not cks:
            if self._current_bubble:
                self._current_bubble.text_label.setText("No relevant chunks found.")
            self._set_enabled(True)
            return

        # Confidence bar
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
            f"QProgressBar::chunk{{background:{clr};border-radius:5px;}}"
        )
        self.conf_lbl.setText(f"{conf}%  {lbl}")

        ctx = "\n\n".join(
            f"[Source {i+1} | {m['source']} | Page {m['page']}]\n{c}"
            for i, (c, m) in enumerate(zip(cks, mts))
        )
        prompt = (
            "Answer using ONLY the sources below. Cite like [Source 1].\n"
            'If not found say: "I don\'t know based on the provided documents."\n\n'
            f"Sources:\n{ctx}\n\nQuestion:\n{q}"
        )
        self._worker = OllamaWorker(GENERAL_MODEL, prompt)
        self._worker.result.connect(self._on_answer)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_answer(self, text: str) -> None:
        if self._current_bubble:
            self._current_bubble.text_label.setText(text)
        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "assistant", "content": text, "ts": ts})
        self._persist()
        self._emit_token_count()
        self._set_enabled(True)
        self._current_bubble = None
        self._scroll_bottom()

    @pyqtSlot(str)
    def _on_error(self, msg: str) -> None:
        if self._current_bubble:
            self._current_bubble.text_label.setText(f"⚠️ {msg}")
            self._current_bubble.text_label.setStyleSheet(
                f"background:{DANGER}22;border:1px solid {DANGER};"
                "border-radius:10px;padding:10px 14px;"
            )
        self._set_enabled(True)


class _RagInnerPanel(GenericSessionPanel):
    def __init__(self, store: HistoryStore, parent=None) -> None:
        self._rag_data: Optional[dict] = None
        super().__init__(store, sidebar_title="🧠 RAG Sessions", parent=parent)

    def _make_tab(self, sid, title, messages) -> RagSessionTab:
        tab = RagSessionTab(sid, title, self._store, messages)
        if self._rag_data:
            tab.set_rag_data(self._rag_data)
        return tab

    def _new_session_title(self) -> str:
        return f"RAG {self.stack.count() + 1}"

    def set_rag_data(self, data: dict) -> None:
        self._rag_data = data
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if isinstance(w, RagSessionTab):
                w.set_rag_data(data)

    def create_session(self) -> None:
        """Override to inject rag_data into newly created tabs."""
        from dental_ai.core.utils import new_session_id
        sid   = new_session_id()
        title = self._new_session_title()
        tab   = self._add_tab(sid, title, [])
        if self._rag_data and isinstance(tab, RagSessionTab):
            tab.set_rag_data(self._rag_data)
        self._store.upsert_session(sid, title, [])
        self.session_list.setCurrentRow(self.session_list.count() - 1)


class RagSessionPanel(QWidget):
    """
    Top: file picker + index button (shared across sessions).
    Bottom: :class:`_RagInnerPanel` with :class:`RagSessionTab` instances.
    """

    token_count_updated = pyqtSignal(int)

    def __init__(self, store: HistoryStore, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── top strip ─────────────────────────────────────────────────────────
        ctrl = QWidget()
        ctrl.setObjectName("ctrlStrip")
        ctrl.setStyleSheet(
            f"QWidget#ctrlStrip {{ background:{SURFACE};"
            f"border-bottom:1px solid {BORDER}; }}"
        )
        ctrl_lay = QVBoxLayout(ctrl)
        ctrl_lay.setContentsMargins(16, 12, 16, 10)
        ctrl_lay.setSpacing(6)

        ctrl_lay.addWidget(heading_label("🧠 Ask Your Document (RAG)"))
        ctrl_lay.addWidget(QLabel(
            "Upload and index PDFs, then ask questions across multiple sessions. "
            "Answers cite sources from your documents."
        ))

        row = QHBoxLayout()
        self.files_lbl = QLineEdit()
        self.files_lbl.setReadOnly(True)
        self.files_lbl.setPlaceholderText("No files selected…")
        bb = QPushButton("Browse PDFs…")
        bb.clicked.connect(self._browse)
        self.idx_btn = QPushButton("Index Documents")
        self.idx_btn.clicked.connect(self._index)
        row.addWidget(self.files_lbl, stretch=1)
        row.addWidget(bb)
        row.addWidget(self.idx_btn)
        ctrl_lay.addLayout(row)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color:{MUTED};font-size:12px;")
        ctrl_lay.addWidget(self.status_lbl)
        outer.addWidget(ctrl)

        # ── session panel ─────────────────────────────────────────────────────
        self._session_panel = _RagInnerPanel(store)
        self._session_panel.token_count_updated.connect(self.token_count_updated)
        outer.addWidget(self._session_panel, stretch=1)

        self._files: list[str] = []
        self._rag_data: Optional[dict] = None
        self._iw: Optional[RagIndexWorker] = None

    def _browse(self) -> None:
        ps, _ = QFileDialog.getOpenFileNames(
            self, "Open PDFs", "", "PDF Files (*.pdf)"
        )
        if not ps:
            return
        self._files = ps
        from pathlib import Path
        self.files_lbl.setText("; ".join(Path(p).name for p in ps))

    def _index(self) -> None:
        if not self._files:
            QMessageBox.warning(self, "No files", "Select PDFs first.")
            return
        self.status_lbl.setText("⏳ Indexing…")
        self.idx_btn.setEnabled(False)
        self._iw = RagIndexWorker(self._files)
        self._iw.done.connect(self._on_indexed)
        self._iw.error.connect(
            lambda e: (
                self.status_lbl.setText(f"⚠️ {e}"),
                self.idx_btn.setEnabled(True),
            )
        )
        self._iw.start()

    @pyqtSlot(dict)
    def _on_indexed(self, data: dict) -> None:
        self._rag_data = data
        cs = data.get("chunk_size", CHUNK_SIZE)
        co = data.get("chunk_overlap", CHUNK_OVERLAP)
        self.status_lbl.setText(
            f"✅ Indexed {len(self._files)} file(s) → "
            f"{len(data['chunks'])} chunks  "
            f"(size {cs}, overlap {co}).  Ready to answer questions."
        )
        self.idx_btn.setEnabled(True)
        self._session_panel.set_rag_data(data)

    def restore_session(self, sid: str, msg_index: int) -> None:
        self._session_panel.restore_session(sid, msg_index)

    def export_current(self) -> None:
        self._session_panel.export_current()
