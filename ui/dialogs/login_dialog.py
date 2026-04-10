"""
dental_ai/ui/dialogs/login_dialog.py
=======================================
Combined Login / Register dialog.

• If the username already exists  → Login mode: verifies password.
• If the username is new          → Register mode: creates account.

On success, exposes:
    self.username     — display name (original casing)
    self.fernet_key   — derived encryption key bytes (or None)
"""

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
)

from dental_ai.auth import ENCRYPTION_AVAILABLE, get_auth_store
from dental_ai.core.constants import MUTED, TEAL, TEAL_DARK, TEAL_LIGHT, TEXT


class LoginDialog(QDialog):
    """Auto-detects whether to log in or register based on username."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dental AI Assistant — Sign In")
        self.setFixedSize(460, 420)
        self.setModal(True)

        self.username:   str             = ""
        self.fernet_key: Optional[bytes] = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 28, 40, 28)
        lay.setSpacing(12)

        # brand
        ico = QLabel("🦷")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet("font-size:28px;")
        lay.addWidget(ico)

        title = QLabel("Dental AI Assistant")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size:22px;font-weight:700;color:{TEXT};")
        lay.addWidget(title)

        sub = QLabel("Private · Local · Powered by Ollama")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color:{MUTED};font-size:12px;")
        lay.addWidget(sub)

        # encryption badge
        if ENCRYPTION_AVAILABLE:
            enc_badge = QLabel("🔒 End-to-end encrypted history")
            enc_badge.setStyleSheet(
                f"background:{TEAL_LIGHT};color:{TEAL_DARK};"
                "border-radius:10px;padding:3px 10px;font-size:11px;font-weight:600;"
            )
        else:
            enc_badge = QLabel(
                "⚠️ cryptography not installed — history stored unencrypted\n"
                "Run: pip install cryptography"
            )
            enc_badge.setStyleSheet(
                "background:#fff7ed;color:#92400e;"
                "border-radius:10px;padding:4px 10px;font-size:11px;"
            )
            enc_badge.setWordWrap(True)
        enc_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(enc_badge)

        # username
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Username (e.g. Dr. Müller)")
        self.name_input.setMinimumHeight(38)
        self.name_input.textChanged.connect(self._on_username_changed)
        lay.addWidget(self.name_input)

        # password
        pw_row = QHBoxLayout()
        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("Password")
        self.pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_input.setMinimumHeight(38)
        self.pw_input.returnPressed.connect(self._submit)
        pw_row.addWidget(self.pw_input)
        show_cb = QCheckBox("Show")
        show_cb.stateChanged.connect(
            lambda s: self.pw_input.setEchoMode(
                QLineEdit.EchoMode.Normal if s == 2
                else QLineEdit.EchoMode.Password
            )
        )
        pw_row.addWidget(show_cb)
        lay.addLayout(pw_row)

        # confirm password (register only)
        self.pw2_input = QLineEdit()
        self.pw2_input.setPlaceholderText("Confirm password (new accounts)")
        self.pw2_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2_input.setMinimumHeight(38)
        self.pw2_input.returnPressed.connect(self._submit)
        lay.addWidget(self.pw2_input)

        # mode label
        self.mode_lbl = QLabel("")
        self.mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;")
        lay.addWidget(self.mode_lbl)

        # submit
        self.submit_btn = QPushButton("Sign In →")
        self.submit_btn.setMinimumHeight(40)
        self.submit_btn.clicked.connect(self._submit)
        lay.addWidget(self.submit_btn)

        note = QLabel("All data stays on your machine.")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet("color:#94a3b8;font-size:11px;")
        lay.addWidget(note)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _on_username_changed(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            self.mode_lbl.setText("")
            self.pw2_input.setVisible(True)
            self.submit_btn.setText("Sign In →")
            return
        if get_auth_store().user_exists(stripped):
            self.mode_lbl.setText("✅ Existing account — enter your password to log in")
            self.pw2_input.setVisible(False)
            self.submit_btn.setText("Log In →")
        else:
            self.mode_lbl.setText("🆕 New account — choose a password to register")
            self.pw2_input.setVisible(True)
            self.submit_btn.setText("Register & Sign In →")

    def _submit(self) -> None:
        username = self.name_input.text().strip()
        password = self.pw_input.text()

        if not username:
            QMessageBox.warning(self, "Required", "Please enter a username.")
            return
        if len(password) < 8:
            QMessageBox.warning(self, "Weak password",
                "Password must be at least 8 characters.")
            return

        auth = get_auth_store()

        if auth.user_exists(username):
            # Login
            if not auth.verify(username, password):
                QMessageBox.critical(self, "Wrong password",
                    "Incorrect password. Please try again.")
                self.pw_input.clear()
                self.pw_input.setFocus()
                return
        else:
            # Register
            if password != self.pw2_input.text():
                QMessageBox.warning(self, "Mismatch", "Passwords do not match.")
                return
            if not auth.register(username, password):
                QMessageBox.warning(self, "Taken",
                    "That username was just registered. Try logging in.")
                return
            QMessageBox.information(self, "Account created",
                f"Welcome, {auth.get_display_name(username)}!\n"
                "Your history will be encrypted with your password.\n"
                "If you forget your password your history cannot be recovered.")

        self.username    = auth.get_display_name(username)
        self.fernet_key  = auth.fernet_key(username, password) if ENCRYPTION_AVAILABLE else None
        self.accept()
