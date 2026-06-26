# -*- coding: utf-8 -*-
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
OUT = os.path.join(ROOT, "scripts", "test_results")

def dom(page):
    return page.evaluate("""() => ({
      url: location.href,
      body: (document.body.innerText||'').slice(0,600),
      inputs: [...document.querySelectorAll('input,textarea')].map(el=>({ph:el.placeholder||'', vis: el.offsetParent!==null})),
      btns: [...document.querySelectorAll('button')].filter(el=>el.offsetParent).map(el=>(el.innerText||el.getAttribute('aria-label')||'').trim()).filter(Boolean).slice(0,20)
    })""")

from browser_launcher import launch_session, close_session, shutdown_playwright
SESSION="+79273295162.txt"
js=open(os.path.join(ROOT,"sessions",SESSION),encoding="utf-8").read()
d=launch_session(profiles_dir=os.path.join(ROOT,"profiles"),session_name=SESSION+"_gf",proxy_raw="proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0",js=js,cdp_port=19292)
p=d._mx_playwright_session.page
time.sleep(3)
log=[]

p.locator('[aria-label="Начать общение"]').click()
time.sleep(1)
p.get_by_text("Создать группу", exact=True).click()
time.sleep(1)
modal=p.locator('[data-testid="modal"]')
modal.locator('input').first.fill("Вадим")
time.sleep(2)
# select first result row in modal (not cancel/next)
modal.locator('button').filter(has_text="Вадим").first.click()
time.sleep(1)
log.append({"after_select":dom(p)})
p.screenshot(path=os.path.join(OUT,"gf_01_select.png"))

modal.get_by_role("button", name="Далее").click()
time.sleep(1.5)
log.append({"after_next":dom(p)})
p.screenshot(path=os.path.join(OUT,"gf_02_next.png"))

title = "АвтоТест " + str(int(time.time()) % 100000)
for inp in modal.locator("input:visible").all():
    try:
        inp.fill(title)
        break
    except Exception:
        pass
log.append({"after_title":dom(p)})
p.screenshot(path=os.path.join(OUT,"gf_03_title.png"))

for btn in ("Создать", "Готово"):
    try:
        modal.get_by_role("button", name=btn, exact=True).click(timeout=2000)
        time.sleep(2)
        log.append({"clicked":btn,"dom":dom(p)})
        break
    except Exception:
        pass
p.screenshot(path=os.path.join(OUT,"gf_04_done.png"))

p.get_by_role("button", name="Чаты").click(timeout=5000)
time.sleep(2)
found = p.get_by_text(title, exact=False).count() > 0
log.append({"group_in_list":found,"title":title,"dom":dom(p)})
p.screenshot(path=os.path.join(OUT,"gf_05_list.png"))

with open(os.path.join(OUT,"gf_log.json"),"w",encoding="utf-8") as f:
    json.dump(log,f,ensure_ascii=False,indent=2)
close_session(d._mx_playwright_session)
shutdown_playwright()
