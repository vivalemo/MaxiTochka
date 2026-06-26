"""Интерактивный туториал: подсветка, стрелка, пользователь выполняет действия сам."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QEvent, QPoint, QTimer, Qt, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from theme import ACCENT, BG_CARD, SUCCESS, TEXT, TEXT_DIM, WARNING

_PAD = 8
_BORDER = 3
_CARD_MAX_W = 500
_FOOTER_RESERVE = 52


@dataclass(frozen=True)
class TutorialStep:
    title: str
    body: str
    tab: int | None = None
    target: str | None = None
    target_hint: str = ""
    wait_for: str | None = None
    setup: str | None = None


STEPS: tuple[TutorialStep, ...] = (
    TutorialStep(
        "Добро пожаловать",
        "Пройдём основные действия: проверка прокси, запуск сессии и проверка токена. "
        "На каждом шаге нужно сделать действие в подсвеченной области — "
        "кнопка «Далее» появится после выполнения.",
    ),
    TutorialStep(
        "Вкладки программы",
        "«Прокси» — список и проверка прокси.\n"
        "«Запуск» — токены и браузер.\n"
        "«Чекер» — живой токен или нет.",
        target="nav_bar",
        target_hint="Панель вкладок сверху",
    ),
    TutorialStep(
        "Список прокси",
        "Вставьте прокси — по одному на строку.\n"
        "Формат: host:port или login:pass@host:port.\n\n"
        "Если поле пустое — мы подставим пример. Замените его на свой прокси.",
        tab=0,
        target="p_input",
        target_hint="Поле ввода прокси",
        setup="proxy_sample",
    ),
    TutorialStep(
        "Проверьте прокси сами",
        "Нажмите «Проверить» в подсветке.\n\n"
        "После проверки справа в списке:\n"
        "• зелёный / OK — прокси живой\n"
        "• красный / мёртвый — не работает\n\n"
        "Дождитесь результата — шаг засчитается автоматически.",
        tab=0,
        target="btn_proxy_check",
        target_hint="Кнопка «Проверить»",
        wait_for="proxy_checked",
    ),
    TutorialStep(
        "Результат проверки прокси",
        "Справа видно статус каждой строки.\n"
        "«Пинг всех» — дополнительно замерит задержку (мс) и IP.\n\n"
        "Для запуска сессий нужны рабочие прокси.",
        tab=0,
        target="proxy_results",
        target_hint="Список результатов",
    ),
    TutorialStep(
        "Вкладка «Токены»",
        "Здесь все файлы сессий (.txt): импорт, проверка и запуск.\n"
        "«Импорт» — добавить с компьютера. Можно перетащить .txt на вкладку.",
        tab=1,
        target="launch_import_btns",
        target_hint="Кнопки импорта",
    ),
    TutorialStep(
        "Запустите сессию",
        "Нажмите ▶ в колонке ▶⏹ — откроется Chrome с токеном.\n\n"
        "Если список пуст — сначала импортируйте .txt, затем вернитесь в Tutorial.",
        tab=1,
        target="launch_run_cell",
        target_hint="▶ — запуск",
        wait_for="session_launched",
        setup="launch_ready",
    ),
    TutorialStep(
        "Остановите сессию",
        "Нажмите ⏹ в той же колонке ▶⏹ — сессия закроется.\n"
        "Так останавливают работу с аккаунтом.",
        tab=1,
        target="launch_stop_cell",
        target_hint="⏹ — стоп",
        wait_for="session_stopped",
    ),
    TutorialStep(
        "Иконки в таблице запуска",
        "▶⏹ запуск и стоп · 📄 RAW · 👁 окно браузера · 🗑 удалить.\n"
        "Комментарий редактируется прямо в ячейке.",
        tab=1,
        target="launch_table",
        target_hint="Таблица сессий",
    ),
    TutorialStep(
        "Проверка токена",
        "Отметьте галочкой токен и нажмите «Проверить».\n"
        "Мы уже отметим первую строку — вам останется нажать «Проверить».",
        tab=1,
        target="checker_table",
        target_hint="Таблица токенов",
        setup="checker_select_first",
    ),
    TutorialStep(
        "Проверьте токен сами",
        "Нажмите «Проверить» в подсветке.\n\n"
        "В колонке «Статус» появится:\n"
        "• Живой — токен работает\n"
        "• Мёртвый — сессия слетела\n"
        "• Ошибка — не удалось проверить",
        tab=1,
        target="btn_checker_run",
        target_hint="Кнопка «Проверить»",
        wait_for="checker_done",
    ),
    TutorialStep(
        "Готово!",
        "Вы прошли основной тур.\n"
        "Кнопка Tutorial внизу — можно повторить.\n"
        "Не отправляйте файлы сессий посторонним.",
    ),
)


def _find_button(window: Any, *needles: str, page: QWidget | None = None) -> QWidget | None:
    from PyQt6.QtWidgets import QPushButton

    roots = [page] if page is not None else [window]
    needles_l = [n.lower() for n in needles]
    for root in roots:
        if root is None:
            continue
        for btn in root.findChildren(QPushButton):
            text = (btn.text() or "").strip().lower()
            if any(n in text for n in needles_l):
                return btn
    return None


def _resolve_target(window: Any, key: str | None) -> QWidget | None:
    if not key:
        return None
    p_page = getattr(window, "p_page", None)
    l_page = getattr(window, "l_page", None)
    c_page = getattr(window, "c_page", None)

    if key == "nav_bar":
        btn = getattr(window, "btn_p", None)
        return btn.parentWidget() if btn else None
    if key == "p_input":
        return getattr(window, "p_input", None)
    if key == "btn_proxy_check":
        return _find_button(window, "проверить", page=p_page)
    if key == "proxy_results":
        return getattr(window, "p_scroll", None)
    if key == "launch_import_btns":
        btn = _find_button(window, "импорт", page=l_page)
        return btn.parentWidget() if btn and btn.parentWidget() else btn
    if key == "launch_table":
        return getattr(window, "_launch_table", None) or getattr(window, "l_scroll", None)
    if key == "launch_run_cell":
        table = getattr(window, "_launch_table", None)
        return table if table is not None and table.rowCount() > 0 else None
    if key == "launch_stop_cell":
        table = getattr(window, "_launch_table", None)
        return table if table is not None and table.rowCount() > 0 else None
    if key == "checker_table":
        return getattr(window, "_launch_table", None) or getattr(
            window, "_checker_table", None
        ) or getattr(window, "l_scroll", None)
    if key == "btn_checker_run":
        return _find_button(window, "проверить", page=l_page)
    return None


def _widget_rect_in(host: QWidget, widget: QWidget | None, *, col: int | None = None) -> QRect:
    if widget is None:
        return QRect()
    try:
        if col is not None and hasattr(widget, "visualRect"):
            rect = widget.visualRect(widget.model().index(0, col))
            tl = widget.viewport().mapToGlobal(rect.topLeft())
            br = widget.viewport().mapToGlobal(rect.bottomRight())
            local_tl = host.mapFromGlobal(tl)
            local_br = host.mapFromGlobal(br)
            return QRect(local_tl, local_br).normalized().adjusted(-_PAD, -_PAD, _PAD, _PAD)
        if not widget.isVisible():
            return QRect()
        tl = host.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        br = host.mapFromGlobal(
            widget.mapToGlobal(QPoint(widget.width(), widget.height()))
        )
        return QRect(tl, br).normalized().adjusted(-_PAD, -_PAD, _PAD, _PAD)
    except RuntimeError:
        return QRect()


def _target_col(step: TutorialStep) -> int | None:
    if step.target in ("launch_run_cell", "launch_stop_cell"):
        return 6
    return None


class _TutorialCard(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("TutorialCard")
        self.setStyleSheet(
            f"""
            QFrame#TutorialCard {{
                background: {BG_CARD};
                border: 1px solid rgba(99, 102, 241, 0.65);
                border-radius: 14px;
            }}
            QLabel#TutorialTitle {{ color: {TEXT}; font-size: 15px; font-weight: 800; border: none; }}
            QLabel#TutorialHint {{
                color: {ACCENT}; font-size: 11px; font-weight: 700; border: none;
                background: rgba(99,102,241,0.12); border-radius: 6px; padding: 4px 8px;
            }}
            QLabel#TutorialBody {{ color: {TEXT_DIM}; font-size: 12px; font-weight: 500; border: none; }}
            QLabel#TutorialStep {{ color: rgba(255,255,255,0.4); font-size: 10px; border: none; }}
            QLabel#TutorialWait {{
                color: {WARNING}; font-size: 11px; font-weight: 700; border: none;
            }}
            QLabel#TutorialDone {{
                color: {SUCCESS}; font-size: 11px; font-weight: 700; border: none;
            }}
            QPushButton#TutorialGhost {{
                color: {TEXT_DIM}; background: transparent;
                border: 1px solid rgba(255,255,255,0.12); border-radius: 8px;
                padding: 6px 14px; font-size: 11px; font-weight: 600;
            }}
            QPushButton#TutorialGhost:hover {{ background: rgba(255,255,255,0.06); }}
            QPushButton#TutorialNext {{
                color: white; background: {ACCENT}; border: none; border-radius: 8px;
                padding: 6px 18px; font-size: 11px; font-weight: 700;
            }}
            QPushButton#TutorialNext:hover {{ background: #818cf8; }}
            QPushButton#TutorialNext:disabled {{
                background: rgba(99,102,241,0.25); color: rgba(255,255,255,0.35);
            }}
            """
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        top = QHBoxLayout()
        self._step_lbl = QLabel()
        self._step_lbl.setObjectName("TutorialStep")
        top.addWidget(self._step_lbl)
        top.addStretch(1)
        outer.addLayout(top)

        self._hint = QLabel()
        self._hint.setObjectName("TutorialHint")
        self._hint.setWordWrap(True)
        outer.addWidget(self._hint)

        self._title = QLabel()
        self._title.setObjectName("TutorialTitle")
        self._title.setWordWrap(True)
        outer.addWidget(self._title)

        self._body = QLabel()
        self._body.setObjectName("TutorialBody")
        self._body.setWordWrap(True)
        outer.addWidget(self._body)

        self._wait = QLabel()
        self._wait.setObjectName("TutorialWait")
        self._wait.hide()
        outer.addWidget(self._wait)

        self._done = QLabel()
        self._done.setObjectName("TutorialDone")
        self._done.hide()
        outer.addWidget(self._done)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._back = QPushButton("Назад")
        self._back.setObjectName("TutorialGhost")
        self._skip = QPushButton("Пропустить")
        self._skip.setObjectName("TutorialGhost")
        self._next = QPushButton("Далее")
        self._next.setObjectName("TutorialNext")
        btns.addWidget(self._back)
        btns.addStretch(1)
        btns.addWidget(self._skip)
        btns.addWidget(self._next)
        outer.addLayout(btns)

    def set_content(
        self,
        *,
        step_num: int,
        total: int,
        title: str,
        body: str,
        target_hint: str,
        show_back: bool,
        is_last: bool,
        waiting: bool,
        action_done: bool,
        can_next: bool,
    ) -> None:
        self._step_lbl.setText(f"Шаг {step_num} из {total}")
        self._title.setText(title)
        self._body.setText(body)
        if target_hint:
            self._hint.setText(f"▲ {target_hint}")
            self._hint.show()
        else:
            self._hint.hide()
        self._back.setVisible(show_back)
        self._next.setText("Готово" if is_last else "Далее")
        self._next.setEnabled(can_next)
        if waiting and not action_done:
            self._wait.setText("⏳ Выполните действие в подсвеченной области…")
            self._wait.show()
            self._done.hide()
        elif action_done:
            self._wait.hide()
            self._done.setText("✓ Готово! Нажмите «Далее»")
            self._done.show()
        else:
            self._wait.hide()
            self._done.hide()


class TutorialOverlay(QWidget):
    def __init__(self, window: Any) -> None:
        host = window.centralWidget() or window
        super().__init__(host)
        self._window = window
        self._host = host
        self._index = 0
        self._target_rect = QRect()
        self._arrow_to = QPoint()
        self._interactive = False
        self._action_done = False
        self._snapshot: dict = {}
        self._card = _TutorialCard(self)
        self._card._back.clicked.connect(self._prev)
        self._card._skip.clicked.connect(self.close_tutorial)
        self._card._next.clicked.connect(self._next)

        self._poll = QTimer(self)
        self._poll.setInterval(400)
        self._poll.timeout.connect(self._poll_action)

        self.hide()
        window.installEventFilter(self)
        if host is not window:
            host.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj in (self._window, self._host) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            QTimer.singleShot(0, self._sync_geometry)
        return False

    def _current(self) -> TutorialStep:
        return STEPS[self._index]

    def _sync_geometry(self) -> None:
        if not self.isVisible():
            return
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._refresh_target()
        self._place_card()
        self._update_mask()
        self.update()

    def start(self) -> None:
        self._index = 0
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self._card.raise_()
        self._show_current()

    def close_tutorial(self) -> None:
        self._poll.stop()
        self.clearMask()
        self.hide()

    def _snapshot_state(self) -> None:
        w = self._window
        self._snapshot = {
            "proxy_cache": dict(getattr(w, "proxy_cache", {}) or {}),
            "token_results": dict(getattr(w, "token_results", {}) or {}),
            "active": set(getattr(w, "active_drivers", {}) or {}),
        }

    def _run_setup(self, setup: str | None) -> None:
        if not setup:
            return
        w = self._window
        if setup == "proxy_sample":
            inp = getattr(w, "p_input", None)
            if inp is not None and not inp.toPlainText().strip():
                inp.setPlainText(
                    "127.0.0.1:8080\n"
                    "# замените на свой прокси — host:port или user:pass@host:port"
                )
        elif setup == "launch_ready":
            try:
                if hasattr(w, "render_sessions"):
                    w.render_sessions()
            except Exception:
                pass
        elif setup == "checker_select_first":
            try:
                if hasattr(w, "render_checker"):
                    w.render_checker()
            except Exception:
                pass
            table = getattr(w, "_launch_table", None) or getattr(w, "_checker_table", None)
            if table is not None and table.rowCount() > 0:
                item = table.item(0, 0)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Checked)
                    picked = set(getattr(w, "_checker_checked", None) or ())
                    fname = item.data(Qt.ItemDataRole.UserRole)
                    if fname:
                        picked.add(fname)
                        w._checker_checked = picked

    def _poll_action(self) -> None:
        if not self._interactive or self._action_done:
            return
        if self._check_wait_done(self._current().wait_for):
            self._action_done = True
            self._interactive = False
            self._update_mask()
            self._refresh_ui()

    def _check_wait_done(self, kind: str | None) -> bool:
        if not kind:
            return True
        w = self._window
        snap = self._snapshot
        if kind == "proxy_checked":
            cache = getattr(w, "proxy_cache", {}) or {}
            before = snap.get("proxy_cache", {})
            if cache and len(cache) >= len(before):
                for line, info in cache.items():
                    st = str((info or {}).get("st", "")).upper()
                    prev = str((before.get(line) or {}).get("st", "")).upper()
                    if st and st not in ("WAIT", "") and st != prev:
                        return True
            if getattr(w, "_tutorial_proxy_touched", False):
                cache = getattr(w, "proxy_cache", {}) or {}
                if cache:
                    return any(
                        str((i or {}).get("st", "")).upper() not in ("", "WAIT")
                        for i in cache.values()
                    )
                lay = getattr(w, "p_list_lay", None)
                if lay is not None and lay.count() > 0:
                    return True
            return False
        if kind == "session_launched":
            active = set(getattr(w, "active_drivers", {}) or {})
            return len(active) > len(snap.get("active", set()))
        if kind == "session_stopped":
            active = set(getattr(w, "active_drivers", {}) or {})
            return bool(snap.get("active")) and len(active) < len(snap.get("active", set()))
        if kind == "checker_done":
            tr = getattr(w, "token_results", {}) or {}
            before = snap.get("token_results", {})
            for fname, st in tr.items():
                if st in ("OK", "dead", "error") and before.get(fname) != st:
                    return True
            return False
        return False

    def _prev(self) -> None:
        if self._index > 0:
            self._poll.stop()
            self._index -= 1
            self._show_current()

    def _next(self) -> None:
        step = self._current()
        if step.wait_for and not self._action_done:
            return
        if self._index >= len(STEPS) - 1:
            self.close_tutorial()
            return
        self._poll.stop()
        self._index += 1
        self._show_current()

    def _show_current(self) -> None:
        step = self._current()
        if step.tab is not None and hasattr(self._window, "switch_tab"):
            self._window.switch_tab(step.tab)
        QTimer.singleShot(180, self._apply_step)

    def _apply_step(self) -> None:
        if not self.isVisible():
            return
        step = self._current()
        self._run_setup(step.setup)
        self._action_done = False
        self._interactive = bool(step.wait_for)
        self._window._tutorial_proxy_touched = False
        self._snapshot_state()
        self._refresh_target()
        self._refresh_ui()
        self._place_card()
        self._update_mask()
        self.update()
        self.raise_()
        self._card.raise_()
        if self._interactive:
            self._poll.start()
        else:
            self._poll.stop()

    def _refresh_target(self) -> None:
        step = self._current()
        widget = _resolve_target(self._window, step.target)
        col = _target_col(step)
        if col is not None and widget is not None:
            self._target_rect = _widget_rect_in(self, widget, col=col)
        else:
            self._target_rect = _widget_rect_in(self, widget)

    def _refresh_ui(self) -> None:
        step = self._current()
        waiting = bool(step.wait_for)
        can_next = not waiting or self._action_done
        if step.target in ("launch_run_cell", "launch_stop_cell"):
            table = getattr(self._window, "_launch_table", None)
            if table is None or table.rowCount() == 0:
                can_next = True
                waiting = False
        self._card.set_content(
            step_num=self._index + 1,
            total=len(STEPS),
            title=step.title,
            body=step.body,
            target_hint=step.target_hint,
            show_back=self._index > 0,
            is_last=self._index >= len(STEPS) - 1,
            waiting=waiting,
            action_done=self._action_done,
            can_next=can_next,
        )

    def _card_rect(self) -> QRect:
        return QRect(self._card.pos(), self._card.size())

    def _place_card(self) -> None:
        margin = 16
        w, h = self.width(), self.height()
        card_w = min(_CARD_MAX_W, w - 2 * margin)
        self._card.setFixedWidth(card_w)
        self._card.adjustSize()
        ch = self._card.height()
        cw = self._card.width()

        candidates: list[int] = []
        bottom_y = h - ch - margin - _FOOTER_RESERVE
        top_y = margin + 8
        candidates.append(max(margin, bottom_y))
        candidates.append(top_y)

        if self._target_rect.isValid() and not self._target_rect.isEmpty():
            tc = self._target_rect.center()
            if tc.y() < h // 2:
                candidates.insert(0, bottom_y)
            else:
                candidates.insert(0, top_y)
            side_y = max(margin, min(tc.y() - ch // 2, h - ch - margin))
            candidates.append(side_y)

        chosen_y = candidates[0]
        chosen_x = (w - cw) // 2
        card_rect = QRect()

        for y in candidates:
            x = (w - cw) // 2
            rect = QRect(x, y, cw, ch)
            if not self._target_rect.isValid() or not rect.intersects(self._target_rect):
                chosen_x, chosen_y = x, y
                card_rect = rect
                break
        else:
            if self._target_rect.isValid():
                if self._target_rect.center().x() < w // 2:
                    chosen_x = min(w - cw - margin, self._target_rect.right() + 20)
                else:
                    chosen_x = max(margin, self._target_rect.left() - cw - 20)
                chosen_y = max(margin, min(self._target_rect.center().y() - ch // 2, h - ch - margin))
            card_rect = QRect(chosen_x, chosen_y, cw, ch)

        self._card.move(chosen_x, chosen_y)

        if self._target_rect.isValid() and not self._target_rect.isEmpty():
            self._arrow_to = self._target_rect.center()
        else:
            self._arrow_to = QPoint()

    def _update_mask(self) -> None:
        if self._interactive and self._target_rect.isValid() and not self._action_done:
            full = QRegion(self.rect())
            hole = QRegion(self._target_rect)
            card_r = self._card_rect()
            mask = full.subtracted(hole).subtracted(card_r)
            self.setMask(mask)
        else:
            card_r = self._card_rect()
            if card_r.isValid():
                self.setMask(QRegion(self.rect()).subtracted(card_r))
            else:
                self.clearMask()

    def mousePressEvent(self, event) -> None:
        pos = event.pos()
        if self._card_rect().contains(pos):
            super().mousePressEvent(event)
            return
        if (
            self._interactive
            and not self._action_done
            and self._target_rect.isValid()
            and self._target_rect.contains(pos)
        ):
            self._forward_click(event.globalPosition().toPoint())
            return
        event.accept()

    def _forward_click(self, global_pos: QPoint) -> None:
        target = QApplication.widgetAt(global_pos)
        if target is None:
            return
        from PyQt6.QtGui import QMouseEvent

        local = target.mapFromGlobal(global_pos)
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            local,
            global_pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(target, ev)
        rel = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            local,
            global_pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(target, rel)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        if not p.isActive():
            return
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            if w <= 0 or h <= 0:
                return

            path = QPainterPath()
            path.addRect(0, 0, w, h)

            card_r = QRectF(self._card_rect())
            if card_r.isValid():
                cp = QPainterPath()
                cp.addRoundedRect(card_r.adjusted(-4, -4, 4, 4), 12, 12)
                path = path.subtracted(cp)

            if self._target_rect.isValid() and not self._target_rect.isEmpty():
                rf = QRectF(self._target_rect)
                hole = QPainterPath()
                hole.addRoundedRect(rf, 10.0, 10.0)
                path = path.subtracted(hole)
                p.fillPath(path, QColor(0, 0, 0, 165))
                pen = QPen(QColor(99, 102, 241, 240), _BORDER + 1)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rf, 10.0, 10.0)
                if not self._arrow_to.isNull():
                    self._draw_arrow(p, card_r, rf)
            else:
                p.fillPath(path, QColor(0, 0, 0, 140))

            if card_r.isValid():
                p.setPen(QPen(QColor(99, 102, 241, 120), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(card_r.adjusted(-4, -4, 4, 4), 12, 12)
        finally:
            p.end()

    def _draw_arrow(self, p: QPainter, card_r: QRectF, target_r: QRectF) -> None:
        if not card_r.isValid() or not target_r.isValid():
            return
        tc = target_r.center()
        cc = card_r.center()
        start = QPoint(int(cc.x()), int(card_r.top() if tc.y() < cc.y() else card_r.bottom()))
        if abs(tc.y() - cc.y()) < abs(tc.x() - cc.x()):
            start = QPoint(
                int(card_r.right() if tc.x() > cc.x() else card_r.left()),
                int(cc.y()),
            )
        end = QPoint(int(tc.x()), int(tc.y()))
        pen = QPen(QColor(129, 140, 248, 200), 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(start, end)
        p.setBrush(QColor(129, 140, 248, 220))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(end, 5, 5)


def install_tutorial(window: Any) -> TutorialOverlay:
    overlay = TutorialOverlay(window)
    window._tutorial_overlay = overlay
    _hook_proxy_check(window)
    return overlay


def _hook_proxy_check(window: Any) -> None:
    if getattr(window, "_tutorial_proxy_hooked", False):
        return
    orig = getattr(window, "start_check", None)
    if callable(orig):

        def start_check_wrapped(*args, **kwargs):
            window._tutorial_proxy_touched = True
            return orig(*args, **kwargs)

        window.start_check = start_check_wrapped

    from PyQt6.QtWidgets import QPushButton

    ping = window.findChild(QPushButton, "ProxyPingAllBtn")
    if ping is not None:
        ping.clicked.connect(lambda: setattr(window, "_tutorial_proxy_touched", True))
    window._tutorial_proxy_hooked = True


def start_tutorial(window: Any) -> None:
    overlay = getattr(window, "_tutorial_overlay", None)
    if overlay is None:
        overlay = install_tutorial(window)
    overlay.start()


def add_tutorial_footer_button(window: Any, footer_layout: Any) -> None:
    btn = QPushButton("Tutorial")
    btn.setObjectName("MxTutorialBtn")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip("Пошаговый тур для новичков")
    btn.setStyleSheet(
        "QPushButton#MxTutorialBtn { "
        "color: rgba(241,245,249,0.85); background: rgba(99,102,241,0.22); "
        "border: 1px solid rgba(99,102,241,0.45); border-radius: 6px; "
        "padding: 3px 12px; font-size: 10px; font-weight: 700; }"
        "QPushButton#MxTutorialBtn:hover { background: rgba(99,102,241,0.38); }"
    )
    btn.clicked.connect(lambda: start_tutorial(window))
    footer_layout.insertWidget(1, btn)
