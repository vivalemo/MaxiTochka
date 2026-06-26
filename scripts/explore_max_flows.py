# -*- coding: utf-8 -*-
"""Разбор UI-потоков MAX."""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
OUT = os.path.join(ROOT, "scripts", "test_results")
os.makedirs(OUT, exist_ok=True)

SESSION = "+79273295162.txt"
PROXY = "proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0"

def dom(page):
    return page.evaluate("""() => {
      const vis = el => { const r=el.getBoundingClientRect(); return r.width>0&&r.height>0; };
      const btns = [];
      document.querySelectorAll('button,[role=button]').forEach(el=>{
        if(!vis(el)) return;
        btns.push({text:(el.innerText||'').trim().slice(0,80), aria:el.getAttribute('aria-label')||''});
      });
      const inputs=[];
      document.querySelectorAll('input,textarea,[role=textbox]').forEach(el=>{
        if(!vis(el)) return;
        inputs.push({ph:el.getAttribute('placeholder')||'', role:el.getAttribute('role')||''});
      });
      return {url:location.href, btns:btns.slice(0,25), inputs, body:(document.body.innerText||'').slice(0,500)};
    }""")

def shot(page, n):
    page.screenshot(path=os.path.join(OUT, f"flow_{n}.png"))

def click_aria(page, aria):
    page.locator(f'[aria-label="{aria}"]').first.click(timeout=8000)

def click_text(page, text):
    page.get_by_text(text, exact=True).first.click(timeout=8000)

from browser_launcher import launch_session, close_session, shutdown_playwright
js = open(os.path.join(ROOT, "sessions", SESSION), encoding="utf-8").read()
d = launch_session(
    profiles_dir=os.path.join(ROOT, "profiles"),
    session_name=SESSION + "_flow",
    proxy_raw=PROXY,
    js=js,
    cdp_port=19293,
)
page = d._mx_playwright_session.page
time.sleep(3)
log = []

# --- Найти по номеру ---
click_aria(page, "Начать общение")
time.sleep(1)
log.append({"step": "menu", "dom": dom(page)})
shot(page, "01_menu")

click_text(page, "Найти по номеру")
time.sleep(1)
log.append({"step": "find_phone_screen", "dom": dom(page)})
shot(page, "02_find_phone")

inp = page.locator("input:visible").first
inp.fill("79045765745")
time.sleep(2)
log.append({"step": "phone_typed", "dom": dom(page)})
shot(page, "03_phone_result")

page.keyboard.press("Escape")
time.sleep(0.5)
page.keyboard.press("Escape")
time.sleep(0.5)

# --- Создать группу ---
click_aria(page, "Начать общение")
time.sleep(0.8)
click_text(page, "Создать группу")
time.sleep(1)
log.append({"step": "group_screen", "dom": dom(page)})
shot(page, "04_group")

# название группы
visible_inputs = page.locator("input:visible")
for i in range(visible_inputs.count()):
    ph = visible_inputs.nth(i).get_attribute("placeholder") or ""
    log.append({"input": i, "placeholder": ph})

group_title = "АвтоТест MX"
visible_inputs.first.fill(group_title)
time.sleep(0.5)
shot(page, "05_group_name")

# участник
member_inp = None
for i in range(visible_inputs.count()):
    ph = (visible_inputs.nth(i).get_attribute("placeholder") or "").lower()
    if i > 0 or "участ" in ph or "найти" in ph or "добав" in ph:
        member_inp = visible_inputs.nth(i)
        break
if member_inp is None and visible_inputs.count() > 1:
    member_inp = visible_inputs.nth(1)
if member_inp:
    member_inp.fill("Вадим")
    time.sleep(2)
    log.append({"step": "member_search", "dom": dom(page)})
    shot(page, "06_member_search")
    try:
        page.locator("button").filter(has_text="Вадим").first.click(timeout=3000)
    except Exception:
        page.get_by_text("Вадим", exact=False).first.click(timeout=3000)
    time.sleep(1)
    shot(page, "07_member_selected")

for label in ("Создать", "Готово", "Далее"):
    try:
        page.get_by_role("button", name=label, exact=True).click(timeout=2500)
        time.sleep(2)
        log.append({"step": "clicked_" + label, "dom": dom(page)})
        shot(page, "08_" + label)
        break
    except Exception:
        pass

# проверка группы в списке
page.get_by_role("button", name="Чаты").click(timeout=5000)
time.sleep(2)
found = False
try:
    found = page.get_by_text(group_title, exact=False).first.is_visible(timeout=5000)
except Exception:
    pass
log.append({"step": "group_in_chats", "found": found, "dom": dom(page)})
shot(page, "09_chats")

with open(os.path.join(OUT, "flow_log.json"), "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

close_session(d._mx_playwright_session)
shutdown_playwright()
