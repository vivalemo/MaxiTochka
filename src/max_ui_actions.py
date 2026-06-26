"""Действия в UI web.max.ru через Playwright."""

from __future__ import annotations

import os
import re
import time
from typing import Any

from app_logger import get_logger, log_path
from max_ui_selectors import (
    APP_READY,
    COMPOSER,
    CONTACT_RESULT,
    INCOMING_MESSAGE,
    SEND_BUTTON,
    TEXT_CONTACTS,
    TEXT_CREATE,
    TEXT_CREATE_GROUP,
    TEXT_FIND_IN_MAX,
    TEXT_FIND_BY_PHONE,
    TEXT_NEW_CHAT,
    TEXT_NEXT,
    TEXT_CONFIRM_DELETE,
    TEXT_LEAVE_GROUP,
    TEXT_SAVE_CONTACT_BTN,
    TEXT_START_CHAT,
)

_log = get_logger("max_ui")

_SKIP_CHAT_HEADERS = frozenset(
    {
        "новые",
        "каналы",
        "все",
        "чаты",
        "контакты",
        "избранное",
        "архив",
        "channels",
        "new",
        "all",
        "chats",
        "contacts",
        "настройки",
        "settings",
    }
)

# Вкладки/фильтры MAX («Новые 2», «Каналы 5») — не чаты.
_UI_CHROME_TITLE_RE = re.compile(
    r"^(новые|каналы|все|чаты|контакты|избранное|архив|"
    r"channels|new|all|chats|contacts|favorites|archive)(\s+\d+)?$",
    re.I,
)


def is_ui_chrome_title(title: str) -> bool:
    """True для вкладок MAX и служебных подписей, не для реальных чатов."""
    s = (title or "").strip()
    if not s or len(s) < 3:
        return True
    if s.casefold() in _SKIP_CHAT_HEADERS:
        return True
    if _UI_CHROME_TITLE_RE.match(s):
        return True
    if re.match(r"^(новые|каналы|new|channels)\s+\d+$", s, re.I):
        return True
    return False


class MaxUIActions:
    def __init__(self, page: Any, session_name: str = "") -> None:
        self.page = page
        self.session_name = session_name
        self._step_timeout_ms = 25000
        self._titles_cache_ts: float = 0.0
        self._titles_cache: list[str] = []

    def _shot(self, tag: str) -> None:
        try:
            folder = os.path.join(os.path.dirname(log_path()), "automation_shots")
            os.makedirs(folder, exist_ok=True)
            safe = re.sub(r"[^\w\-.]+", "_", self.session_name)[:40]
            path = os.path.join(folder, f"{safe}_{tag}_{int(time.time())}.png")
            self.page.screenshot(path=path)
            _log.info("screenshot: %s", path)
        except Exception:
            pass

    def _modal(self) -> Any:
        return self.page.locator('[data-testid="modal"]')

    def _page_text(self) -> str:
        try:
            return (self.page.inner_text("body") or "").casefold()
        except Exception:
            return ""

    def _format_phone_input(self, contact: str) -> str:
        digits = re.sub(r"\D", "", contact or "")
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        if len(digits) == 11 and digits.startswith("7"):
            digits = digits[1:]
        if len(digits) == 10:
            return f"{digits[:3]} {digits[3:6]} {digits[6:8]} {digits[8:]}"
        return digits

    def _is_logged_in(self) -> bool:
        try:
            return bool(
                self.page.evaluate(
                    """() => {
                      try {
                        const r = localStorage.getItem('__oneme_auth');
                        return !!(r && r !== 'null' && JSON.parse(r).token);
                      } catch (e) { return false; }
                    }"""
                )
            )
        except Exception:
            return False

    def wait_app_ready(self, timeout_ms: int = 60000) -> bool:
        deadline = time.time() + timeout_ms / 1000
        navigated = False
        while time.time() < deadline:
            try:
                url = (self.page.url or "").lower()
                if "web.max.ru" not in url:
                    if not navigated:
                        self.page.goto(
                            "https://web.max.ru",
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                        navigated = True
                    time.sleep(0.5)
                    continue
                body_len = int(
                    self.page.evaluate(
                        "document.body ? document.body.innerText.length : 0"
                    )
                    or 0
                )
                if body_len > 250:
                    return True
                if self._is_logged_in() and body_len > 80:
                    return True
                for sel in APP_READY:
                    loc = self.page.locator(sel).first
                    if loc.count() and loc.is_visible(timeout=500):
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _click_text(self, *labels: str, exact: bool = False) -> bool:
        scope = self._modal() if self._modal().count() else self.page
        for label in labels:
            if not label:
                continue
            try:
                loc = scope.get_by_text(label, exact=exact).first
                if loc.is_visible(timeout=1500):
                    loc.click(timeout=self._step_timeout_ms)
                    return True
            except Exception:
                pass
            try:
                loc = scope.get_by_role(
                    "button", name=re.compile(re.escape(label), re.I)
                ).first
                if loc.is_visible(timeout=1000):
                    loc.click(timeout=self._step_timeout_ms)
                    return True
            except Exception:
                pass
        return False

    def _click_selector(self, selectors: list[str]) -> bool:
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=1200):
                    loc.click(timeout=self._step_timeout_ms)
                    return True
            except Exception:
                continue
        return False

    def go_to_contacts(self) -> bool:
        """Нижняя вкладка «Контакты» (не раздел «Чаты»)."""
        self._close_overlays()
        try:
            clicked = self.page.evaluate(
                """() => {
                  const vis = el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                  };
                  const tabs = [...document.querySelectorAll('button,[role=button]')]
                    .filter(el => vis(el) && (el.innerText || '').trim() === 'Контакты');
                  if (!tabs.length) return false;
                  tabs.sort(
                    (a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top
                  );
                  tabs[tabs.length - 1].click();
                  return true;
                }"""
            )
            if clicked:
                time.sleep(1.0)
                return True
        except Exception:
            pass
        if self._click_text(*TEXT_CONTACTS, exact=True):
            time.sleep(1.0)
            return True
        try:
            self.page.get_by_role("button", name="Контакты").click(timeout=5000)
            time.sleep(1.0)
            return True
        except Exception:
            return False

    def go_to_chats(self) -> bool:
        self._close_overlays()
        try:
            compose = self.page.locator('[aria-label="Начать общение"]').first
            if compose.is_visible(timeout=1500):
                return True
        except Exception:
            pass
        for back_aria in ("Перейти назад", "Закрыть", "Close"):
            try:
                btn = self.page.locator(f'[aria-label="{back_aria}"]').first
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=3000)
                    time.sleep(0.5)
            except Exception:
                continue
        for sel in ('[aria-label="Чаты"]', '[aria-label="Chats"]'):
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=2000):
                    loc.click(timeout=4000)
                    time.sleep(1.0)
                    return True
            except Exception:
                continue
        try:
            self.page.get_by_role("button", name=re.compile(r"Чаты", re.I)).click(timeout=4000)
            time.sleep(1.0)
            return True
        except Exception:
            pass
        try:
            self.page.goto(
                "https://web.max.ru",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            time.sleep(2.0)
            return True
        except Exception:
            return False

    def open_compose_menu(self) -> bool:
        try:
            btn = self.page.locator('[aria-label="Начать общение"]').first
            if btn.is_visible(timeout=3000):
                btn.click(timeout=self._step_timeout_ms)
                return True
        except Exception:
            pass
        return self._click_text(*TEXT_START_CHAT, *TEXT_NEW_CHAT)

    def open_new_chat_menu(self) -> bool:
        return self.open_compose_menu()

    def _close_overlays(self) -> None:
        for _ in range(2):
            try:
                self.page.keyboard.press("Escape")
                time.sleep(0.25)
            except Exception:
                break

    def _pick_in_modal(self, query: str) -> bool:
        query = (query or "").strip()
        if not query:
            return False
        modal = self._modal()
        scope = modal if modal.count() else self.page
        try:
            loc = scope.locator("button").filter(has_text=query).first
            if loc.is_visible(timeout=2500):
                loc.click(timeout=self._step_timeout_ms)
                return True
        except Exception:
            pass
        try:
            loc = scope.get_by_text(query, exact=False).first
            if loc.is_visible(timeout=2000):
                loc.click(timeout=self._step_timeout_ms)
                return True
        except Exception:
            pass
        digits = re.sub(r"\D", "", query)
        if len(digits) >= 10:
            try:
                loc = scope.get_by_text(digits[-10:], exact=False).first
                if loc.is_visible(timeout=2000):
                    loc.click(timeout=self._step_timeout_ms)
                    return True
            except Exception:
                pass
        return False

    def _contact_visible_in_list(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        if not self.go_to_contacts():
            return False
        try:
            search = self.page.locator('input[placeholder="Найти"]').first
            search.fill("", timeout=3000)
            search.fill(name, timeout=5000)
        except Exception:
            return False
        time.sleep(1.2)
        try:
            return self.page.get_by_text(name, exact=False).first.is_visible(timeout=2500)
        except Exception:
            return name.casefold() in self._page_text()

    def open_add_contact_form(self) -> bool:
        """Контакты → + → «Добавить контакт»."""
        if not self.go_to_contacts():
            self._shot("contacts_tab")
            return False
        try:
            self.page.locator('[aria-label="Начать общение"]').first.click(timeout=5000)
            time.sleep(0.8)
        except Exception:
            self._shot("contacts_compose")
            return False
        try:
            self.page.locator('[aria-label="Добавить контакт"]').first.click(timeout=5000)
            time.sleep(1.0)
            return self.page.locator('input[placeholder="Имя"]').first.is_visible(timeout=5000)
        except Exception:
            self._shot("add_contact_form")
            return False

    def _fill_add_contact_phone(self, phone: str) -> bool:
        phone_fmt = self._format_phone_input(phone)
        try:
            name_inp = self.page.locator('input[placeholder="Имя"]').first
            phone_inp = name_inp.locator("xpath=./preceding::input[1]")
            phone_inp.fill(phone_fmt, timeout=5000)
            return True
        except Exception:
            pass
        try:
            for i in range(self.page.locator('input[type="text"]').count()):
                inp = self.page.locator('input[type="text"]').nth(i)
                ph = (inp.get_attribute("placeholder") or "").strip()
                if ph in ("Найти", "Имя") or "Фамилия" in ph:
                    continue
                inp.fill(phone_fmt, timeout=3000)
                return True
        except Exception:
            pass
        return False

    def _add_contact_via_contacts_tab(
        self, phone: str, save_as: str | None = None
    ) -> tuple[bool, str]:
        save_as = (save_as or "").strip()
        if save_as and self._contact_visible_in_list(save_as):
            return True, f"контакт уже есть: {save_as}"

        if not self.open_add_contact_form():
            return False, "форма «Добавить контакт» не открыта"

        if not self._fill_add_contact_phone(phone):
            self._shot("contact_phone_input")
            return False, "поле телефона не найдено"

        if save_as:
            try:
                self.page.locator('input[placeholder="Имя"]').first.fill(
                    save_as, timeout=5000
                )
            except Exception:
                self._shot("contact_name_input")
                return False, "поле «Имя» не найдено"

        time.sleep(0.5)
        saved = False
        try:
            self.page.locator('[aria-label="Сохранить контакт"]').first.click(
                timeout=self._step_timeout_ms
            )
            saved = True
        except Exception:
            saved = self._click_text(*TEXT_SAVE_CONTACT_BTN, exact=False)

        if not saved:
            self._shot("save_contact")
            return False, "кнопка «Сохранить контакт» не найдена"

        time.sleep(2.0)
        self._close_overlays()

        text = self._page_text()
        if any(
            x in text
            for x in (
                "не найден",
                "не зарегистрирован",
                "не в max",
                "ошибка",
                "некорректн",
            )
        ):
            self._shot("save_contact_result")
            return False, f"контакт не сохранён: {phone}"

        if save_as and self._contact_visible_in_list(save_as):
            return True, f"контакт сохранён как «{save_as}»"
        if save_as:
            return True, f"контакт добавлен как «{save_as}»"
        return True, f"контакт добавлен: {phone}"

    def _add_contact_by_name(self, name: str) -> tuple[bool, str]:
        if not self.go_to_contacts():
            self._shot("contacts_tab")
            return False, "вкладка «Контакты» не найдена"

        time.sleep(0.5)
        try:
            self.page.locator('input[placeholder="Найти"]').first.fill(name, timeout=5000)
        except Exception:
            self._shot("contacts_search")
            return False, "поиск в контактах не найден"

        time.sleep(1.2)
        try:
            loc = self.page.get_by_text(name, exact=False).first
            if loc.is_visible(timeout=2000):
                return True, "контакт найден в списке"
        except Exception:
            pass

        text = self._page_text()
        if "не найден" in text:
            return False, f"контакт не найден: {name}"
        self._shot("contact_by_name")
        return False, f"контакт не найден: {name}"

    def add_contact(self, contact: str, save_as: str | None = None) -> tuple[bool, str]:
        contact = (contact or "").strip()
        if not contact:
            return False, "пустой контакт"
        if not self.wait_app_ready():
            self._shot("not_ready")
            return False, "MAX не загрузился"

        self._close_overlays()
        digits = re.sub(r"\D", "", contact)
        save_as = (save_as or "").strip() or None
        if len(digits) >= 10:
            return self._add_contact_via_contacts_tab(contact, save_as=save_as)
        return self._add_contact_by_name(save_as or contact)

    def create_group(self, title: str, members: list[str]) -> tuple[bool, str]:
        title = (title or "").strip()
        if not title:
            return False, "пустое название группы"
        if not self.wait_app_ready():
            self._shot("group_not_ready")
            return False, "MAX не загрузился"

        self.go_to_chats()
        self._close_overlays()
        if not self.open_compose_menu():
            return False, "меню «Начать общение» не открыто"
        if not self._click_text(*TEXT_CREATE_GROUP, exact=True):
            self._shot("create_group_menu")
            return False, "пункт «Создать группу» не найден"

        time.sleep(0.6)
        modal = self._modal()
        picked_any = False
        for member in members:
            m = (member or "").strip()
            if not m:
                continue
            try:
                search = modal.locator(
                    'input[placeholder*="имени"], input[placeholder*="Найти"]'
                ).first
                search.fill("", timeout=3000)
                search.fill(m, timeout=5000)
            except Exception:
                self._shot("group_member_search")
                return False, "поле поиска участников не найдено"

            picked = False
            for attempt in range(3):
                time.sleep(1.2 if attempt == 0 else 2.5)
                if self._pick_in_modal(m):
                    picked = True
                    break
                if attempt < 2:
                    try:
                        search.fill("", timeout=2000)
                        search.fill(m, timeout=4000)
                    except Exception:
                        pass
            if not picked:
                self._shot("group_member_pick")
                return False, f"участник не найден: {m}"
            picked_any = True
            time.sleep(0.4)

        if members and not picked_any:
            return False, "участники не выбраны"

        if not self._click_text(*TEXT_NEXT, exact=True):
            self._shot("group_next")
            return False, "кнопка «Далее» не найдена"

        time.sleep(0.8)
        modal = self._modal()
        try:
            name_inp = modal.locator(
                'input[placeholder*="Название"], input[placeholder*="назван"]'
            ).first
            name_inp.fill(title, timeout=5000)
        except Exception:
            try:
                modal.locator("input:visible").first.fill(title, timeout=5000)
            except Exception:
                self._shot("group_name")
                return False, "поле названия группы не найдено"

        if not self._click_text(*TEXT_CREATE, exact=True):
            self._shot("group_create_btn")
            return False, "кнопка «Создать» не найдена"

        time.sleep(2.0)
        text = self._page_text()
        if title.casefold() in text:
            return True, f"группа «{title}» создана"
        if "вы создали чат" in text or "чат готов" in text:
            return True, f"группа «{title}» создана"

        self._shot("group_verify")
        return False, f"группа «{title}» не подтверждена"

    def _clear_chat_search(self) -> None:
        try:
            search = self.page.locator('input[placeholder="Найти"]').first
            if search.is_visible(timeout=800):
                search.fill("", timeout=2000)
        except Exception:
            pass

    def open_group_chat(self, title: str) -> bool:
        title = (title or "").strip()
        if not title or is_ui_chrome_title(title):
            return False
        if not self.go_to_chats():
            return False

        try:
            loc = self.page.locator("button").filter(has_text=title).first
            if loc.is_visible(timeout=2000):
                loc.click(timeout=self._step_timeout_ms)
                time.sleep(0.6)
                return True
        except Exception:
            pass
        try:
            loc = self.page.get_by_text(title, exact=False).first
            if loc.is_visible(timeout=2000):
                loc.click(timeout=self._step_timeout_ms)
                time.sleep(0.6)
                return True
        except Exception:
            pass

        search = None
        try:
            search = self.page.locator('input[placeholder="Найти"]').first
            if search.is_visible(timeout=1500):
                search.fill("", timeout=2000)
                search.fill(title, timeout=3000)
                time.sleep(0.8)
                try:
                    loc = self.page.locator("button").filter(has_text=title).first
                    if loc.is_visible(timeout=2500):
                        loc.click(timeout=self._step_timeout_ms)
                        time.sleep(0.6)
                        return True
                except Exception:
                    pass
                try:
                    self.page.get_by_text(title, exact=False).first.click(
                        timeout=4000
                    )
                    time.sleep(0.6)
                    return True
                except Exception:
                    self._shot("open_chat")
                    return False
            return False
        except Exception:
            self._shot("open_chat")
            return False
        finally:
            self._clear_chat_search()

    def read_chat_messages(self) -> list[dict[str, str]]:
        try:
            items = self.page.evaluate(
                """() => {
                  const res = [];
                  const seen = new Set();
                  const nodes = document.querySelectorAll(
                    '[class*="message"], [class*="bubble"], [class*="msg"], [data-testid*="message"]'
                  );
                  for (const n of nodes) {
                    const t = (n.innerText || '').trim();
                    if (!t || t.length > 2000 || seen.has(t)) continue;
                    seen.add(t);
                    const cls = ((n.className || '') + ' ' + (n.parentElement?.className || '')).toLowerCase();
                    const aria = (n.getAttribute('aria-label') || '').toLowerCase();
                    const isOut = /out|self|mine|own|right|sent/.test(cls + aria);
                    res.push({text: t, direction: isOut ? 'out' : 'in'});
                  }
                  return res.slice(-50);
                }"""
            )
            return [
                {"text": str(x.get("text", "")), "direction": str(x.get("direction", "in"))}
                for x in (items or [])
                if str(x.get("text", "")).strip()
            ]
        except Exception:
            return []

    def send_message(self, text: str, *, group_title: str = "") -> tuple[bool, str]:
        text = (text or "").strip()
        if not text:
            return False, "пустое сообщение"
        if not self.wait_app_ready():
            return False, "MAX не загрузился"
        if group_title and not self.open_group_chat(group_title):
            return False, f"чат «{group_title}» не открыт"

        if not self._click_selector(list(COMPOSER)):
            self._shot("composer")
            return False, "поле ввода не найдено"

        try:
            self.page.keyboard.type(text, delay=35)
        except Exception:
            try:
                self.page.locator(COMPOSER[0]).first.fill(text)
            except Exception as ex:
                return False, str(ex)

        if self._click_selector(list(SEND_BUTTON)):
            return True, "отправлено"
        try:
            self.page.keyboard.press("Enter")
            return True, "отправлено (Enter)"
        except Exception as ex:
            self._shot("send")
            return False, str(ex)

    def read_incoming_messages(self) -> list[str]:
        out: list[str] = []
        for sel in INCOMING_MESSAGE:
            try:
                loc = self.page.locator(sel)
                n = min(loc.count(), 30)
                for i in range(n):
                    try:
                        t = (loc.nth(i).inner_text(timeout=2000) or "").strip()
                        if t:
                            out.append(t)
                    except Exception:
                        continue
            except Exception:
                continue
        if out:
            return out[-20:]

        try:
            items = self.page.evaluate(
                """() => {
                  const nodes = document.querySelectorAll(
                    '[class*="message"], [class*="bubble"], [class*="msg"]'
                  );
                  const res = [];
                  for (const n of nodes) {
                    const t = (n.innerText || '').trim();
                    if (t && t.length < 2000) res.push(t);
                  }
                  return res.slice(-25);
                }"""
            )
            return [str(x) for x in (items or []) if str(x).strip()]
        except Exception:
            return []

    @staticmethod
    def _filter_chat_title_lines(lines: list[str], *, limit: int) -> list[str]:
        out: list[str] = []
        time_re = re.compile(r"^\d{1,2}:\d{2}$")
        for ln in lines:
            s = (ln or "").strip()
            if not s or len(s) < 2 or len(s) > 120:
                continue
            low = s.casefold()
            if low in _SKIP_CHAT_HEADERS:
                continue
            if is_ui_chrome_title(s):
                continue
            if time_re.match(s):
                continue
            if s.isdigit():
                continue
            if s not in out:
                out.append(s)
            if len(out) >= limit:
                break
        return out

    def list_chat_titles(self, *, limit: int = 80, max_age_sec: float = 45.0) -> list[str]:
        """Заголовки чатов из списка слева в MAX."""
        now = time.time()
        if (
            self._titles_cache
            and now - self._titles_cache_ts < max_age_sec
        ):
            return self._titles_cache[:limit]
        if not self.go_to_chats():
            return self._titles_cache[:limit] if self._titles_cache else []
        time.sleep(0.5)
        try:
            raw = self.page.evaluate(
                f"""() => {{
                  const res = [];
                  const seen = new Set();
                  const skip = /^(чаты|контакты|настройки|chats|contacts|все|all)$/i;
                  const nodes = document.querySelectorAll(
                    '[class*="chat-list"] button, [class*="dialogs"] button, '
                    + '[class*="ChatList"] button, [class*="ChatItem"], '
                    + '[class*="dialog"] button, [role="listitem"] button, '
                    + '[class*="sidebar"] [role="button"]'
                  );
                  const push = (raw) => {{
                    const t = (raw || '').trim().split('\\n').map(s => s.trim()).filter(Boolean)[0];
                    if (!t || t.length > 120 || seen.has(t) || skip.test(t)) return;
                    seen.add(t);
                    res.push(t);
                  }};
                  for (const n of nodes) push(n.innerText);
                  if (res.length < 3) {{
                    for (const n of document.querySelectorAll('[class*="chat"], [class*="dialog"]')) {{
                      const t = (n.innerText || '').trim().split('\\n')[0];
                      push(t);
                    }}
                  }}
                  return res.slice(0, {int(limit)});
                }}"""
            )
            out = self._filter_chat_title_lines(
                [str(t) for t in (raw or [])], limit=limit
            )
            if len(out) >= 2:
                self._titles_cache = out[:limit]
                self._titles_cache_ts = time.time()
                return self._titles_cache
        except Exception:
            out = []

        for sel in ('[class*="sidebar"]', '[class*="Dialogs"]', "nav", "main"):
            try:
                loc = self.page.locator(sel).first
                if not loc.is_visible(timeout=1500):
                    continue
                text = loc.inner_text(timeout=4000) or ""
                parsed = self._filter_chat_title_lines(
                    text.splitlines(), limit=limit
                )
                if len(parsed) > len(out):
                    out = parsed
            except Exception:
                continue

        if len(out) < 2:
            try:
                raw_buttons = self.page.evaluate(
                    f"""() => {{
                      const skip = /^(все|новые|каналы|контакты|звонки|настройки|чаты|избранное|архив|channels|new|all|chats|contacts|favorites|archive|settings|calls)$/i;
                      const res = [];
                      const seen = new Set();
                      for (const b of document.querySelectorAll('button,[role=button]')) {{
                        const r = b.getBoundingClientRect();
                        if (r.width < 8 || r.height < 8) continue;
                        const t = (b.innerText || '').trim().split('\\n').map(s => s.trim()).filter(Boolean)[0];
                        if (!t || t.length > 120 || seen.has(t) || skip.test(t)) continue;
                        if (/^(новые|каналы|new|channels)\\s+\\d+$/i.test(t)) continue;
                        seen.add(t);
                        res.push(t);
                      }}
                      return res.slice(0, {int(limit)});
                    }}"""
                )
                parsed = self._filter_chat_title_lines(
                    [str(t) for t in (raw_buttons or [])], limit=limit
                )
                if len(parsed) > len(out):
                    out = parsed
            except Exception:
                pass

        self._titles_cache = out[:limit]
        self._titles_cache_ts = time.time()
        return self._titles_cache

    def chat_exists(self, title: str) -> bool:
        """Проверить, что групповой чат есть в списке MAX."""
        title = (title or "").strip()
        if not title or is_ui_chrome_title(title):
            return False
        if not self.go_to_chats():
            return False
        needle = title.casefold()
        for item in self.list_chat_titles():
            if item.casefold() == needle or needle in item.casefold():
                return True
        return False

    def delete_group(self, title: str) -> tuple[bool, str]:
        """Покинуть / удалить группу в MAX."""
        title = (title or "").strip()
        if not title:
            return False, "пустое название"
        if not self.wait_app_ready():
            return False, "MAX не загрузился"
        if not self.open_group_chat(title):
            return False, f"чат «{title}» не найден"

        self._close_overlays()
        for sel in (
            '[class*="header"]',
            '[class*="chat-info"]',
            '[class*="ChatHeader"]',
            "header",
        ):
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=1500):
                    loc.click(timeout=self._step_timeout_ms)
                    time.sleep(0.5)
                    break
            except Exception:
                continue

        if not self._click_text(*TEXT_LEAVE_GROUP, exact=False):
            for label in ("Настройки", "Ещё", "⋯", "..."):
                if self._click_text(label, exact=False):
                    time.sleep(0.4)
                    if self._click_text(*TEXT_LEAVE_GROUP, exact=False):
                        break
            else:
                self._shot("delete_group_menu")
                return False, "пункт удаления группы не найден"

        time.sleep(0.5)
        if self._click_text(*TEXT_CONFIRM_DELETE, exact=False):
            time.sleep(0.8)
            return True, "группа удалена в MAX"

        self._shot("delete_group_confirm")
        return False, "подтверждение удаления не найдено"
