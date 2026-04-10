"""
dental_ai/core/context_manager.py
===================================
Rolling-context compression for any conversation message list.
Keeps recent turns verbatim and summarises older history via Ollama.
"""

from datetime import datetime
from typing import Optional

import ollama

from .constants import (
    CHARS_PER_TOKEN,
    CTX_COMPRESS_TOKENS,
    CTX_KEEP_RECENT_TURNS,
    CTX_WARN_TOKENS,
    GENERAL_MODEL,
)


def _estimate_tokens(messages: list[dict]) -> int:
    """Fast token estimate: total character count ÷ CHARS_PER_TOKEN."""
    total = sum(len(m.get("content", "")) for m in messages)
    return total // CHARS_PER_TOKEN


class ContextManager:
    """
    Manages rolling context for a single conversation.

    Usage::

        ctx = ContextManager()
        messages, compressed = ctx.maybe_compress(messages)
        if compressed:
            # inject a notice bubble into the UI

    Compression strategy
    --------------------
    1. Keep the last ``CTX_KEEP_RECENT_TURNS`` turn-pairs verbatim.
    2. Summarise everything older into a single system-style bullet list.
    3. Falls back to simple truncation if summarisation fails.
    """

    def __init__(self, model: str = GENERAL_MODEL) -> None:
        self.model = model

    # ── public API ────────────────────────────────────────────────────────────

    def token_count(self, messages: list[dict]) -> int:
        return _estimate_tokens(messages)

    def needs_compression(self, messages: list[dict]) -> bool:
        return self.token_count(messages) >= CTX_COMPRESS_TOKENS

    def needs_warning(self, messages: list[dict]) -> bool:
        tc = self.token_count(messages)
        return CTX_WARN_TOKENS <= tc < CTX_COMPRESS_TOKENS

    def maybe_compress(
        self, messages: list[dict]
    ) -> tuple[list[dict], bool]:
        """
        Return *(new_messages, was_compressed)*.
        If compression was not needed, returns *(messages, False)* unchanged.
        """
        if not self.needs_compression(messages):
            return messages, False

        keep_count = CTX_KEEP_RECENT_TURNS * 2  # user + assistant per turn
        if len(messages) <= keep_count:
            return messages, False

        old_msgs  = messages[:-keep_count]
        keep_msgs = messages[-keep_count:]

        transcript = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: "
            f"{m['content'][:400]}"
            for m in old_msgs
        )

        summary_prompt = (
            "Summarise the following conversation excerpt into 3-5 concise "
            "bullet points that capture the key topics, questions asked, and "
            "answers given. Focus on facts relevant to continuing the "
            "conversation.\n\n" + transcript
        )

        try:
            resp = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            summary_text = resp["message"]["content"]
        except Exception:
            # Summarisation failed — truncate rather than crash
            return list(keep_msgs), True

        summary_msg = {
            "role": "system",
            "content": (
                "📋 [Context summary — earlier conversation compressed]\n"
                + summary_text
            ),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }

        return [summary_msg] + list(keep_msgs), True
