"""Фильтр чатов CRM по ключевому слову (по умолчанию «ЖКХ»).

В CRM подтягиваются только чаты/группы, в названии которых есть одно из
ключевых слов. Слова настраиваются в settings.json (`crm_chat_keyword`),
можно перечислить несколько через запятую (например «ЖКХ, УК, Двор»).
Пустое значение отключает фильтр — тянутся все чаты.
"""

from __future__ import annotations

DEFAULT_CRM_KEYWORD = "ЖКХ, ключ"


def get_crm_keyword() -> str:
    """Сырое значение ключевого слова (как в настройках) — для отображения."""
    try:
        from settings_store import load_settings

        raw = str(load_settings().get("crm_chat_keyword", DEFAULT_CRM_KEYWORD) or "")
    except Exception:
        raw = DEFAULT_CRM_KEYWORD
    return raw.strip()


def _keywords(keyword: str | None) -> list[str]:
    """Список ключевых слов (разбивка по запятой), приведённый к нижнему регистру."""
    raw = keyword if keyword is not None else get_crm_keyword()
    parts = [p.strip().casefold() for p in str(raw or "").replace(";", ",").split(",")]
    return [p for p in parts if p]


def title_matches_keyword(title: str, keyword: str | None = None) -> bool:
    """True, если в названии есть хотя бы одно ключевое слово (без учёта регистра)."""
    words = _keywords(keyword)
    if not words:
        return True
    low = (title or "").casefold()
    return any(w in low for w in words)


def dialog_matches_keyword(dialog, keyword: str | None = None) -> bool:
    """Проверка диалога по названию группы или алиасу."""
    words = _keywords(keyword)
    if not words:
        return True
    for value in (
        getattr(dialog, "group_title", "") or "",
        getattr(dialog, "lead_alias", "") or "",
    ):
        low = value.casefold()
        if any(w in low for w in words):
            return True
    return False
