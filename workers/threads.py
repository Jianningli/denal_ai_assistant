"""
dental_ai/workers/threads.py
==============================
All QThread worker classes — each encapsulates one async operation so the
Qt event loop is never blocked.

Workers
-------
ChatWorker          — streaming chat via Ollama
OllamaWorker        — single-shot Ollama chat (no streaming)
FetchWebWorker      — HTTP fetch + BeautifulSoup text extraction
RagIndexWorker      — PDF chunking + FAISS index construction
ImageAnalysisWorker — multimodal image analysis via Ollama
"""

import base64
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
import ollama
import pdfplumber
import requests
from bs4 import BeautifulSoup
from PyQt6.QtCore import QThread, pyqtSignal
from sentence_transformers import SentenceTransformer

from dental_ai.core.constants import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    GENERAL_MODEL,
    IMAGE_MODEL,
    IMAGE_SYSTEM_PROMPT,
    MAX_CONTEXT_CHARS,
)

# ── Singleton sentence-transformer model ──────────────────────────────────────
from dental_ai.core.constants import EMBED_MODEL_NAME

_embed_model: Optional[SentenceTransformer] = None


def get_embed_model() -> SentenceTransformer:
    """Return the shared :class:`SentenceTransformer` instance (lazy init)."""
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


# ── Workers ───────────────────────────────────────────────────────────────────

class ChatWorker(QThread):
    """Streams tokens from an Ollama chat call."""

    token_received = pyqtSignal(str)
    finished       = pyqtSignal(str)
    error          = pyqtSignal(str)

    def __init__(self, model: str, messages: list[dict]) -> None:
        super().__init__()
        self.model    = model
        self.messages = messages

    def run(self) -> None:
        full = ""
        try:
            stream = ollama.chat(
                model=self.model, messages=self.messages, stream=True
            )
            for chunk in stream:
                token = chunk["message"]["content"]
                full += token
                self.token_received.emit(token)
        except ollama.ResponseError as exc:
            self.error.emit(f"Model error: {exc.error}")
            return
        except Exception as exc:
            self.error.emit(str(exc))
            return
        self.finished.emit(full)


class OllamaWorker(QThread):
    """Single-shot (non-streaming) Ollama chat call."""

    result = pyqtSignal(str)
    error  = pyqtSignal(str)

    def __init__(self, model: str, prompt: str) -> None:
        super().__init__()
        self.model  = model
        self.prompt = prompt

    def run(self) -> None:
        try:
            resp = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": self.prompt}],
            )
            self.result.emit(resp["message"]["content"])
        except Exception as exc:
            self.error.emit(str(exc))


class FetchWebWorker(QThread):
    """Fetch a URL, extract paragraph text with BeautifulSoup."""

    result = pyqtSignal(str)
    error  = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; DentalAI/1.0)"}
            r = requests.get(self.url, headers=headers, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            main = soup.find("article") or soup.find("main") or soup
            text = " ".join(
                p.get_text(" ", strip=True) for p in main.find_all("p")
            )
            self.result.emit(text[:MAX_CONTEXT_CHARS])
        except requests.exceptions.Timeout:
            self.error.emit("Request timed out.")
        except requests.exceptions.HTTPError as exc:
            self.error.emit(f"HTTP error: {exc}")
        except Exception as exc:
            self.error.emit(str(exc))


class RagIndexWorker(QThread):
    """
    Chunk PDFs with a sliding window, embed chunks, build a FAISS index.

    Emits ``done(dict)`` with keys:
        chunks, metadata, index, embeddings, chunk_size, chunk_overlap
    """

    done  = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, file_paths: list[str]) -> None:
        super().__init__()
        self.file_paths = file_paths

    def run(self) -> None:
        try:
            model  = get_embed_model()
            chunks: list[str] = []
            meta:   list[dict] = []

            for path in self.file_paths:
                fname  = Path(path).name
                stride = max(CHUNK_SIZE - CHUNK_OVERLAP, 50)
                with pdfplumber.open(path) as pdf:
                    for pn, page in enumerate(pdf.pages):
                        text = page.extract_text()
                        if not text:
                            continue
                        pos = 0
                        while pos < len(text):
                            chunk = text[pos: pos + CHUNK_SIZE].strip()
                            if chunk:
                                chunks.append(chunk)
                                meta.append(
                                    {"source": fname, "page": pn + 1,
                                     "char_offset": pos}
                                )
                            pos += stride

            if not chunks:
                self.error.emit("No readable text found.")
                return

            embeddings = model.encode(chunks, show_progress_bar=False)
            index = faiss.IndexFlatL2(embeddings.shape[1])
            index.add(np.array(embeddings, dtype="float32"))

            self.done.emit({
                "chunks":        chunks,
                "metadata":      meta,
                "index":         index,
                "embeddings":    embeddings,
                "chunk_size":    CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
            })
        except Exception as exc:
            self.error.emit(str(exc))


class ImageAnalysisWorker(QThread):
    """
    Send the full image-session message history to the multimodal model.

    Each user turn that has an ``image_path`` field gets the image embedded
    as base64, preserving visual context across follow-up questions.
    """

    result = pyqtSignal(str)
    error  = pyqtSignal(str)

    def __init__(self, messages: list[dict]) -> None:
        super().__init__()
        self.messages = messages

    def run(self) -> None:
        try:
            ollama_msgs = [{"role": "system", "content": IMAGE_SYSTEM_PROMPT}]

            for m in self.messages:
                msg: dict = {"role": m["role"], "content": m["content"]}
                img_path  = m.get("image_path", "")
                if m["role"] == "user" and img_path and Path(img_path).exists():
                    img_data      = Path(img_path).read_bytes()
                    msg["images"] = [base64.b64encode(img_data).decode("utf-8")]
                ollama_msgs.append(msg)

            resp = ollama.chat(model=IMAGE_MODEL, messages=ollama_msgs)
            self.result.emit(resp["message"]["content"])
        except FileNotFoundError as exc:
            self.error.emit(f"Image file not found: {exc.filename}")
        except ollama.ResponseError as exc:
            self.error.emit(f"Model error: {exc.error}")
        except Exception as exc:
            self.error.emit(str(exc))
