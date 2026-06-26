# -*- coding: utf-8 -*-
"""Разведка: добавление контакта через вкладку «Контакты»."""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
OUT = os.path.join(ROOT, "scripts", "test_results")
os.makedirs(OUT, exist_ok=True)

SESSION = "79002673484.txt"
PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"
PHONE = "79045765745"


def dom(page) -> dict:
    return page.evaluate(
        """() => {
      const vis = el => { const r=el.getBoundingClientRect(); return r.width>0&&r.height>0; };
      const btns = [];
      document.querySelectorAll('button,[role=button],[aria-label]').forEach(el=>{
        if(!vis(el)) return;
        const t = (el.innerText||'').trim().slice(0,80);
        const a = el.getAttribute('aria-label')||'';
        if (t || a) btns.push({text:t, aria:a});
      });
      const inputs=[];
      document.querySelectorAll('input,textarea,[role=textbox]').forEach(el=>{
        if(!vis(el)) return;
        inputs.push({ph:el.getAttribute('placeholder')||'', type:el.type||''});
      });
      return {url:location.href, btns:btns.slice(0,40), inputs,
        body:(document.body.innerText||'').slice(0,1200)};
    }"""
    )


def main() -> int:
    from browser_launcher import close_session, launch_session, shutdown_playwright
    from max_ui_actions import MaxUIActions

    js = open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8").read()
    d = launch_session(
        profiles_dir=os.path.join(ROOT, "profiles"),
        session_name=SESSION + "_contacts",
        proxy_raw=PROXY,
        js=js,
        cdp_port=19296,
    )
    if not d:
        print("launch failed")
        return 1
    page = d._mx_playwright_session.page
    ui = MaxUIActions(page, SESSION)
    log: list[dict] = []

    if not ui.wait_app_ready(120000):
        log.append({"step": "not_ready", "dom": dom(page)})
        page.screenshot(path=os.path.join(OUT, "contacts_not_ready.png"))
    else:
        # вкладка Контакты (низ)
        clicked = page.evaluate(
            """() => {
              const vis = el => { const r=el.getBoundingClientRect(); return r.width>0&&r.height>0; };
              const tabs = [...document.querySelectorAll('button,[role=button]')].filter(el => {
                if (!vis(el)) return false;
                const t = (el.innerText||'').trim();
                return t === 'Контакты';
              });
              if (!tabs.length) return false;
              // нижняя панель — максимальный Y
              tabs.sort((a,b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
              tabs[tabs.length-1].click();
              return true;
            }"""
        )
        log.append({"step": "contacts_tab_bottom", "clicked": clicked})
        time.sleep(2)
        page.screenshot(path=os.path.join(OUT, "contacts_01_tab.png"))
        log.append({"step": "contacts_dom", "dom": dom(page)})

        # + на вкладке контактов → «Добавить контакт»
        try:
            page.locator('[aria-label="Начать общение"]').first.click(timeout=5000)
            time.sleep(1)
            log.append({"step": "compose_on_contacts", "dom": dom(page)})
        except Exception as ex:
            log.append({"step": "compose_err", "err": str(ex)})

        try:
            page.locator('[aria-label="Добавить контакт"]').first.click(timeout=5000)
            time.sleep(1.5)
            log.append({"step": "add_contact_menu", "dom": dom(page)})
            page.screenshot(path=os.path.join(OUT, "contacts_02_add_contact.png"))
        except Exception as ex:
            log.append({"step": "add_contact_err", "err": str(ex)})

        modal = page.locator('[data-testid="modal"]')
        scope = modal if modal.count() else page
        try:
            scope.locator("input").first.fill("904 576 57 45", timeout=5000)
            time.sleep(1)
            log.append({"step": "modal_phone", "dom": dom(page)})
            page.screenshot(path=os.path.join(OUT, "contacts_03_phone.png"))
        except Exception as ex:
            log.append({"step": "modal_phone_err", "err": str(ex)})

        for label in ("Найти в MAX", "Найти", "Далее", "Добавить", "Сохранить"):
            try:
                scope.get_by_text(label, exact=True).first.click(timeout=2500)
                time.sleep(2)
                log.append({"step": f"clicked_{label}", "dom": dom(page)})
                page.screenshot(path=os.path.join(OUT, f"contacts_04_{label}.png"))
            except Exception:
                pass

        # поле имени
        try:
            m = page.locator('[data-testid="modal"]')
            s = m if m.count() else page
            for inp in s.locator("input").all():
                ph = (inp.get_attribute("placeholder") or "").lower()
                log.append({"step": "input_ph", "ph": ph})
            s.locator("input").nth(1).fill("Тестов Тест Тестович 01.01.1990", timeout=3000)
            time.sleep(1)
            log.append({"step": "name_filled", "dom": dom(page)})
        except Exception as ex:
            log.append({"step": "name_err", "err": str(ex)})

    with open(os.path.join(OUT, "contacts_flow_log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    close_session(d._mx_playwright_session)
    shutdown_playwright()
    print("written", os.path.join(OUT, "contacts_flow_log.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
