"""
dental_ai/core/constants.py
============================
Application-wide constants, model names, RAG tuning knobs, and the
full Qt stylesheet.  Nothing in this file has side-effects on import.
"""

# ── Model identifiers ──────────────────────────────────────────────────────────
CHAT_MODEL       = "personaldentalassistantadvanced_xml"
GENERAL_MODEL    = "llama3:8b"
IMAGE_MODEL      = "gemma4:e4b"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

# ── RAG / chunking ─────────────────────────────────────────────────────────────
CHUNK_SIZE        = 400   # characters per RAG chunk
CHUNK_OVERLAP     = 80    # overlap between consecutive chunks
RAG_TOP_K         = 3
MAX_CONTEXT_CHARS = 5_000

# ── Context-window management ─────────────────────────────────────────────────
CHARS_PER_TOKEN       = 4      # conservative estimate for clinical text
CTX_WARN_TOKENS       = 2_800  # warn user
CTX_COMPRESS_TOKENS   = 3_200  # trigger summarisation
CTX_KEEP_RECENT_TURNS = 6      # verbatim turns kept after compression

# ── Tool index → (display label, model) ───────────────────────────────────────
TOOL_STATUS = {
    0: ("💬 Chat",                CHAT_MODEL),
    1: ("📄 PDF Summary",         GENERAL_MODEL),
    2: ("🌐 Website Summary",     GENERAL_MODEL),
    3: ("📊 Excel Analysis",      GENERAL_MODEL),
    4: ("🧠 Ask Your Document",   GENERAL_MODEL),
    5: ("🦷 Dental Image Analysis", IMAGE_MODEL),
}

# ── Image-analysis system prompt ──────────────────────────────────────────────
IMAGE_SYSTEM_PROMPT = """\
You are a dental imaging assistant powered by AI. Your role is to help describe
and explain features visible in dental images such as X-rays, photographs, or scans.

IMPORTANT DISCLAIMERS — you must follow these at all times:
• You are NOT a licensed dentist or medical professional.
• Your observations are for EDUCATIONAL and INFORMATIONAL purposes ONLY.
• Nothing you say constitutes a medical diagnosis, clinical opinion, or treatment recommendation.
• Always advise the user to consult a qualified dental professional for any clinical decisions.
• Do NOT make definitive statements about disease presence, severity, or prognosis.
• If the image quality is poor or the findings are ambiguous, say so clearly.

When describing an image:
1. Describe what you can objectively observe (e.g., visible structures, regions of interest, tonal differences).
2. Note any areas that may warrant professional attention, using cautious language
   ("appears to show…", "may suggest…", "could indicate…").
3. End every response with a reminder to consult a dentist or dental specialist.
"""

# ── Supported image extensions ────────────────────────────────────────────────
SUPPORTED_IMAGE_EXTS = (
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"
)

# ── Image-panel disclaimer HTML ────────────────────────────────────────────────
IMAGE_DISCLAIMER_HTML = (
    "<b>⚠️ Educational use only.</b>  This tool provides AI-generated "
    "observations for informational purposes.  It does <u>not</u> constitute "
    "a medical diagnosis or professional dental opinion.  Always consult a "
    "qualified dentist for clinical decisions."
)

# ── Colour palette ─────────────────────────────────────────────────────────────
TEAL        = "#0d9488"
TEAL_LIGHT  = "#ccfbf1"
TEAL_DARK   = "#0f766e"
BG          = "#f8fafc"
SURFACE     = "#ffffff"
BORDER      = "#e2e8f0"
TEXT        = "#0f172a"
MUTED       = "#64748b"
DANGER      = "#ef4444"
WARNING_CLR = "#f59e0b"
SUCCESS     = "#10b981"
HIGHLIGHT   = "#fef08a"

# ── Application-wide Qt stylesheet ────────────────────────────────────────────
APP_STYLESHEET = f"""
QWidget {{
    font-family: 'Segoe UI', 'DM Sans', Arial, sans-serif;
    font-size: 13px; color: {TEXT}; background-color: {BG};
}}
QMainWindow, QDialog {{ background-color: {BG}; }}
#sidebar {{
    background-color: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QPushButton {{
    background-color: {TEAL}; color: white; border: none;
    border-radius: 8px; padding: 7px 16px;
    font-weight: 600; font-size: 13px;
}}
QPushButton:hover   {{ background-color: {TEAL_DARK}; }}
QPushButton:disabled {{ background-color: #94a3b8; }}
QPushButton#secondary {{
    background-color: {SURFACE}; color: {TEAL};
    border: 1px solid {TEAL};
}}
QPushButton#secondary:hover {{ background-color: {TEAL_LIGHT}; }}
QPushButton#danger {{
    background-color: {DANGER};
}}
QPushButton#scopeBtn {{
    background-color: {SURFACE}; color: {MUTED};
    border: 1px solid {BORDER};
    border-radius: 8px; padding: 4px 12px; font-weight: 500;
}}
QPushButton#scopeBtn:hover {{
    background-color: {TEAL_LIGHT}; color: {TEAL_DARK};
    border-color: {TEAL};
}}
QPushButton#scopeBtn:checked {{
    background-color: {TEAL}; color: white;
    border: 1px solid {TEAL_DARK};
}}
QWidget#ctrlStrip QPushButton {{
    background-color: {TEAL}; color: white; border: none;
    border-radius: 8px; padding: 7px 16px;
    font-weight: 600; font-size: 13px;
}}
QWidget#ctrlStrip QPushButton:hover   {{ background-color: {TEAL_DARK}; }}
QWidget#ctrlStrip QPushButton:disabled {{ background-color: #94a3b8; }}
QLineEdit, QTextEdit, QComboBox, QDateEdit {{
    background-color: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px 10px;
    selection-background-color: {TEAL_LIGHT};
}}
QLineEdit:focus, QTextEdit:focus {{ border: 1.5px solid {TEAL}; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    border: none; padding-right: 8px;
}}
QListWidget {{
    background-color: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; outline: none;
}}
QListWidget::item {{ padding: 7px 10px; border-radius: 6px; }}
QListWidget::item:selected {{
    background-color: {TEAL_LIGHT}; color: {TEAL_DARK};
}}
QListWidget::item:hover {{ background-color: #f1f5f9; }}
QScrollBar:vertical {{
    background: {BG}; width: 8px; border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: #cbd5e1; border-radius: 4px; min-height: 20px;
}}
QProgressBar {{
    background-color: {BORDER}; border-radius: 5px;
    height: 10px; text-align: center;
}}
QProgressBar::chunk {{ background-color: {TEAL}; border-radius: 5px; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px;
    padding: 10px; margin-top: 8px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; color: {MUTED};
}}
QSplitter::handle {{ background: {BORDER}; width: 4px; height: 4px; }}
QStatusBar {{
    background: {SURFACE}; border-top: 1px solid {BORDER};
    color: {MUTED}; font-size: 12px;
}}
QToolBar {{
    background: {SURFACE}; border-bottom: 1px solid {BORDER};
    spacing: 4px; padding: 2px 8px;
}}
QToolBar QToolButton {{
    background: transparent; border: none;
    border-radius: 6px; padding: 4px 12px;
    color: {TEXT}; font-size: 12px;
}}
QToolBar QToolButton:hover {{
    background: {TEAL_LIGHT}; color: {TEAL_DARK};
}}
"""
