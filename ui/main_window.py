"""
dental_ai/ui/main_window.py
==============================
Top-level QMainWindow — toolbar, sidebar navigation, tool panels,
token-count status bar, search, export, and logout.
"""

from typing import Optional

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from dental_ai.core.constants import (
    BORDER,
    CTX_COMPRESS_TOKENS,
    CTX_WARN_TOKENS,
    DANGER,
    MUTED,
    TEAL,
    TEXT,
    TOOL_STATUS,
)
from dental_ai.core.history_store import HistoryStore, history_path
from dental_ai.ui.dialogs.search_dialog import SearchDialog
from dental_ai.ui.panels.chat_panel  import ChatPanel
from dental_ai.ui.panels.excel_panel import ExcelSessionPanel
from dental_ai.ui.panels.image_panel import ImageSessionPanel
from dental_ai.ui.panels.pdf_panel   import PdfSummaryPanel
from dental_ai.ui.panels.rag_panel   import RagSessionPanel
from dental_ai.ui.panels.web_panel   import WebsiteSummaryPanel


class MainWindow(QMainWindow):
    """Application main window — one instance per logged-in user."""

    def __init__(
        self, username: str, fernet_key: Optional[bytes] = None
    ) -> None:
        super().__init__()
        self.username    = username
        self._fernet_key = fernet_key
        self.setWindowTitle(f"🦷 Dental AI Assistant  —  {username}")
        self.setMinimumSize(1200, 750)
        self._search_dlg: Optional[SearchDialog] = None
        self._last_token_count: int = 0

        # ── per-user stores ───────────────────────────────────────────────────
        self._stores: dict[str, HistoryStore] = {
            kind: HistoryStore(
                history_path(username, kind), username, kind, fernet_key
            )
            for kind in ("chat", "excel", "rag", "image")
        }

        self._build_toolbar()
        self._build_central()
        self._wire_token_signals()
        self._switch_tool(0)

    # ── construction ──────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        search_act = QAction("🔍  Search History  (Ctrl+F)", self)
        search_act.setShortcut(QKeySequence("Ctrl+F"))
        search_act.triggered.connect(self._open_search)
        tb.addAction(search_act)
        tb.addSeparator()

        export_act = QAction("⬇  Export Current Session PDF", self)
        export_act.triggered.connect(self._export_current)
        tb.addAction(export_act)

    def _build_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        # ── tool panels ───────────────────────────────────────────────────────
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
        root.addWidget(self.stack)

    def _build_sidebar(self) -> QWidget:
        _nav_style = f"""
            QPushButton#navBtn {{
                background:transparent; color:{TEXT};
                border:none; border-radius:8px;
                padding:8px 12px; text-align:left; font-weight:500;
            }}
            QPushButton#navBtn:hover {{
                background:#ccfbf1; color:#0f766e;
            }}
            QPushButton#navBtn:checked {{
                background:#ccfbf1; color:#0f766e; font-weight:700;
            }}
        """

        sb_w = QWidget()
        sb_w.setObjectName("sidebar")
        sb_w.setFixedWidth(215)
        sb = QVBoxLayout(sb_w)
        sb.setContentsMargins(12, 16, 12, 16)
        sb.setSpacing(5)

        brand = QLabel("🦷 DentalAI")
        brand.setStyleSheet(f"font-size:20px;font-weight:700;color:{TEAL};")
        ulbl  = QLabel(f"Logged in as  {self.username}")
        ulbl.setStyleSheet(f"color:{MUTED};font-size:11px;")
        sb.addWidget(brand)
        sb.addWidget(ulbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};")
        sb.addWidget(sep)

        self._nav_btns: list[QPushButton] = []
        for label, idx in [
            ("💬 Chat",               0),
            ("📄 PDF Summary",        1),
            ("🌐 Website Summary",    2),
            ("📊 Excel Analysis",     3),
            ("🧠 Ask Your Document",  4),
            ("🦷 Image Analysis",     5),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("navBtn")
            btn.setStyleSheet(_nav_style)
            btn.clicked.connect(lambda _, i=idx: self._switch_tool(i))
            sb.addWidget(btn)
            self._nav_btns.append(btn)

        sb.addStretch()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color:{BORDER};")
        sb.addWidget(sep2)

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
        lo_btn.clicked.connect(self._logout)
        sb.addWidget(lo_btn)
        return sb_w

    def _wire_token_signals(self) -> None:
        for panel in (
            self._chat_panel, self._excel_panel,
            self._rag_panel,  self._image_panel,
        ):
            if hasattr(panel, "token_count_updated"):
                panel.token_count_updated.connect(self._on_token_count)

    # ── routing ───────────────────────────────────────────────────────────────

    def _switch_tool(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        self._refresh_status_bar()

    def _refresh_status_bar(self) -> None:
        idx          = self.stack.currentIndex()
        label, model = TOOL_STATUS.get(idx, ("", ""))
        tc           = self._last_token_count

        if tc == 0:
            tok_str = ""
        elif tc >= CTX_COMPRESS_TOKENS:
            tok_str = f"  ·  ⚠️ ~{tc:,} tokens (compressing)"
        elif tc >= CTX_WARN_TOKENS:
            tok_str = f"  ·  🟡 ~{tc:,} tokens (context filling)"
        else:
            tok_str = f"  ·  🟢 ~{tc:,} tokens"

        self.statusBar().showMessage(
            f"Ready  ·  {label}  ·  model: {model}"
            f"  ·  user: {self.username}{tok_str}"
        )

    @pyqtSlot(int)
    def _on_token_count(self, count: int) -> None:
        self._last_token_count = count
        self._refresh_status_bar()

    # ── search ────────────────────────────────────────────────────────────────

    def _open_search(self) -> None:
        if self._search_dlg is None:
            self._search_dlg = SearchDialog(self._stores, self)
            self._search_dlg.open_chat.connect(
                lambda sid, idx: (
                    self._switch_tool(0),
                    self._chat_panel.restore_session(sid, idx),
                )
            )
            self._search_dlg.open_excel.connect(
                lambda sid, idx: (
                    self._switch_tool(3),
                    self._excel_panel.restore_session(sid, idx),
                )
            )
            self._search_dlg.open_rag.connect(
                lambda sid, idx: (
                    self._switch_tool(4),
                    self._rag_panel.restore_session(sid, idx),
                )
            )
            self._search_dlg.open_image.connect(
                lambda sid, idx: (
                    self._switch_tool(5),
                    self._image_panel.restore_session(sid, idx),
                )
            )
        self._search_dlg.show_and_focus()

    # ── export ────────────────────────────────────────────────────────────────

    def _export_current(self) -> None:
        idx     = self.stack.currentIndex()
        targets = {
            0: self._chat_panel,
            3: self._excel_panel,
            4: self._rag_panel,
            5: self._image_panel,
        }
        panel = targets.get(idx)
        if panel:
            panel.export_current()
        else:
            QMessageBox.information(
                self, "Export",
                "PDF export is available for Chat, Excel Analysis, "
                "Ask Your Document, and Image Analysis sessions.",
            )

    # ── logout ────────────────────────────────────────────────────────────────

    def _logout(self) -> None:
        if (
            QMessageBox.question(
                self, "Log out", "Log out and return to login?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.close()
            # Defer import to avoid circular reference at module load time
            from dental_ai.app import start_login
            start_login()
