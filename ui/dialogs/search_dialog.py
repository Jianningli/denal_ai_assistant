"""
dental_ai/ui/dialogs/search_dialog.py
========================================
Cross-session, cross-tool keyword search dialog with date-range filter,
scope toggles, preview pane, and direct navigation to results.
"""

import re
from datetime import date
from typing import Optional

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat
from PyQt6.QtWidgets import (
    QDateEdit,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from dental_ai.core.constants import (
    BORDER,
    HIGHLIGHT,
    MUTED,
    SURFACE,
    TEAL,
    TEXT,
)
from dental_ai.core.history_store import HistoryStore


class SearchDialog(QDialog):
    """Searches across chat, excel, rag, and image sessions."""

    open_chat  = pyqtSignal(str, int)
    open_excel = pyqtSignal(str, int)
    open_rag   = pyqtSignal(str, int)
    open_image = pyqtSignal(str, int)

    def __init__(
        self, stores: dict[str, HistoryStore], parent=None
    ) -> None:
        super().__init__(parent)
        self._stores  = stores
        self._results: list[dict] = []

        self.setWindowTitle("🔍 Search Chat History")
        self.setMinimumSize(760, 580)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # header
        hdr = QLabel("Search Chat History")
        hdr.setStyleSheet(f"font-size:16px;font-weight:700;color:{TEXT};margin-bottom:2px;")
        root.addWidget(hdr)
        sub = QLabel(
            "Searches across Chat, Excel Analysis, RAG, and Image Analysis "
            "sessions for the current user. Double-click a result to open it."
        )
        sub.setStyleSheet(f"color:{MUTED};font-size:12px;")
        root.addWidget(sub)

        # keyword row
        kw_row = QHBoxLayout()
        self.kw_input = QLineEdit()
        self.kw_input.setPlaceholderText("Type a keyword…")
        self.kw_input.setMinimumHeight(36)
        self.kw_input.returnPressed.connect(self._run_search)
        kw_row.addWidget(self.kw_input, stretch=1)
        search_btn = QPushButton("Search")
        search_btn.setFixedHeight(36)
        search_btn.clicked.connect(self._run_search)
        kw_row.addWidget(search_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(36)
        clear_btn.setObjectName("secondary")
        clear_btn.clicked.connect(self._clear)
        kw_row.addWidget(clear_btn)
        root.addLayout(kw_row)

        # scope toggles
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Search in:"))
        self.scope_chat  = self._scope_btn("💬 Chat")
        self.scope_excel = self._scope_btn("📊 Excel")
        self.scope_rag   = self._scope_btn("🧠 RAG")
        self.scope_image = self._scope_btn("🦷 Images")
        for b in (self.scope_chat, self.scope_excel, self.scope_rag, self.scope_image):
            scope_row.addWidget(b)
        scope_row.addStretch()
        root.addLayout(scope_row)

        # date filter
        date_grp = QGroupBox("Date Range Filter")
        d_lay    = QHBoxLayout(date_grp)
        self.use_date_cb = QPushButton("Enable Date Filter")
        self.use_date_cb.setCheckable(True)
        self.use_date_cb.setChecked(False)
        self.use_date_cb.setObjectName("secondary")
        self.use_date_cb.setFixedHeight(28)
        self.use_date_cb.toggled.connect(self._toggle_date)
        d_lay.addWidget(self.use_date_cb)
        d_lay.addSpacing(12)
        d_lay.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate(2020, 1, 1))
        self.date_from.setDisplayFormat("dd MMM yyyy")
        self.date_from.setEnabled(False)
        d_lay.addWidget(self.date_from)
        d_lay.addSpacing(8)
        d_lay.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat("dd MMM yyyy")
        self.date_to.setEnabled(False)
        d_lay.addWidget(self.date_to)
        d_lay.addStretch()
        root.addWidget(date_grp)

        self.count_lbl = QLabel("Enter a keyword and press Search.")
        self.count_lbl.setStyleSheet(f"color:{MUTED};font-size:12px;")
        root.addWidget(self.count_lbl)

        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
        self.results_list.currentRowChanged.connect(self._on_row_changed)
        self.results_list.itemDoubleClicked.connect(lambda _: self._open_selected())
        root.addWidget(self.results_list, stretch=1)

        prev_grp = QGroupBox("Message Preview  (keyword highlighted)")
        prev_lay = QVBoxLayout(prev_grp)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(110)
        self.preview.setStyleSheet(
            f"background:{SURFACE};border:1px solid {BORDER};border-radius:8px;"
        )
        prev_lay.addWidget(self.preview)
        root.addWidget(prev_grp)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Open Session  ↗")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_selected)
        btn_row.addStretch()
        btn_row.addWidget(self.open_btn)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _scope_btn(label: str) -> QPushButton:
        b = QPushButton(label)
        b.setCheckable(True)
        b.setChecked(True)
        b.setObjectName("scopeBtn")
        b.setFixedHeight(30)
        return b

    def _toggle_date(self, checked: bool) -> None:
        self.date_from.setEnabled(checked)
        self.date_to.setEnabled(checked)
        self.use_date_cb.setText(
            "✓ Date Filter Active" if checked else "Enable Date Filter"
        )

    def _run_search(self) -> None:
        kw = self.kw_input.text().strip()
        df = dt = None
        if self.use_date_cb.isChecked():
            qf = self.date_from.date()
            qt = self.date_to.date()
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
        self.results_list.clear()
        self.preview.clear()
        self.open_btn.setEnabled(False)

        if not self._results:
            self.count_lbl.setText("No results found.")
            return

        n_sess = len({r["sid"] for r in self._results})
        self.count_lbl.setText(
            f"{len(self._results)} result(s) across {n_sess} session(s)."
        )

        kind_icons = {"chat": "💬", "excel": "📊", "rag": "🧠", "image": "🦷"}
        for i, r in enumerate(self._results):
            created  = r["created"][:10] if r["created"] else "?"
            role_ico = "👤" if r["role"] == "user" else "🤖"
            tool_ico = kind_icons.get(r.get("kind", "chat"), "💬")
            item = QListWidgetItem(
                f"{tool_ico} {role_ico}  [{created}]  {r['title']}   —   "
                f"{r['snippet'][:85]}"
            )
            item.setToolTip(r["snippet"])
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.results_list.addItem(item)

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._results):
            return
        r  = self._results[row]
        kw = r.get("keyword", "")
        self.open_btn.setEnabled(True)
        self.preview.clear()
        cursor   = self.preview.textCursor()
        fmt_norm = QTextCharFormat()
        fmt_hi   = QTextCharFormat()
        fmt_hi.setBackground(QColor(HIGHLIGHT))
        fmt_hi.setFontWeight(700)
        content  = r["content"]
        if kw:
            lower, last = content.lower(), 0
            for m in re.finditer(re.escape(kw), lower):
                cursor.insertText(content[last: m.start()], fmt_norm)
                cursor.insertText(content[m.start(): m.end()], fmt_hi)
                last = m.end()
            cursor.insertText(content[last:], fmt_norm)
        else:
            self.preview.setPlainText(content)

    def _open_selected(self) -> None:
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self._results):
            return
        r    = self._results[row]
        kind = r.get("kind", "chat")
        sig  = {
            "chat":  self.open_chat,
            "excel": self.open_excel,
            "rag":   self.open_rag,
            "image": self.open_image,
        }.get(kind, self.open_chat)
        sig.emit(r["sid"], r["msg_index"])
        self.close()

    def _clear(self) -> None:
        self.kw_input.clear()
        self.results_list.clear()
        self.preview.clear()
        self.count_lbl.setText("Enter a keyword and press Search.")
        self._results = []
        self.open_btn.setEnabled(False)

    def show_and_focus(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.kw_input.setFocus()
