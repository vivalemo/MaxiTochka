# -*- coding: utf-8 -*-
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
SESSION="+79273295162.txt"
TEST_DB = """Тестов Тест Тестович
01.01.1990
79045765745 Вадим
-------
"""
from browser_launcher import launch_session, close_session, shutdown_playwright
from automation_config import load_automation_config, save_automation_config
from automation_engine import AutomationEngine

js=open(os.path.join(ROOT,"sessions",SESSION),encoding="utf-8").read()
d=launch_session(profiles_dir=os.path.join(ROOT,"profiles"),session_name=SESSION+"_auto",proxy_raw="proxy.proxyma.io:10062:mUjWhsclWb:OHVx4PCwZ0",js=js,cdp_port=19290)
cfg=load_automation_config()
cfg.update({"database_inline":TEST_DB,"database_file":"","contacts_per_account_max":1,"groups_per_account_max":1,"post_group_steps":[]})
for k in cfg.get("delays_sec",{}): cfg["delays_sec"][k]=[1,2]
save_automation_config(cfg)
state=AutomationEngine(d, SESSION+"_auto").run_database_workflow()
r={"ok":not state.error and state.groups_created>=1,"error":state.error,"groups":state.groups_created,"contacts":state.contacts_added,"log":state.log}
open(os.path.join(ROOT,"scripts","test_results","auto_only.json"),"w",encoding="utf-8").write(json.dumps(r,ensure_ascii=False,indent=2))
close_session(d._mx_playwright_session); shutdown_playwright()
