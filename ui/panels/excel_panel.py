"""
dental_ai/ui/panels/excel_panel.py
=====================================
Excel Analysis feature: file picker + sheet preview + Matplotlib chart +
multi-session Q&A against any loaded spreadsheet.

Classes
-------
ExcelSessionTab   — one Q&A session tied to an Excel file
_ExcelInnerPanel  — GenericSessionPanel wired to ExcelSessionTabs
ExcelSessionPanel — outer widget (file picker, preview, chart, inner panel)
"""

from datetime import datetime
from typing import Optional

import ollama
import pandas as pd
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dental_ai.core.constants import (
    BORDER,
    DANGER,
    GENERAL_MODEL,
    MAX_CONTEXT_CHARS,
    MUTED,
    SURFACE,
)
from dental_ai.core.history_store import HistoryStore
from dental_ai.core.utils import heading_label, safe_json_parse
from dental_ai.ui.widgets.base_session import BaseSessionTab, GenericSessionPanel
from dental_ai.ui.widgets.shared import ChatBubble, MatplotlibCanvas
from dental_ai.workers import OllamaWorker


class ExcelSessionTab(BaseSessionTab):
    """
    One Q&A session against a loaded Excel file.
    The file path is stored in session metadata so it can be displayed on restore.
    """

    def __init__(
        self,
        session_id: str,
        title: str,
        store: HistoryStore,
        existing_messages: Optional[list[dict]] = None,
        excel_path: str = "",
        parent=None,
    ) -> None:
        super().__init__(
            session_id, title, store, existing_messages,
            ai_label="📊 Excel AI",
            placeholder="Ask a question about the loaded spreadsheet…",
            parent=parent,
        )
        self._excel_path = excel_path
        self._xls:    Optional[pd.ExcelFile] = None
        self._df:     Optional[pd.DataFrame] = None
        self._canvas: Optional[MatplotlibCanvas] = None
        self._worker: Optional[OllamaWorker]  = None
        self._current_bubble: Optional[ChatBubble] = None

        if excel_path:
            self._try_load_excel(excel_path)

    # ── file helpers ──────────────────────────────────────────────────────────

    def attach_canvas(self, canvas: MatplotlibCanvas) -> None:
        self._canvas = canvas

    def _try_load_excel(self, path: str) -> None:
        try:
            self._xls        = pd.ExcelFile(path)
            self._excel_path = path
        except Exception:
            self._xls = None

    def load_sheet(self, sheet: str) -> None:
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
        for name in self._xls.sheet_names:
            try:
                df = pd.read_excel(self._xls, sheet_name=name)
                if not df.empty:
                    blocks.append(
                        f"=== Sheet: {name} ===\n"
                        f"{df.head(50).to_string()[:budget]}"
                    )
            except Exception:
                pass
        return "\n\n".join(blocks)

    # ── send ─────────────────────────────────────────────────────────────────

    def _on_send_clicked(self) -> None:
        question = self.input_box.text().strip()
        if not question:
            return
        if not self._xls:
            QMessageBox.warning(self, "No file", "Please load an Excel file first.")
            return

        self.input_box.clear()
        self._set_enabled(False)

        ts = datetime.now().isoformat(timespec="seconds")
        self.messages.append({"role": "user", "content": question, "ts": ts})
        self._make_bubble("user", question, self._user_label)
        self._current_bubble = self._make_bubble(
            "assistant", "⏳ Analysing…", self._ai_label
        )
        self._maybe_compress_and_warn()

        # Auto-chart (sync, quick)
        if self._df is not None and not self._df.empty and self._canvas:
            self._try_auto_chart(question)

        # LLM answer (async)
        ctx    = self._build_context()
        prompt = (
            "You have access to all sheets of an Excel workbook.\n"
            "Use data from any relevant sheet; state which sheet you draw from.\n\n"
            f"{ctx}\n\nQuestion:\n{question}"
        )
        self._worker = OllamaWorker(GENERAL_MODEL, prompt)
        self._worker.result.connect(self._on_answer)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _try_auto_chart(self, question: str) -> None:
        chart_prompt = (
            "You are a data analyst. Given column names and a user question, "
            "pick the single best chart.\n"
            'Respond ONLY with valid JSON, no markdown:\n'
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
                    f"Columns '{xc}'/'{yc}' not found in sheet."
                )
        except Exception:
            self._canvas.show_message("Auto-chart not available for this question.")

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


class _ExcelInnerPanel(GenericSessionPanel):
    """Inner panel wired to ExcelSessionTab and a shared MatplotlibCanvas."""

    def __init__(
        self,
        store: HistoryStore,
        canvas: MatplotlibCanvas,
        parent=None,
    ) -> None:
        self._canvas = canvas
        super().__init__(store, sidebar_title="📊 Excel Sessions", parent=parent)

    def _make_tab(self, sid, title, messages) -> ExcelSessionTab:
        tab = ExcelSessionTab(sid, title, self._store, messages)
        tab.attach_canvas(self._canvas)
        return tab

    def _new_session_title(self) -> str:
        return f"Excel {self.stack.count() + 1}"

    def _switch_session(self, row: int) -> None:
        super()._switch_session(row)
        tab = self._current_tab()
        if tab and isinstance(tab, ExcelSessionTab):
            tab.attach_canvas(self._canvas)


class ExcelSessionPanel(QWidget):
    """
    Top: file picker + sheet selector + data preview + chart.
    Bottom: :class:`_ExcelInnerPanel` (sidebar + chat bubbles).
    """

    token_count_updated = pyqtSignal(int)

    def __init__(self, store: HistoryStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── top controls strip ────────────────────────────────────────────────
        ctrl = QWidget()
        ctrl.setObjectName("ctrlStrip")
        ctrl.setStyleSheet(
            f"QWidget#ctrlStrip {{ background:{SURFACE};"
            f"border-bottom:1px solid {BORDER}; }}"
        )
        ctrl_lay = QVBoxLayout(ctrl)
        ctrl_lay.setContentsMargins(16, 12, 16, 10)
        ctrl_lay.setSpacing(6)

        ctrl_lay.addWidget(heading_label("📊 Excel Analysis"))
        ctrl_lay.addWidget(QLabel(
            "Load a spreadsheet, preview sheets, then ask questions across "
            "multiple sessions. A chart is auto-generated per question."
        ))

        # file picker
        fr = QHBoxLayout()
        self.path_lbl = QLineEdit()
        self.path_lbl.setReadOnly(True)
        self.path_lbl.setPlaceholderText("No file selected…")
        bb = QPushButton("Browse…")
        bb.clicked.connect(self._browse)
        fr.addWidget(self.path_lbl, stretch=1)
        fr.addWidget(bb)
        ctrl_lay.addLayout(fr)

        # sheet selector
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Preview sheet:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._load_sheet)
        sr.addWidget(self.sheet_combo)
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;")
        sr.addWidget(self.info_lbl)
        sr.addStretch()
        ctrl_lay.addLayout(sr)
        outer.addWidget(ctrl)

        # ── main splitter ─────────────────────────────────────────────────────
        main_split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 4, 8)
        left_lay.setSpacing(6)

        vert_split = QSplitter(Qt.Orientation.Vertical)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet(
            f"font-family:monospace;font-size:11px;background:{SURFACE};"
        )
        vert_split.addWidget(self.preview)

        self.canvas = MatplotlibCanvas()
        self.canvas.setMinimumHeight(180)
        vert_split.addWidget(self.canvas)
        vert_split.setSizes([150, 200])
        left_lay.addWidget(vert_split)
        main_split.addWidget(left)

        self._session_panel = _ExcelInnerPanel(store, self.canvas)
        self._session_panel.token_count_updated.connect(self.token_count_updated)
        main_split.addWidget(self._session_panel)
        main_split.setSizes([380, 620])
        outer.addWidget(main_split, stretch=1)

        self._xls: Optional[pd.ExcelFile] = None

    # ── file / sheet ──────────────────────────────────────────────────────────

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, "Open Excel", "", "Excel Files (*.xlsx *.xls)"
        )
        if not p:
            return
        self.path_lbl.setText(p)
        try:
            self._xls = pd.ExcelFile(p)
            self.sheet_combo.clear()
            self.sheet_combo.addItems(self._xls.sheet_names)
            self.info_lbl.setText(f"{len(self._xls.sheet_names)} sheet(s)")
            self._notify_file_loaded(p)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _load_sheet(self) -> None:
        if not self._xls:
            return
        s = self.sheet_combo.currentText()
        if not s:
            return
        try:
            df = pd.read_excel(self._xls, sheet_name=s)
            self.preview.setText(df.head(20).to_string())
            self._notify_sheet_loaded(df)
        except Exception as exc:
            self.preview.setText(f"Error: {exc}")

    def _notify_file_loaded(self, path: str) -> None:
        tab = self._session_panel._current_tab()
        if tab and isinstance(tab, ExcelSessionTab):
            tab._try_load_excel(path)

    def _notify_sheet_loaded(self, df: pd.DataFrame) -> None:
        tab = self._session_panel._current_tab()
        if tab and isinstance(tab, ExcelSessionTab):
            tab._df = df

    def restore_session(self, sid: str, msg_index: int) -> None:
        self._session_panel.restore_session(sid, msg_index)

    def export_current(self) -> None:
        self._session_panel.export_current()
