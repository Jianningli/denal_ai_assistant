"""
dental_ai/ui/panels/pdf_panel.py
==================================
PDF Summary panel — extract text from a PDF and summarise it with Ollama.
"""

from typing import Optional

import pdfplumber
from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dental_ai.core.constants import GENERAL_MODEL, MAX_CONTEXT_CHARS
from dental_ai.core.utils import heading_label
from dental_ai.workers import OllamaWorker

_LENGTH_MAP = {
    "Short (1-2 paragraphs)": "in 1-2 short paragraphs",
    "Medium":                  "in 3-4 paragraphs",
    "Detailed":                "in a structured, detailed manner with key points",
}


class PdfSummaryPanel(QWidget):
    """Upload a PDF, choose length/focus, click Summarise."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)

        lay.addWidget(heading_label("📄 PDF Summary"))
        lay.addWidget(QLabel("Upload a dental report, research paper, or any PDF."))

        # file picker
        row = QHBoxLayout()
        self.path_lbl = QLineEdit()
        self.path_lbl.setReadOnly(True)
        self.path_lbl.setPlaceholderText("No file selected…")
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        row.addWidget(self.path_lbl)
        row.addWidget(b)
        lay.addLayout(row)

        # options row
        opt = QHBoxLayout()
        self.length_combo = QComboBox()
        self.length_combo.addItems(list(_LENGTH_MAP.keys()))
        self.focus_input = QLineEdit()
        self.focus_input.setPlaceholderText("Focus on (optional)…")
        opt.addWidget(QLabel("Length:"))
        opt.addWidget(self.length_combo)
        opt.addSpacing(16)
        opt.addWidget(QLabel("Focus:"))
        opt.addWidget(self.focus_input)
        lay.addLayout(opt)

        self.sum_btn = QPushButton("Summarise")
        self.sum_btn.clicked.connect(self._summarise)
        lay.addWidget(self.sum_btn)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Summary will appear here…")
        lay.addWidget(self.output)

        self._pdf_text = ""
        self._worker: Optional[OllamaWorker] = None

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf)"
        )
        if not p:
            return
        self.path_lbl.setText(p)
        try:
            with pdfplumber.open(p) as pdf:
                text = "".join(pg.extract_text() or "" for pg in pdf.pages)
            if not text.strip():
                QMessageBox.warning(self, "Warning", "No extractable text.")
                return
            self._pdf_text = text
            self.output.setPlaceholderText(
                f"Extracted {len(text):,} chars. Click Summarise."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _summarise(self) -> None:
        if not self._pdf_text:
            QMessageBox.warning(self, "No PDF", "Select a PDF first.")
            return

        instr = _LENGTH_MAP[self.length_combo.currentText()]
        focus = self.focus_input.text().strip()
        fc    = f" Focus especially on: {focus}." if focus else ""
        prompt = (
            f"Summarise the following document {instr}.{fc}\n\n"
            f"Document:\n{self._pdf_text[:MAX_CONTEXT_CHARS]}"
        )

        self.sum_btn.setEnabled(False)
        self.output.setText("⏳ Summarising…")

        self._worker = OllamaWorker(GENERAL_MODEL, prompt)
        self._worker.result.connect(
            lambda t: (self.output.setText(t), self.sum_btn.setEnabled(True))
        )
        self._worker.error.connect(
            lambda e: (
                self.output.setText(f"⚠️ {e}"),
                self.sum_btn.setEnabled(True),
            )
        )
        self._worker.start()
