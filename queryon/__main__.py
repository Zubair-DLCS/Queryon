"""Start Queryon:  python -m queryon"""

import sys


def main() -> int:
    from .cpu import select_llama_build

    select_llama_build()  # must happen before llama_cpp is imported anywhere

    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        from .selftest import run

        return run(sys.argv[2] if len(sys.argv) > 2 else "selftest.txt")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, AUTHOR_NAME
    from .ui.main_window import MainWindow
    from .ui.style import QSS

    if sys.platform == "win32":  # own taskbar icon instead of python's
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{AUTHOR_NAME}.{APP_NAME}")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(AUTHOR_NAME)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:  # "Open with Queryon" / file dropped on the exe
        win.open_document(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
