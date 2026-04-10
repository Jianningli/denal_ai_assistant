"""
dental_ai/ui/panels/web_panel.py
==================================
Website Summary panel — fetch a URL, extract paragraphs, summarise with Ollama.
"""

from typing import Optional

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dental_ai.core.constants import GENERAL_MODEL
from dental_ai.core.utils import heading_label
from dental_ai.workers import FetchWebWorker, OllamaWorker


class WebsiteSummaryPanel(QWidget):
    """Paste any public URL → fetch → summarise."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)

        lay.addWidget(heading_label("🌐 Website Summary"))
        lay.addWidget(QLabel("Paste any public URL to get an AI summary."))

        row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/article")
        self.url_input.returnPressed.connect(self._fetch)
        fb = QPushButton("Fetch & Summarise")
        fb.clicked.connect(self._fetch)
        row.addWidget(self.url_input)
        row.addWidget(fb)
        lay.addLayout(row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Summary will appear here…")
        lay.addWidget(self.output)

        self._fw: Optional[FetchWebWorker] = None
        self._lw: Optional[OllamaWorker]   = None

    def _fetch(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "No URL", "Enter a URL.")
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "Invalid", "URL must start with http:// or https://"
            )
            return
        self.output.setText("⏳ Fetching…")
        self._fw = FetchWebWorker(url)
        self._fw.result.connect(self._on_fetched)
        self._fw.error.connect(lambda e: self.output.setText(f"⚠️ {e}"))
        self._fw.start()

    @pyqtSlot(str)
    def _on_fetched(self, text: str) -> None:
        if not text.strip():
            self.output.setText("⚠️ No readable text found.")
            return
        self.output.setText("⏳ Analysing…")
        self._lw = OllamaWorker(
            GENERAL_MODEL,
            f"Summarise the following web page content concisely:\n\n{text}",
        )
        self._lw.result.connect(lambda t: self.output.setText(t))
        self._lw.error.connect(lambda e: self.output.setText(f"⚠️ {e}"))
        self._lw.start()
