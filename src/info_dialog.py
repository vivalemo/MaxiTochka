"""Окно «Как пользоваться» для менеджеров."""

from __future__ import annotations

from manager_guide import APP_NAME, HELP_PLAIN


def show_help(parent, module) -> None:
    dlg = module.QDialog(parent)
    dlg.setWindowTitle(f"{APP_NAME} — как пользоваться")
    dlg.setModal(True)
    dlg.setMinimumSize(480, 420)
    dlg.setStyleSheet(
        """
        QDialog {
            background: #252b3d;
        }
        QLabel#HelpTitle {
            color: #f1f5f9;
            font-size: 18px;
            font-weight: 700;
        }
        QTextEdit {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            color: #e2e8f0;
            font-size: 14px;
            line-height: 1.5;
            padding: 14px;
        }
        QPushButton {
            background: #6366f1;
            color: white;
            border: none;
            border-radius: 10px;
            min-height: 40px;
            font-weight: 600;
            padding: 0 24px;
        }
        QPushButton:hover {
            background: #818cf8;
        }
        """
    )

    try:
        import sys

        mod = sys.modules.get("dotlauncher_main")
        if mod and hasattr(mod, "apply_void_acrylic"):
            mod.apply_void_acrylic(dlg.winId())
    except Exception:
        pass

    lay = module.QVBoxLayout(dlg)
    lay.setContentsMargins(24, 24, 24, 24)
    lay.setSpacing(16)

    title = module.QLabel("Краткая инструкция")
    title.setObjectName("HelpTitle")
    lay.addWidget(title)

    body = module.QTextEdit()
    body.setReadOnly(True)
    body.setPlainText(HELP_PLAIN)
    lay.addWidget(body, 1)

    close_btn = module.QPushButton("Понятно")
    close_btn.clicked.connect(dlg.accept)
    lay.addWidget(close_btn, alignment=module.Qt.AlignmentFlag.AlignRight)

    dlg.exec()
