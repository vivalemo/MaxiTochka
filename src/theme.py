"""Modern UI theme for Maxitochka (dev mode)."""

# Palette (мягкая тёмная тема — не почти чёрный)
BG_DEEP = "#1a1f2e"
BG_CARD = "#252b3d"
BG_INPUT = "rgba(255, 255, 255, 0.08)"
BORDER = "rgba(255, 255, 255, 0.12)"
BORDER_FOCUS = "rgba(99, 102, 241, 0.55)"

ACCENT = "#6366f1"
ACCENT_HOVER = "#818cf8"
SUCCESS = "#22c55e"
SUCCESS_BRIGHT = "#86efac"
WARNING = "#f59e0b"
DANGER = "#f43f5e"
STATUS_OK = "#86efac"
STATUS_DEAD = "#fb7185"
STATUS_ERROR = "#f87171"
STATUS_CHECKING = "#fcd34d"
MUTED = "rgba(255, 255, 255, 0.45)"
TEXT = "#f1f5f9"
TEXT_DIM = "rgba(241, 245, 249, 0.65)"

# Legacy aliases used in bytecode render methods (same length hex where patched)
OK_COLOR = SUCCESS
ERR_COLOR = DANGER
WAIT_COLOR = ACCENT
ACTIVE_COLOR = SUCCESS

STYLESHEET = f"""
QMainWindow {{
    background: {BG_DEEP};
}}
QFrame#MainContainer {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 20px;
}}
QFrame#MainContainer QLabel {{
    color: {TEXT};
    background: transparent;
}}
QFrame#MainContainer QPushButton {{
    color: {TEXT};
}}
QWidget {{
    background: transparent;
    border: none;
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
}}
QLabel {{
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-weight: 600;
    font-size: 14px;
}}
QLabel#Header {{
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: {TEXT};
}}
QTextEdit {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 12px;
    color: {TEXT};
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 13px;
    font-weight: 400;
    padding: 12px;
    selection-background-color: {ACCENT};
}}
QTextEdit:focus {{
    border: 1px solid {BORDER_FOCUS};
}}
QLineEdit {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    padding: 10px 14px;
    font-weight: 500;
}}
QLineEdit:focus {{
    border: 1px solid {BORDER_FOCUS};
}}
QPushButton#NavBtn {{
    background: transparent;
    color: {MUTED};
    font-size: 13px;
    font-weight: 600;
    border: none;
    border-radius: 10px;
    padding: 10px 18px;
    margin: 0 2px;
}}
QPushButton#NavBtn:hover {{
    color: {TEXT};
    background: rgba(255, 255, 255, 0.05);
}}
QPushButton#NavBtn:checked {{
    color: {TEXT};
    background: rgba(99, 102, 241, 0.22);
    border: 1px solid rgba(99, 102, 241, 0.35);
}}
QPushButton#GhostBtn {{
    background: rgba(255, 255, 255, 0.06);
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-weight: 600;
    font-size: 12px;
    min-height: 40px;
    padding: 0 16px;
}}
QPushButton#GhostBtn:hover {{
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.15);
}}
QPushButton#CyanBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(99, 102, 241, 0.35), stop:1 rgba(129, 140, 248, 0.25));
    color: {TEXT};
    border: 1px solid rgba(99, 102, 241, 0.5);
    border-radius: 10px;
    font-weight: 600;
    font-size: 12px;
    min-height: 40px;
    padding: 0 16px;
}}
QPushButton#CyanBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(99, 102, 241, 0.5), stop:1 rgba(129, 140, 248, 0.4));
    border-color: {ACCENT_HOVER};
}}
QFrame#ProxyItem, QFrame#SessionItem {{
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    margin: 2px 0;
    padding: 4px 0;
}}
QFrame#ProxyItem:hover, QFrame#SessionItem:hover {{
    background: rgba(255, 255, 255, 0.09);
}}
QFrame#Toast {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 8px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.15);
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 0.28);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QCheckBox {{
    color: {TEXT_DIM};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {BORDER};
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
"""

HEADER_SUBTITLE_STYLE = (
    f"color: {MUTED}; font-size: 11px; font-weight: 500; border: none; letter-spacing: 0.3px;"
)
WINDOW_BTN_MIN_STYLE = (
    f"color: {MUTED}; background: transparent; border: none; "
    "font-size: 18px; border-radius: 8px; padding: 4px 10px;"
)
WINDOW_BTN_MIN_HOVER = "background: rgba(255,255,255,0.08);"
WINDOW_BTN_CLOSE_STYLE = (
    f"color: {TEXT}; background: transparent; border: none; "
    "font-size: 18px; border-radius: 8px; padding: 4px 10px;"
)
WINDOW_BTN_CLOSE_HOVER = f"background: {DANGER}; color: white;"

CHECKER_LOG_STYLE = f"""
QTextEdit {{
    font-size: 11px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-weight: 400;
    color: {TEXT_DIM};
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 8px;
}}
"""

SECTION_LABEL_STYLE = (
    f"color: {MUTED}; font-size: 10px; font-weight: 700; "
    "letter-spacing: 1.2px; border: none; text-transform: uppercase;"
)

DANGER_BTN_EXTRA = f"color: {DANGER}; border-color: rgba(244, 63, 94, 0.45);"
DANGER_BTN_EXTRA_HOVER = f"background: rgba(244, 63, 94, 0.12);"

INFO_BTN_STYLE = (
    f"background: rgba(99, 102, 241, 0.25); color: {TEXT}; "
    "border: 1px solid rgba(99, 102, 241, 0.45); border-radius: 20px; "
    "font-size: 18px; font-weight: 700; font-family: 'Segoe UI';"
)
INFO_BTN_STYLE_HOVER = "background: rgba(99, 102, 241, 0.45);"
