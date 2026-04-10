"""
dental_ai/core/pdf_export.py
==============================
Render any list of ``{role, content}`` messages as a styled ReportLab PDF.
Image-analysis turns that carry an ``image_path`` field have the actual
image embedded inline for a complete audit trail.
"""

import io
from datetime import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
)

_TEAL = colors.HexColor("#0d9488")


def export_session_to_pdf(
    title: str,
    messages: list[dict],
    subtitle: str = "",
) -> bytes:
    """
    Return the raw bytes of a styled PDF containing *messages*.

    Parameters
    ----------
    title:     Session title shown in the PDF header.
    messages:  List of ``{"role": ..., "content": ..., "image_path": ...}`` dicts.
    subtitle:  Optional sub-heading (e.g. tool kind).
    """
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm,  bottomMargin=20 * mm,
    )
    stls         = getSampleStyleSheet()
    usable_width = A4[0] - 40 * mm

    # ── Header ────────────────────────────────────────────────────────────────
    story = [
        Paragraph(
            "🦷 Dental AI Assistant",
            ParagraphStyle("T", parent=stls["Title"],
                           textColor=_TEAL, fontSize=18, spaceAfter=4),
        ),
        Paragraph(
            f"Session: <b>{title}</b>"
            + (f"  <i>({subtitle})</i>" if subtitle else ""),
            ParagraphStyle("M", parent=stls["Normal"],
                           textColor=colors.HexColor("#64748b"),
                           fontSize=9, spaceAfter=4),
        ),
        Paragraph(
            f"Exported: {datetime.now().strftime('%d %b %Y, %H:%M')}",
            ParagraphStyle("M2", parent=stls["Normal"],
                           textColor=colors.HexColor("#64748b"),
                           fontSize=9, spaceAfter=12),
        ),
        HRFlowable(width="100%", color=_TEAL, thickness=1, spaceAfter=12),
    ]

    # ── Paragraph styles ──────────────────────────────────────────────────────
    lbl_s = ParagraphStyle(
        "L", parent=stls["Normal"],
        fontSize=8, textColor=colors.HexColor("#94a3b8"), spaceAfter=2,
    )
    usr_s = ParagraphStyle(
        "U", parent=stls["Normal"],
        backColor=colors.HexColor("#ccfbf1"),
        borderPadding=(6, 8, 6, 8),
        fontSize=10, leading=14, spaceAfter=8,
    )
    ast_s = ParagraphStyle(
        "A", parent=stls["Normal"],
        backColor=colors.HexColor("#f1f5f9"),
        borderPadding=(6, 8, 6, 8),
        fontSize=10, leading=14, spaceAfter=8,
    )
    img_cap_s = ParagraphStyle(
        "IC", parent=stls["Normal"],
        fontSize=8, textColor=colors.HexColor("#64748b"),
        spaceAfter=4, alignment=1,  # centred
    )

    # ── Message bubbles ───────────────────────────────────────────────────────
    for msg in messages:
        safe_content = (
            msg["content"]
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        role = msg.get("role", "user")

        if role == "user":
            story.append(Paragraph("You", lbl_s))

            # Embed image if present (image-analysis audit trail)
            img_path = msg.get("image_path", "")
            if img_path and Path(img_path).exists():
                try:
                    rl_img = RLImage(img_path)
                    ratio  = rl_img.imageWidth / max(rl_img.imageHeight, 1)
                    max_w, max_h = float(usable_width) * 0.6, 120.0
                    if ratio >= 1:
                        w = min(max_w, float(rl_img.imageWidth))
                        h = w / ratio
                    else:
                        h = min(max_h, float(rl_img.imageHeight))
                        w = h * ratio
                    rl_img.drawWidth  = w
                    rl_img.drawHeight = h
                    story.append(rl_img)
                    story.append(
                        Paragraph(
                            f"<i>Image: {Path(img_path).name}</i>",
                            img_cap_s,
                        )
                    )
                except Exception:
                    story.append(
                        Paragraph(
                            f"[Image could not be embedded: {Path(img_path).name}]",
                            img_cap_s,
                        )
                    )

            story.append(Paragraph(safe_content, usr_s))
        else:
            story.append(Paragraph("Dental AI", lbl_s))
            story.append(Paragraph(safe_content, ast_s))

    doc.build(story)
    return buf.getvalue()
