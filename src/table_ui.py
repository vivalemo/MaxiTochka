"""Общие стили и настройки таблиц (белый текст, ресайз колонок)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView

from theme import ACCENT

TABLE_TEXT = "#ffffff"
TABLE_TEXT_MUTED = "#94a3b8"
TABLE_MIN_COL_WIDTH = 32


def table_stylesheet(object_name: str) -> str:
    return f"""
    QTableWidget#{object_name} {{
        background-color: #14161d;
        alternate-background-color: #1b1e27;
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 10px;
        color: {TABLE_TEXT};
        gridline-color: rgba(255,255,255,0.08);
        font-size: 12px;
        selection-background-color: rgba(99,102,241,0.30);
    }}
    QTableWidget#{object_name}::item {{
        padding: 6px 8px;
        border: none;
        color: {TABLE_TEXT};
    }}
    QTableWidget#{object_name}::item:selected {{
        color: {TABLE_TEXT};
    }}
    QHeaderView::section {{
        background-color: #232733;
        color: {TABLE_TEXT};
        border: none;
        border-right: 1px solid rgba(255,255,255,0.06);
        padding: 8px 6px;
        font-size: 11px;
        font-weight: 700;
    }}
    """


def checker_table_extra_stylesheet() -> str:
    return f"""
    QTableWidget#CheckerTable::indicator {{
        width: 17px;
        height: 17px;
        border-radius: 4px;
        border: 1px solid rgba(255,255,255,0.35);
        background: rgba(255,255,255,0.04);
    }}
    QTableWidget#CheckerTable::indicator:checked {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
    }}
    """


def setup_resizable_columns(
    header: QHeaderView,
    widths: tuple[int, ...],
    *,
    stretch_col: int | None = None,
) -> None:
    """Все колонки тянутся мышью; stretch_col — опционально растягивается."""
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(TABLE_MIN_COL_WIDTH)
    header.setSectionsClickable(True)
    header.setHighlightSections(True)
    header.setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    for col in range(header.count() or len(widths)):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
    if stretch_col is not None and 0 <= stretch_col < len(widths):
        header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    for col, w in enumerate(widths):
        if w > 0:
            header.resizeSection(col, w)
