# -*- coding: utf-8 -*-
"""Быстрые unit-тесты без браузера."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_suite_common import phone_from_session_file, save_json


def test_store_roundtrip() -> dict:
    from campaign_store import (
        ChatMessage,
        DialogRecord,
        add_dialog,
        append_messages,
        list_dialogs,
        list_messages,
        _store_path,
    )

    test_sd = os.path.join(ROOT, "sessions", "_crm_unit_test")
    os.makedirs(test_sd, exist_ok=True)
    p = _store_path(test_sd)
    if os.path.isfile(p):
        os.remove(p)

    try:
        d = add_dialog(
            test_sd,
            DialogRecord.create(
                session_name="unit.txt",
                group_title="Unit Group",
                lead_fio="Тест",
                lead_phone="79000000000",
            ),
        )
        append_messages(
            test_sd, d.id, [ChatMessage.create(d.id, "out", "ping")]
        )
        ok = len(list_dialogs(test_sd)) == 1 and len(list_messages(test_sd, d.id)) == 1
        return {"test": "store_roundtrip", "ok": ok}
    finally:
        if os.path.isfile(p):
            os.remove(p)


def test_coordinator() -> dict:
    from campaign_coordinator import plan_round_robin, summarize_plan
    from contact_database import ContactRecord

    sessions = [f"s{i}.txt" for i in range(10)]
    records = [
        ContactRecord(fio=f"L{i}", phones=[(f"790000000{i:02d}", "")])
        for i in range(30)
    ]
    plan = plan_round_robin(sessions, records)
    summary = summarize_plan(plan)
    ok = summary["total_assignments"] == 30 and summary["rounds"] == 3
    ok = ok and all(summary["per_session"].get(s) == 3 for s in sessions)
    return {"test": "coordinator", "ok": ok, "summary": summary}


def test_smart_sync_pick() -> dict:
    from campaign_store import STATUS_AWAITING, STATUS_REPLIED, DialogRecord
    from crm_service import pick_dialogs_for_smart_sync

    sd = "_smart_sync_test"
    dialogs = [
        DialogRecord(
            id="a",
            session_name="1.txt",
            status=STATUS_AWAITING,
            group_title="G1",
            lead_fio="A",
        ),
        DialogRecord(
            id="b",
            session_name="2.txt",
            status=STATUS_REPLIED,
            group_title="G2",
            lead_fio="B",
            unread=2,
        ),
        DialogRecord(
            id="c",
            session_name="3.txt",
            status=STATUS_REPLIED,
            group_title="G3",
            lead_fio="C",
            unread=0,
        ),
    ]

    from unittest.mock import patch

    with patch("crm_service.list_dialogs", return_value=dialogs):
        with patch("crm_service.get_crm_keyword", return_value=""):
            with patch("crm_service._SYNC_CURSORS", {}):
                picked = pick_dialogs_for_smart_sync(sd, None, batch_size=3)
    ok = len(picked) == 1 and picked[0].id == "b"
    with patch("crm_service.list_dialogs", return_value=dialogs):
        with patch("crm_service.get_crm_keyword", return_value=""):
            with patch("crm_service._SYNC_CURSORS", {}):
                picked2 = pick_dialogs_for_smart_sync(sd, None, batch_size=2)
    ok = ok and {d.id for d in picked2} <= {"b", "c", "a"}
    return {"test": "smart_sync_pick", "ok": ok}


def test_delete_dialog() -> dict:
    from campaign_store import (
        ChatMessage,
        DialogRecord,
        add_dialog,
        delete_dialog,
        get_dialog,
        list_messages,
        _store_path,
    )

    test_sd = os.path.join(ROOT, "sessions", "_crm_delete_test")
    os.makedirs(test_sd, exist_ok=True)
    p = _store_path(test_sd)
    if os.path.isfile(p):
        os.remove(p)
    try:
        d = add_dialog(
            test_sd,
            DialogRecord.create(
                session_name="1.txt",
                group_title="G",
                lead_fio="Test",
            ),
        )
        from campaign_store import append_messages

        append_messages(
            test_sd, d.id, [ChatMessage.create(d.id, "in", "hi")]
        )
        ok = delete_dialog(test_sd, d.id)
        ok = ok and get_dialog(test_sd, d.id) is None
        ok = ok and len(list_messages(test_sd, d.id)) == 0
        return {"test": "delete_dialog", "ok": ok}
    finally:
        if os.path.isfile(p):
            os.remove(p)


def test_ui_chrome_title() -> dict:
    from max_ui_actions import MaxUIActions, is_ui_chrome_title

    ok = is_ui_chrome_title("Новые")
    ok = ok and is_ui_chrome_title("Новые 2")
    ok = ok and is_ui_chrome_title("Каналы 5")
    ok = ok and not is_ui_chrome_title("ИВАНОВ ИВАН 01.01.1990")
    lines = ["Все", "Новые", "Каналы", "АРХИПЦОВА", "23:48", "Контакты"]
    filtered = MaxUIActions._filter_chat_title_lines(lines, limit=10)
    ok = ok and filtered == ["АРХИПЦОВА"]
    return {"test": "ui_chrome_title", "ok": ok}


def test_store_cache() -> dict:
    from campaign_store import (
        DialogRecord,
        add_dialog,
        load_store,
        _store_path,
    )

    test_sd = os.path.join(ROOT, "sessions", "_store_cache_test")
    os.makedirs(test_sd, exist_ok=True)
    p = _store_path(test_sd)
    if os.path.isfile(p):
        os.remove(p)
    try:
        add_dialog(
            test_sd,
            DialogRecord.create(
                session_name="a.txt", group_title="G", lead_fio="X"
            ),
        )
        a = load_store(test_sd)
        b = load_store(test_sd)
        ok = a is not b and len(a.get("dialogs") or []) == 1
        return {"test": "store_cache", "ok": ok}
    finally:
        if os.path.isfile(p):
            os.remove(p)


def test_group_dialogs() -> dict:
    from campaign_store import STATUS_REPLIED, DialogRecord
    from crm_helpers import format_chat_row, group_dialogs_by_session

    dialogs = [
        DialogRecord(
            id="1",
            session_name="b.txt",
            status=STATUS_REPLIED,
            lead_alias="B",
            group_title="G1",
        ),
        DialogRecord(
            id="2",
            session_name="a.txt",
            status=STATUS_REPLIED,
            lead_alias="A",
            group_title="G2",
            unread=1,
        ),
    ]
    groups = group_dialogs_by_session(dialogs)
    ok = len(groups) == 2
    ok = ok and groups[0][0] == "a.txt" and len(groups[0][1]) == 1
    ok = ok and "●" in format_chat_row(groups[0][1][0])
    return {"test": "group_dialogs", "ok": ok}


def test_resolve_chat_title() -> dict:
    from chat_bridge import resolve_chat_title

    class _FakeUi:
        def list_chat_titles(self, limit=120):
            return ["Игорь", "УТКИНА ПОЛИНА 15.04.1960"]

    ui = _FakeUi()
    ok = resolve_chat_title(ui, "Игорь") == "Игорь"
    ok = ok and resolve_chat_title(ui, "УТКИНА ПОЛИНА") == "УТКИНА ПОЛИНА 15.04.1960"
    return {"test": "resolve_chat_title", "ok": ok}


def test_crm_format() -> dict:
    from campaign_store import STATUS_REPLIED, DialogRecord
    from crm_helpers import format_dialog_row, format_token_label

    row = format_dialog_row(
        DialogRecord(
            id="x",
            session_name="79504503453__КОММЕНТАРИЙ.txt",
            status=STATUS_REPLIED,
            lead_alias="ИВАНОВ ИВАН 01.01.1990",
            unread=1,
            group_title="G",
        )
    )
    ok = "● Ответил" in row and "ИВАНОВ" in row
    ok = ok and format_token_label("79002673484.txt") == "+79002673484"
    return {"test": "crm_format", "ok": ok}


def test_lead_registry() -> dict:
    from lead_registry import reset_claims, try_claim

    reset_claims()
    ok, _ = try_claim("79001234567", "a.txt")
    ok2, owner = try_claim("79001234567", "b.txt")
    ok3, _ = try_claim("79007654321", "b.txt")
    return {
        "test": "lead_registry",
        "ok": ok and not ok2 and owner == "a.txt" and ok3,
    }


def test_lead_distribution_unique() -> dict:
    from campaign_coordinator import assignments_for_session, plan_round_robin
    from contact_database import ContactRecord

    sessions = sorted(["c.txt", "a.txt", "b.txt"])
    records = [
        ContactRecord(fio=f"L{i}", phones=[(f"7900000000{i}", "")])
        for i in range(7)
    ]
    plan = plan_round_robin(sessions, records)
    indices = [a.record_index for a in plan]
    by_sess = {s: assignments_for_session(plan, s) for s in sessions}
    first = {s: by_sess[s][0].record_index for s in sessions}
    ok = len(set(indices)) == len(indices)
    ok = ok and first == {"a.txt": 0, "b.txt": 1, "c.txt": 2}
    return {"test": "lead_distribution", "ok": ok, "first_round": first}


def test_runner_assignments() -> dict:
    from automation_config import load_automation_config, save_automation_config
    from automation_runner import _build_session_assignments
    from contact_database import ContactRecord, parse_contact_database

    cfg = load_automation_config()
    old_inline = cfg.get("database_inline")
    cfg["database_inline"] = """Иванов Иван
01.01.1990
79001111111
-------
Петров Пётр
02.02.1991
79002222222
-------
Сидоров Сидор
03.03.1992
79003333333
-------
"""
    cfg["database_start_index"] = 0
    save_automation_config(cfg)

    try:
        names = sorted(["z.txt", "a.txt", "m.txt"])
        by, plan = _build_session_assignments(names)
        first = {n: by[n][0].record_index for n in names if by.get(n)}
        ok = first == {"a.txt": 0, "m.txt": 1, "z.txt": 2}
        ok = ok and len({a.record_index for a in plan}) == 3
        return {"test": "runner_assignments", "ok": ok, "first_round": first}
    finally:
        cfg["database_inline"] = old_inline
        save_automation_config(cfg)


def test_message_templates() -> dict:
    from automation_config import message_for_record, post_group_steps_for_record
    from contact_database import ContactRecord

    rec = ContactRecord(
        fio="Иванов Иван",
        dob="01.01.1990",
        phones=[("79001234567", "Иван")],
    )
    cfg = {
        "first_message_templates": ["Привет, {short_name}!", "Добрый день!"],
        "post_group_steps": [{"type": "wait_reply", "timeout_sec": 60}],
        "group_name_counter": 1,
    }
    m0 = message_for_record(rec, 0, cfg=cfg)
    m1 = message_for_record(rec, 1, cfg=cfg)
    steps = post_group_steps_for_record(rec, 0, cfg=cfg)
    ok = m0 == "Привет, Иван!" and m1 == "Добрый день!"
    ok = ok and steps[0]["text"] == "Привет, Иван!"
    return {"test": "message_templates", "ok": ok}


def test_plain_token_parse() -> dict:
    from session_token_parse import extract_device_id, extract_session_token, normalize_for_checker

    path = os.path.join(ROOT, "sessions", "my_accounts_1_20260611_1558.txt")
    sample = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    if not sample:
        return {"test": "plain_token_parse", "ok": True, "skip": "no my_accounts file"}
    tok, _ = extract_session_token(sample)
    dev = extract_device_id(sample)
    js = normalize_for_checker(sample)
    ok = bool(tok) and tok.startswith("An_")
    ok = ok and dev == "083c0e51-4681-4342-a552-ad3f2f45e2fe"
    ok = ok and "__oneme_device_id" in js and "__oneme_auth" in js
    return {"test": "plain_token_parse", "ok": ok}


def test_reply_filter() -> dict:
    from automation_engine import AutomationEngine

    sent = {"Пинг 123"}
    ok = not AutomationEngine._is_real_reply(
        "Вы создали чат", sent=sent, ignore_own=True
    )
    ok = ok and not AutomationEngine._is_real_reply(
        "Пинг 123", sent=sent, ignore_own=True
    )
    ok = ok and AutomationEngine._is_real_reply(
        "Ответ лида 123", sent=sent, ignore_own=True
    )
    return {"test": "reply_filter", "ok": ok}


def test_phone_from_filename() -> dict:
    ok = phone_from_session_file("79002673484.txt") == "79002673484"
    ok = ok and phone_from_session_file("+79273295162.txt") == "79273295162"
    ok = ok and phone_from_session_file("my_accounts_1.txt") == ""
    return {"test": "phone_from_filename", "ok": ok}


def test_list_token_files_recursive() -> dict:
    import tempfile
    from token_checker import list_token_files

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "batch_a"))
        open(os.path.join(tmp, "root.txt"), "w", encoding="utf-8").write("t")
        open(os.path.join(tmp, "batch_a", "nested.txt"), "w", encoding="utf-8").write("t")
        open(os.path.join(tmp, "batch_a", "skip.json"), "w", encoding="utf-8").write("{}")
        os.makedirs(os.path.join(tmp, "alive"))
        open(os.path.join(tmp, "alive", "skip.txt"), "w", encoding="utf-8").write("t")
        flat = list_token_files(tmp, recursive=False)
        deep = list_token_files(tmp, recursive=True)
        ok = flat == ["root.txt"]
        ok = ok and len(deep) == 2 and "root.txt" in deep
        ok = ok and any(p.replace("\\", "/").endswith("batch_a/nested.txt") for p in deep)
        ok = ok and not any("alive" in p for p in deep)
    return {"test": "list_token_files_recursive", "ok": ok}


def test_mark_alive_moves_to_alive() -> dict:
    import tempfile
    from token_checker import alive_dir, mark_alive_file

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "batch", "token.txt")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "w", encoding="utf-8") as f:
            f.write("localStorage token")
        out = mark_alive_file(src, checktoken_root=tmp, log=lambda _m: None)
        ok = os.path.isfile(out)
        ok = ok and out.startswith(alive_dir(tmp))
        ok = ok and not os.path.exists(src)
        with open(out, encoding="utf-8") as f:
            ok = ok and f.readline().strip().upper() == "ЖИВОЙ"
    return {"test": "mark_alive_moves_to_alive", "ok": ok}


def test_normalize_launch_checker_same() -> dict:
    from session_token_parse import (
        normalize_for_checker,
        normalize_for_launch,
        normalize_session_token,
    )

    raw = (
        "sessionStorage.clear();\n"
        "localStorage.setItem('__oneme_auth','{\"token\":\"AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
        "AbCdEfGhIjKlMnOpQr\"}');\n"
        "window.location.reload();\n"
    )
    launch = normalize_for_launch(raw)
    check = normalize_for_checker(raw)
    unified = normalize_session_token(raw)
    ok = launch == check == unified
    ok = ok and '"viewerId": 1' in unified
    ok = ok and ".clear()" not in unified
    return {"test": "normalize_launch_checker_same", "ok": ok}


def test_alive_tag_launch_js() -> dict:
    from session_token_parse import (
        extract_device_id,
        normalize_for_launch,
        wrap_session_js_for_inject,
    )

    sample = (
        "ЖИВОЙ\n"
        "sessionStorage.clear();\n"
        "localStorage.clear();\n"
        "localStorage.setItem('__oneme_device_id','e1b84aad-9861-45ba-83f5-b0679c9ce2d1');\n"
        "localStorage.setItem('__oneme_auth','{\"token\":\"AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
        "AbCdEfGhIjKlMnOpQr\",\"viewerId\":0}');\n"
        "window.location.reload();\n"
    )
    js = normalize_for_launch(sample)
    wrapped = wrap_session_js_for_inject(js)
    dev = extract_device_id(sample)
    ok = dev == "e1b84aad-9861-45ba-83f5-b0679c9ce2d1"
    ok = ok and "__oneme_device_id" in js
    ok = ok and "JSON.stringify" in js
    # viewerId обязателен и ненулевой: 0 заменяется на заглушку 1
    ok = ok and '"viewerId": 1' in js
    ok = ok and '"viewerId": 0' not in js
    ok = ok and "живой" not in js.casefold()
    ok = ok and ".clear()" not in js
    ok = ok and wrapped.startswith("() => {")
    return {"test": "alive_tag_launch_js", "ok": ok}


def test_checktoken_parallel_default() -> dict:
    from token_checker import _DEFAULT_PARALLEL

    workers = max(1, min(int(_DEFAULT_PARALLEL or 1), 16))
    ok = _DEFAULT_PARALLEL == 5 and workers == 5
    ok = ok and max(1, min(20, 16)) == 16
    ok = ok and max(1, min(0, 16)) == 1
    return {"test": "checktoken_parallel_default", "ok": ok}


def test_proxy_media_bypass_modes() -> dict:
    from unittest.mock import patch

    from browser_launcher import _apply_proxy_media_bypass, _proxy_bypass_mode

    base = {"server": "http://proxy.test:8080", "username": "u", "password": "p"}
    ok = _proxy_bypass_mode() in ("max", "cdn", "off")
    with patch("browser_launcher._proxy_bypass_mode", return_value="max"):
        out = _apply_proxy_media_bypass(dict(base))
    bypass_parts = [p.strip() for p in out.get("bypass", "").split(",")]
    ok = ok and ".max.ru" in bypass_parts
    ok = ok and "i.oneme.ru" in bypass_parts
    ok = ok and ".okcdn.ru" in bypass_parts
    ok = ok and "*.max.ru" not in bypass_parts
    with patch("browser_launcher._proxy_bypass_mode", return_value="off"):
        off = _apply_proxy_media_bypass(dict(base))
    ok = ok and "bypass" not in off
    return {"test": "proxy_media_bypass_modes", "ok": ok}


def test_profile_media_enabled() -> dict:
    import json
    import shutil
    import tempfile

    from browser_profile_prefs import ensure_profile_media_enabled

    tmp = tempfile.mkdtemp(prefix="mx_profile_media_")
    try:
        profile_dir = os.path.join(tmp, "79001112233.txt")
        prefs_path = os.path.join(profile_dir, "Default", "Preferences")
        os.makedirs(os.path.dirname(prefs_path), exist_ok=True)
        with open(prefs_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "profile": {
                        "default_content_setting_values": {"images": 2},
                        "content_settings": {
                            "exceptions": {
                                "images": {"https://web.max.ru,*": {"setting": 2}}
                            }
                        },
                    }
                },
                f,
            )

        ensure_profile_media_enabled(profile_dir)
        with open(prefs_path, encoding="utf-8") as f:
            data = json.load(f)
        prof = data.get("profile", {})
        dcv = prof.get("default_content_setting_values", {})
        ok = dcv.get("images") == 1
        exc = prof.get("content_settings", {}).get("exceptions", {})
        ok = ok and exc.get("images") == {}
        return {"test": "profile_media_enabled", "ok": ok}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_crm_keyword_filter() -> dict:
    from crm_filter import (
        DEFAULT_CRM_KEYWORD,
        dialog_matches_keyword,
        title_matches_keyword,
    )

    ok = DEFAULT_CRM_KEYWORD == "ЖКХ, ключ"
    ok = ok and title_matches_keyword("Чат ЖКХ Двор", "ЖКХ")
    ok = ok and title_matches_keyword("жкх ремонт", "ЖКХ")
    ok = ok and not title_matches_keyword("Соседи 2-й подъезд", "ЖКХ")
    # несколько слов через запятую: совпадение по любому
    ok = ok and title_matches_keyword("Ключ от подъезда", "ЖКХ, ключ")
    ok = ok and title_matches_keyword("дом ЖКХ 5", "ЖКХ, ключ")
    ok = ok and not title_matches_keyword("Просто соседи", "ЖКХ, ключ")
    # пустое ключевое слово отключает фильтр
    ok = ok and title_matches_keyword("любой чат", "")

    class _D:
        def __init__(self, group_title="", lead_alias=""):
            self.group_title = group_title
            self.lead_alias = lead_alias

    ok = ok and dialog_matches_keyword(_D(group_title="ЖКХ дом 5"), "ЖКХ")
    ok = ok and dialog_matches_keyword(_D(lead_alias="чат жкх"), "ЖКХ")
    ok = ok and not dialog_matches_keyword(_D(group_title="Просто чат"), "ЖКХ")
    ok = ok and dialog_matches_keyword(_D(group_title="Ключи во дворе"), "ЖКХ, ключ")
    return {"test": "crm_keyword_filter", "ok": ok}


def test_profile_cleanup_orphans() -> dict:
    import shutil
    import tempfile

    from profile_cleanup import cleanup_orphan_profiles, profile_has_token

    tmp = tempfile.mkdtemp(prefix="mx_profile_cleanup_")
    try:
        tokenbase = os.path.join(tmp, "tokenbase")
        profiles = os.path.join(tmp, "profiles")
        os.makedirs(tokenbase, exist_ok=True)
        os.makedirs(profiles, exist_ok=True)

        keep_name = "79001112233.txt"
        with open(os.path.join(tokenbase, keep_name), "w", encoding="utf-8") as f:
            f.write("token")

        for rel in ("79001112233.txt", "orphan.txt", "legacy_no_ext"):
            prof = os.path.join(profiles, rel)
            os.makedirs(os.path.join(prof, "Default"), exist_ok=True)

        running = os.path.join(profiles, "running.txt")
        os.makedirs(os.path.join(running, "Default"), exist_ok=True)

        stats = cleanup_orphan_profiles(
            profiles,
            tokenbase,
            is_running=lambda name: name == "running.txt",
        )
        ok = stats["deleted"] == 2
        ok = ok and os.path.isdir(os.path.join(profiles, keep_name))
        ok = ok and not os.path.isdir(os.path.join(profiles, "orphan.txt"))
        ok = ok and not os.path.isdir(os.path.join(profiles, "legacy_no_ext"))
        ok = ok and os.path.isdir(running)
        ok = ok and profile_has_token("79001112233", {"79001112233.txt"})
        return {"test": "profile_cleanup_orphans", "ok": ok, "stats": stats}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_update_version_compare() -> dict:
    from update_checker import is_newer_version

    ok = is_newer_version("1.3.0", "1.2.7")
    ok = ok and not is_newer_version("1.2.7", "1.2.7")
    ok = ok and not is_newer_version("1.2.0", "1.2.7")
    ok = ok and is_newer_version("1.2.8", "1.2.7")
    return {"test": "update_version_compare", "ok": ok}


def test_playwright_uses_selenium_wire_relay() -> dict:
    from unittest.mock import patch

    from browser_launcher import _is_local_relay_proxy, _prepare_browser_proxy

    with patch("proxy_backend.allocate_relay_port", return_value=23456), patch(
        "proxy_backend.start_backend", return_value=object()
    ):
        proxy, port = _prepare_browser_proxy("proxy.test:8080:user:pass")
    ok = port == 23456
    ok = ok and proxy is not None
    ok = ok and proxy.get("server") == "http://127.0.0.1:23456"
    ok = ok and _is_local_relay_proxy(proxy)
    direct, p0 = _prepare_browser_proxy("")
    ok = ok and direct is None and p0 == 0
    return {"test": "playwright_uses_selenium_wire_relay", "ok": ok}


def test_browser_engine_default() -> dict:
    from unittest.mock import patch

    from browser_engine import ENGINE_SELENIUM, get_browser_engine, use_playwright
    from session_token_parse import prepare_js_for_selenium

    with patch("browser_engine.load_settings", return_value={"browser_engine": "selenium"}):
        ok = get_browser_engine() == ENGINE_SELENIUM
        ok = ok and not use_playwright()
    raw = (
        "PASSWORD: x\n"
        "sessionStorage.clear();\n"
        "localStorage.clear();\n"
        "localStorage.setItem('__oneme_auth', '{}');\n"
        "window.location.reload();\n"
    )
    prep = prepare_js_for_selenium(raw)
    ok = ok and "sessionStorage.clear()" in prep
    ok = ok and "localStorage.clear()" in prep
    ok = ok and "reload" in prep
    ok = ok and "PASSWORD" not in prep
    return {"test": "browser_engine_default", "ok": ok}


def test_user_token_parse_790930126660() -> dict:
    from session_token_parse import extract_device_id, extract_session_token, normalize_session_token

    path = os.path.join(ROOT, "scripts", "test_data", "790930126660.txt")
    if not os.path.isfile(path):
        return {"test": "user_token_parse_790930126660", "ok": True, "skipped": True}
    raw = open(path, encoding="utf-8").read()
    tok, vid = extract_session_token(raw)
    dev = extract_device_id(raw)
    prep = normalize_session_token(raw)
    ok = bool(tok) and len(tok or "") > 100
    ok = ok and vid == "164650160"
    ok = ok and dev == "eb2a16b1-2f3b-44aa-8b05-d1b64e890424"
    ok = ok and extract_session_token(prep)[0] == tok
    ok = ok and ".clear()" not in prep and "reload" not in prep.casefold()
    return {"test": "user_token_parse_790930126660", "ok": ok}


def run_all() -> dict:
    tests = []
    for fn in (
        test_store_roundtrip,
        test_coordinator,
        test_smart_sync_pick,
        test_delete_dialog,
        test_ui_chrome_title,
        test_store_cache,
        test_group_dialogs,
        test_resolve_chat_title,
        test_crm_format,
        test_lead_registry,
        test_lead_distribution_unique,
        test_runner_assignments,
        test_message_templates,
        test_plain_token_parse,
        test_reply_filter,
        test_phone_from_filename,
        test_list_token_files_recursive,
        test_checktoken_parallel_default,
        test_normalize_launch_checker_same,
        test_alive_tag_launch_js,
        test_crm_keyword_filter,
        test_profile_cleanup_orphans,
        test_proxy_media_bypass_modes,
        test_profile_media_enabled,
        test_update_version_compare,
        test_browser_engine_default,
        test_playwright_uses_selenium_wire_relay,
        test_user_token_parse_790930126660,
        test_mark_alive_moves_to_alive,
    ):
        try:
            tests.append(fn())
        except Exception as ex:
            tests.append({"test": fn.__name__, "ok": False, "error": str(ex)})

    report = {
        "suite": "unit",
        "passed": sum(1 for t in tests if t.get("ok")),
        "total": len(tests),
        "tests": tests,
    }
    save_json("unit_report.json", report)
    return report


def main() -> int:
    report = run_all()
    for t in report["tests"]:
        mark = "OK" if t.get("ok") else "FAIL"
        print(f"{mark}: {t.get('test')}")
    print(f"\n{report['passed']}/{report['total']} passed")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
