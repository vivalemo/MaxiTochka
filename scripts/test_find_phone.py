# -*- coding: utf-8 -*-
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from browser_launcher import launch_session, close_session, shutdown_playwright

SESSION="+79273295162.txt"
js=open(os.path.join(ROOT,"sessions",SESSION),encoding="utf-8").read()
d=launch_session(profiles_dir=os.path.join(ROOT,"profiles"),session_name=SESSION+"_fp",proxy_raw="proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0",js=js,cdp_port=19291)
p=d._mx_playwright_session.page
time.sleep(3)
p.locator('[aria-label="Начать общение"]').click()
time.sleep(1)
p.get_by_text("Найти по номеру", exact=True).click()
time.sleep(1)
modal=p.locator('[data-testid="modal"]')
modal.locator("input:visible").first.fill("904 576 57 45")
time.sleep(0.5)
modal.get_by_role("button", name="Найти в MAX").click()
time.sleep(3)
text=modal.inner_text()
p.screenshot(path=os.path.join(ROOT,"scripts","test_results","find_phone_result.png"))
open(os.path.join(ROOT,"scripts","test_results","find_phone_text.txt"),"w",encoding="utf-8").write(text)
close_session(d._mx_playwright_session)
shutdown_playwright()
