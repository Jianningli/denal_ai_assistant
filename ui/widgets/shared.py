"""
dental_ai/ui/widgets/shared.py
================================
Reusable leaf widgets used across multiple panels.

Classes
-------
ChatBubble        — single message bubble (user or assistant)
MatplotlibCanvas  — embedded Matplotlib figure for the Excel panel
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from dental_ai.core.constants import BORDER, MUTED, SURFACE, TEAL


# ── ChatBubble ────────────────────────────────────────────────────────────────

class ChatBubble(QFrame):
    """A single chat bubble aligned left (AI) or right (user)."""

    def __init__(
        self,
        role: str,
        label_override: str = "",
        text: str = "",
        parent=None,
    ) -> None:
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
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.text_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.text_label.setStyleSheet(f"""
            background-color: {"#e0fdf4" if is_user else SURFACE};
            border: 1px solid {"#99f6e4" if is_user else BORDER};
            border-radius: 10px;
            padding: 10px 14px; font-size: 13px;
        """)
        self._base_style = self.text_label.styleSheet()

        inner = QVBoxLayout()
        inner.addWidget(lbl)
        inner.addWidget(self.text_label)
        inner.setSpacing(2)

        row = QHBoxLayout()
        if is_user:
            row.addStretch()
            row.addLayout(inner)
        else:
            row.addLayout(inner)
            row.addStretch()

        lay.addLayout(row)

    def append_text(self, token: str) -> None:
        """Append *token* to the bubble's text (used during streaming)."""
        self.text_label.setText(self.text_label.text() + token)

    def flash_highlight(self) -> None:
        """Briefly highlight the bubble with a teal border (search jump)."""
        hi = self._base_style + f"border: 2px solid {TEAL};"
        self.text_label.setStyleSheet(hi)
        QTimer.singleShot(
            1600, lambda: self.text_label.setStyleSheet(self._base_style)
        )


# ── MatplotlibCanvas ──────────────────────────────────────────────────────────

class MatplotlibCanvas(FigureCanvas):
    """Embedded Matplotlib figure widget for the Excel analysis panel."""

    def __init__(self, parent=None) -> None:
        self.fig = Figure(figsize=(5, 3.2), facecolor=SURFACE)
        self.ax  = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._show_placeholder()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _show_placeholder(self) -> None:
        self.ax.clear()
        self.ax.text(
            0.5, 0.5,
            "Chart will appear here after analysis",
            ha="center", va="center",
            color="#94a3b8", fontsize=10,
            transform=self.ax.transAxes,
        )
        self.ax.set_axis_off()
        self.draw()

    def _style(self, title: str, xlabel: str, ylabel: str) -> None:
        self.ax.set_title(title, fontsize=10, pad=8)
        self.ax.set_xlabel(xlabel, fontsize=9)
        self.ax.set_ylabel(ylabel, fontsize=9)
        self.ax.tick_params(axis="x", rotation=35, labelsize=8)
        self.ax.tick_params(axis="y", labelsize=8)
        self.ax.spines[["top", "right"]].set_visible(False)
        self.ax.set_axis_on()
        self.fig.tight_layout()

    # ── public plot methods ───────────────────────────────────────────────────

    def plot_bar(self, df, x_col: str, y_col: str, title: str = "") -> None:
        self.ax.clear()
        (
            df[[x_col, y_col]].dropna()
            .groupby(x_col, as_index=True)[y_col].mean()
            .plot(kind="bar", ax=self.ax, color=TEAL, edgecolor="white")
        )
        self._style(title, x_col, y_col)
        self.draw()

    def plot_line(self, df, x_col: str, y_col: str, title: str = "") -> None:
        self.ax.clear()
        sub = df[[x_col, y_col]].dropna().reset_index(drop=True)
        self.ax.plot(
            sub[x_col].astype(str), sub[y_col],
            color=TEAL, marker="o", linewidth=2, markersize=5,
        )
        self._style(title, x_col, y_col)
        self.draw()

    def show_message(self, msg: str) -> None:
        self.ax.clear()
        self.ax.text(
            0.5, 0.5, msg,
            ha="center", va="center",
            color="#94a3b8", fontsize=9,
            transform=self.ax.transAxes, wrap=True,
        )
        self.ax.set_axis_off()
        self.draw()
