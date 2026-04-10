"""
dental_ai/app.py
=================
Application entry point — creates the QApplication singleton,
shows the login dialog, and launches the main window.

Usage::

    python -m dental_ai          # via __main__.py
    python dental_ai/app.py      # direct run
"""

import sys
from pathlib import Path
from typing import Optional


if __package__ in (None, ""):
    package_parent = Path(__file__).resolve().parent.parent
    package_parent_str = str(package_parent)
    if package_parent_str not in sys.path:
        sys.path.insert(0, package_parent_str)

if __name__ == "__main__":
    package_name = Path(__file__).resolve().parent.name
    sys.modules.setdefault(f"{package_name}.app", sys.modules[__name__])

from PyQt6.QtWidgets import QApplication, QDialog

from dental_ai.core.constants import APP_STYLESHEET

# Module-level singletons (one QApplication per process)
_app:      Optional[QApplication] = None
_main_win                         = None   # MainWindow — typed lazily


def start_login() -> None:
    """Show the Login/Register dialog; on success launch the MainWindow."""
    # Deferred imports prevent circular-import issues
    from dental_ai.ui.dialogs.login_dialog import LoginDialog
    from dental_ai.ui.main_window         import MainWindow

    dlg = LoginDialog()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        global _main_win
        _main_win = MainWindow(dlg.username, fernet_key=dlg.fernet_key)
        _main_win.setStyleSheet(APP_STYLESHEET)
        _main_win.show()


def main() -> None:
    """Create the QApplication and enter the event loop."""
    global _app
    _app = QApplication(sys.argv)
    _app.setStyle("Fusion")
    _app.setStyleSheet(APP_STYLESHEET)
    start_login()
    sys.exit(_app.exec())


if __name__ == "__main__":
    main()
