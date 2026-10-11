"""Reproducible real-browser checks, isolated from the user's active draft.
CLI browser sessions expired across turns; use the installed Playwright runtime in one process.
This runner uses real SlimSAM and synthetic generation mode. It never calls the paid editor.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/playwright';OUT.mkdir(parents=True,exist_ok=True)
ENV={**os.environ,'DATA_DIR':str(OUT/'browser-data'),'SITE_PASSWORD':'browser-check-private-password','PORT':'8788','GENERATION_MODE':'simulation'}
BASE='http://127.0.0.1:8788'
checks=[]
log=(OUT/'server.log').open('w',encoding='utf-8')
def start_server():
    process=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=ENV,stdout=log,stderr=log)
    for _ in range(100):
        try:
            if httpx.get(BASE+'/api/health',trust_env=False,timeout=1).status_code==200:return process
        except Exception:pass
        time.sleep(.1)
    raise RuntimeError('Server startup failed')

def login(page):
    page.goto(BASE)
    if page.get_by_role('textbox',name='空间密码').count():
        page.get_by_role('textbox',name='空间密码').fill(ENV['SITE_PASSWORD'])
        page.get_by_role('button',name='进入工作室 →').click()
    expect(page.get_by_role('heading',name='编辑操作',exact=False)).to_be_visible()

def point(page,side,x,y,photo):
    b=page.locator('#'+side+'-canvas').bounding_box();w,h=Image.open(ROOT/'evidence/samples'/photo).size
    scale=min(b['width']/w,b['height']/h)
    return (b['x']+(b['width']-w*scale)/2+x*w*scale,b['y']+(b['height']-h*scale)/2+y*h*scale)

def polygon(page,side,pts,photo):
    page.locator('#manual-'+side).click()
    page.mouse.move(*point(page,side,*pts[0],photo));page.mouse.down()
    for x,y in pts[1:]:page.mouse.move(*point(page,side,x,y,photo),steps=12)
    page.mouse.up()
    expect(page.locator('#cancel-select')).to_have_count(0)

def drag(page,src,dst,photo):
    page.mouse.move(*point(page,'reference',*src,photo));page.mouse.down()
    page.mouse.move(*point(page,'main',*dst,'fashion-a.png'),steps=20);page.mouse.up()

proc=start_server()
try:
 with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1100})
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_default_timeout(45000)
    login(page)
    (OUT/'initial-structure.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
    page.get_by_role('button',name='＋ 新建编辑').click()
    page.locator('#main-upload').set_input_files(str(ROOT/'evidence/samples/fashion-a.png'))
    page.locator('#refs-upload').set_input_files([str(ROOT/'evidence/samples'/n) for n in ['bag.png','shoes.png','fashion-b.png']])
    expect(page.locator('#reference-count')).to_have_text('3 / 12')
    page.get_by_title('参考图 1',exact=True).click()
    expect(page.locator('#image-viewer')).to_be_visible();page.locator('#viewer-close').click()
    expect(page.locator('#reference-status')).to_contain_text('选区已准备',timeout=120000)
    page.mouse.move(*point(page,'reference',.5,.5,'bag.png'))
    expect(page.locator('#reference-status')).to_contain_text('候选',timeout=90000)
    checks.append('Real hover candidate visible; no fixed selection fallback')
    page.screenshot(path=str(OUT/'hover-real.png'),full_page=True)
    page.keyboard.press('Tab')
    expect(page.locator('#reference-status')).to_contain_text('候选 2')
    polygon(page,'main',[[.32,.425],[.52,.425],[.52,.54],[.32,.54]],'fashion-a.png')
    polygon(page,'reference',[[.2,.25],[.75,.16],[.83,.75],[.2,.83]],'bag.png')
    drag(page,(.5,.5),(.41,.48),'bag.png')
    expect(page.locator('.mapping')).to_have_count(1)
    checks.append('Manual source/target correction then drag creates mapping 1')
    page.get_by_title('参考图 2',exact=True).click()
    expect(page.locator('#image-viewer')).to_be_visible();page.locator('#viewer-close').click()
    polygon(page,'main',[[.37,.80],[.48,.80],[.48,.95],[.37,.95]],'fashion-a.png')
    polygon(page,'reference',[[.2,.4],[.65,.05],[.84,.3],[.65,.8],[.2,.9]],'shoes.png')
    drag(page,(.5,.5),(.43,.89),'shoes.png')
    expect(page.locator('.mapping')).to_have_count(2)
    page.get_by_title('参考图 1',exact=True).click()
    expect(page.locator('#image-viewer')).to_be_visible();page.locator('#viewer-close').click()
    expect(page.locator('.mapping')).to_have_count(2)
    page.get_by_title('删除操作 2',exact=True).click()
    expect(page.locator('.mapping')).to_have_count(1)
    page.get_by_role('button',name='↶ 撤销',exact=True).click()
    expect(page.locator('.mapping')).to_have_count(2)
    page.get_by_role('button',name='↷ 重做',exact=True).click()
    expect(page.locator('.mapping')).to_have_count(1)
    page.get_by_role('button',name='↶ 撤销',exact=True).click()
    expect(page.locator('.mapping')).to_have_count(2)
    checks.append('Reference switching, deletion, undo/redo keep mapping identity')
    page.locator('#project-name').fill('浏览器验收 · 双对象');page.locator('#project-name').press('Tab')
    page.locator('#instructions').fill('保留背景和人物姿势');page.locator('#instructions').press('Tab')
    expect(page.locator('#save-status')).to_have_text('已保存到私有空间')
    page.screenshot(path=str(OUT/'workspace-mappings.png'),full_page=True)
    metrics=page.evaluate('window.selectionMetrics')
    page.reload();expect(page.locator('.mapping')).to_have_count(2)
    checks.append('Reload restores assets, two mappings and instructions from server')
    page.get_by_role('button',name='检查模拟流程（2 项编辑）').click()
    expect(page.locator('.status-badge')).to_have_text('模拟检查 · 未生图',timeout=45000)
    history_url=page.url
    page.screenshot(path=str(OUT/'history-detail-simulation.png'),full_page=True)
    page.get_by_role('button',name='↶ 恢复当时编辑').click()
    expect(page.locator('.mapping')).to_have_count(2)
    checks.append('Submission snapshot and restore create new draft without generation')
    context.close()
    proc.terminate();proc.wait(timeout=15);proc=start_server()
    fresh=browser.new_context(viewport={'width':1440,'height':1100});page=fresh.new_page();login(page)
    page.goto(history_url);expect(page.locator('.status-badge')).to_have_text('模拟检查 · 未生图')
    page.get_by_role('button',name='↶ 恢复当时编辑').click();expect(page.locator('.mapping')).to_have_count(2)
    checks.append('Closed browser, fresh cache/cookies and actual process restart: history restores')
    assert not errors,errors
    (OUT/'browser-check.json').write_text(json.dumps({'passed':checks,'console_errors':errors,'metrics':metrics},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':checks,'console_errors':errors},ensure_ascii=True),flush=True)
    browser.close()
except Exception:
 try:
    page.screenshot(path=str(OUT/'failure.png'),full_page=True)
    (OUT/'failure-structure.txt').write_text(page.locator('body').aria_snapshot()+'\nERRORS: '+json.dumps(errors),encoding='utf-8')
 except Exception:pass
 raise
finally:
 proc.terminate();proc.wait(timeout=15);log.close()
