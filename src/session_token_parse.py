"""Извлечение токена из содержимого .txt (JS localStorage или plain)."""

from __future__ import annotations

import json
import re

# Как в main.pyc (оригинальный чекер)
_RE_STRINGIFY = re.compile(
    r"__oneme_auth[^,]*,\s*JSON\.stringify\((\{.*?\})\)",
    re.DOTALL,
)
_RE_TOKEN_QUOTED = re.compile(
    r'"token"\s*:\s*"([A-Za-z0-9\-._~+/=]{30,})"',
)
_RE_SETITEM_JSON = re.compile(
    r"""__oneme_auth['"]\s*,\s*['"](\{.*?\})['"]""",
    re.DOTALL,
)
_RE_SETITEM_ESCAPED = re.compile(
    r"""__oneme_auth['"]\s*,\s*['"](\{.*?\})['"]\s*\)""",
    re.DOTALL,
)


def _is_session_preamble_line(line: str) -> bool:
    """Строки в начале .txt, которые не являются JS (PASSWORD / 2FA / метка чекера)."""
    s = line.strip()
    if not s:
        return False
    low = s.casefold()
    if low == "живой":
        return True
    if low.startswith("живой_"):
        return True
    if low.startswith("password:"):
        return True
    if low.startswith("2fa password:"):
        return True
    if low.startswith("2fa пароль:"):
        return True
    return False


def strip_session_preamble(raw: str) -> str:
    """Убрать PASSWORD / 2FA ПАРОЛЬ — они не JS и ломают execute_script."""
    if not raw:
        return raw
    lines: list[str] = []
    for line in raw.splitlines():
        if _is_session_preamble_line(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


_RE_LOCATION_RELOAD = re.compile(
    r"window\.location\.reload\s*\(\s*\)\s*;?",
    re.IGNORECASE,
)


def strip_session_reload(raw: str) -> str:
    """Убрать reload из JS сессии — в add_init_script это даёт бесконечный цикл."""
    if not raw:
        return raw
    return _RE_LOCATION_RELOAD.sub("", raw).strip()


_RE_STORAGE_CLEAR = re.compile(
    r"(?:sessionStorage|localStorage)\.clear\s*\(\s*\)\s*;?",
    re.IGNORECASE,
)


def strip_storage_clear(raw: str) -> str:
    """Убрать clear() — сбрасывает кэш PWA и зависает на «Обновление…»."""
    if not raw:
        return raw
    return _RE_STORAGE_CLEAR.sub("", raw).strip()


def wrap_session_js_for_inject(clean_js: str) -> str:
    """Обёртка для page.evaluate / add_init_script (несколько строк JS)."""
    s = (clean_js or "").strip()
    if not s:
        return ""
    head = s.lstrip()[:12].casefold()
    if head.startswith("(") or head.startswith("function") or head.startswith("async"):
        return s
    return f"() => {{\n{s}\n}}"


_RE_DEVICE_ID_SETITEM = re.compile(
    r"""__oneme_device_id['"]\s*,\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def extract_session_token(content: str) -> tuple[str | None, str | None]:
    """
    Вернуть (token, viewer_id или None).
    viewer_id — числовой id из JSON, если есть.
    """
    raw = strip_session_preamble(content or "").strip()
    if not raw:
        return None, None

    # 1) JSON.stringify(...) — старый формат
    m = _RE_STRINGIFY.search(raw)
    if m:
        try:
            obj = json.loads(m.group(1))
            tok = (obj.get("token") or "").strip()
            if tok:
                vid = obj.get("viewerId")
                return tok, str(vid) if vid is not None else None
        except json.JSONDecodeError:
            pass

    # 2) localStorage.setItem('__oneme_auth', "{...}") — escaped JSON в кавычках
    for pat in (_RE_SETITEM_ESCAPED, _RE_SETITEM_JSON):
        m = pat.search(raw)
        if m:
            blob = m.group(1)
            # в файле часто \" внутри строки
            for candidate in (blob, blob.replace('\\"', '"').replace("\\\\", "\\")):
                try:
                    obj = json.loads(candidate)
                    tok = (obj.get("token") or "").strip()
                    if tok:
                        vid = obj.get("viewerId")
                        return tok, str(vid) if vid is not None else None
                except json.JSONDecodeError:
                    continue

    # 3) Прямой regex на "token":"..." (работает и внутри JS одной строкой)
    m = _RE_TOKEN_QUOTED.search(raw)
    if m:
        return m.group(1), None

    # 4) Целый файл — JSON
    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
            tok = (obj.get("token") or "").strip()
            if tok:
                vid = obj.get("viewerId")
                return tok, str(vid) if vid is not None else None
        except json.JSONDecodeError:
            pass

    # 5) plain token + device JSON (экспорт my_accounts)
    brace = raw.find('{"deviceType"')
    if brace > 80:
        tok = raw[:brace].strip()
        if re.fullmatch(r"[A-Za-z0-9\-._~+/=]+", tok):
            return tok, None

    return None, None


def extract_device_id(content: str) -> str | None:
    raw = strip_session_preamble(content or "")
    m = _RE_DEVICE_ID_SETITEM.search(raw)
    if m:
        return m.group(1).strip()
    m = re.search(r'"deviceId"\s*:\s*"([^"]+)"', raw)
    return m.group(1) if m else None


# Клиент web.max.ru требует ненулевой viewerId в __oneme_auth, иначе сеттер
# _auth пишет «missing auth.viewerId», удаляет токен и уходит на QR-экран.
# Реальный viewerId сервер возвращает после login (opcode 19), поэтому
# заглушка (1) безопасна: после входа она заменяется настоящим id.
_PLACEHOLDER_VIEWER_ID = 1


def _resolve_viewer_id(vid: str | None) -> int:
    """Ненулевой viewerId: настоящий из файла либо заглушка."""
    if vid is not None and str(vid).strip() not in ("", "0", "0.0"):
        try:
            n = int(str(vid).strip())
            if n != 0:
                return n
        except ValueError:
            pass
    return _PLACEHOLDER_VIEWER_ID


def _build_auth_inject_js(content: str) -> str:
    """Собрать localStorage JS из токена (token + device_id + viewerId)."""
    cleaned = strip_session_preamble(content)
    tok, vid = extract_session_token(cleaned)
    if not tok:
        return ""
    payload: dict = {"token": tok, "viewerId": _resolve_viewer_id(vid)}
    parts: list[str] = []
    device_id = extract_device_id(cleaned)
    if device_id:
        parts.append(
            f"localStorage.setItem('__oneme_device_id', {json.dumps(device_id)});"
        )
    parts.append(
        "localStorage.setItem('__oneme_auth', JSON.stringify("
        + json.dumps(payload, ensure_ascii=False)
        + "));"
    )
    return "".join(parts)


def normalize_session_token(content: str) -> str:
    """
    Единая подготовка токена для запуска (Playwright) и чекера (WS).
    token + device_id + viewerId, без clear/reload.
    """
    built = _build_auth_inject_js(content)
    if built:
        return built
    cleaned = strip_session_preamble(content or "")
    return strip_storage_clear(strip_session_reload(cleaned))


def normalize_for_launch(content: str) -> str:
    """Алиас normalize_session_token (Playwright)."""
    return normalize_session_token(content)


def prepare_js_for_selenium(content: str) -> str:
    """Токен для Selenium: как в .txt, с clear/reload (убираем только PASSWORD/2FA)."""
    return strip_session_preamble(content or "").strip()


def normalize_for_checker(content: str) -> str:
    """Алиас normalize_session_token (чекер)."""
    return normalize_session_token(content)
