"""Colours and the Qt style sheet."""

ACCENT = "#0f766e"
ACCENT_DARK = "#115e59"
ACCENT_LIGHT = "#ccfbf1"
INK = "#1f2937"
MUTED = "#6b7280"
BORDER = "#e5e7eb"
BG = "#f6f7f9"
GOOD = "#15803d"
BAD = "#b91c1c"

QSS = f"""
* {{ font-family: 'Segoe UI', 'Inter', Arial, sans-serif; font-size: 10pt; color: {INK}; }}
QMainWindow, QWidget#central {{ background: {BG}; }}

QFrame#header {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_DARK}, stop:1 #0e7490);
    border: none;
}}
QFrame#header QLabel {{ color: white; background: transparent; }}
QLabel#appTitle {{ font-size: 20pt; font-weight: 700; }}
QLabel#appTagline {{ font-size: 10pt; color: #d1fae5; }}
QLabel#creditName {{ font-size: 13pt; font-weight: 700; }}
QLabel#creditTitle {{ font-size: 9pt; color: #d1fae5; }}

QFrame#sidebar {{ background: white; border-right: 1px solid {BORDER}; }}
QFrame#card {{ background: white; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#dropZone {{
    background: #f0fdfa; border: 2px dashed #5eead4; border-radius: 12px;
}}
QLabel#muted {{ color: {MUTED}; }}
QLabel#sectionTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#docName {{ font-size: 11pt; font-weight: 600; }}

QPushButton {{
    background: white; border: 1px solid #d1d5db; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ background: #f3f4f6; }}
QPushButton:disabled {{ color: #9ca3af; background: #f9fafb; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: #99c9c4; border-color: #99c9c4; color: white; }}
QPushButton#danger {{ color: {BAD}; }}
QPushButton#segment {{ border-radius: 0; padding: 7px 18px; }}
QPushButton#segment:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; font-weight: 600; }}
QPushButton#chip {{ border-radius: 14px; padding: 5px 12px; background: #f0fdfa; border-color: #99f6e4; color: {ACCENT_DARK}; }}
QPushButton#chip:hover {{ background: {ACCENT_LIGHT}; }}
QPushButton#option {{ text-align: left; padding: 11px 14px; font-size: 10.5pt; }}

QTabWidget::pane {{ border: none; background: {BG}; }}
QTabBar::tab {{
    background: transparent; padding: 10px 18px; margin-right: 2px; color: {MUTED};
    border-bottom: 3px solid transparent; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 3px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {INK}; }}

QTextBrowser, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {{
    background: white; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
    selection-background-color: {ACCENT_LIGHT}; selection-color: {INK};
}}
QPlainTextEdit:focus, QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QProgressBar {{ background: #e5e7eb; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QStatusBar {{ background: white; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ color: {MUTED}; }}
"""

CHAT_CSS = f"""
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; color: {INK}; }}
.who {{ font-size: 8.5pt; font-weight: 600; color: {MUTED}; margin-top: 10px; }}
.user {{ background: {ACCENT_LIGHT}; border-radius: 10px; padding: 8px 12px; }}
.bot {{ background: #ffffff; padding: 2px 0px; }}
.src {{ color: #9ca3af; font-size: 9pt; }}
h2, h3, h4 {{ color: #134e4a; }}
"""
