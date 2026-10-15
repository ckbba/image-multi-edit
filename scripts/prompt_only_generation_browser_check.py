"""Offline browser acceptance for prompt-only main-image generation."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'prompt-only-generation'
DATA = OUT / 'data'
BASE = 'http://127.0.0.1:8798'
PASSWORD = 'prompt-only-offline-password'
PROMPT = '保留原人物姿势、构图和光影，只把整体色调改得更温暖'

if DATA.exists():
    shutil.rmtree(DATA)
OUT.mkdir(parents=True, exist_ok=True)
env = {**os.environ, 'DATA_DIR': str(DATA), 'SITE_PASSWORD': PASSWORD,
       'PORT': '8798', 'GENERATION_MODE': 'simulation'}
log = (OUT / 'server.log').open('w', encoding='utf-8')
server = subprocess.Popen([sys.executable, str(ROOT / 'run.py')], cwd=ROOT, env=env,
                          stdout=log, stderr=log)
try:
    for _ in range(100):
        try:
            if httpx.get(BASE + '/api/health', trust_env=False, timeout=1).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(.1)
    else:
        raise RuntimeError('isolated server did not start')

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE)
        page.get_by_role('textbox', name='空间密码').fill(PASSWORD)
        page.get_by_role('button', name='进入工作室 →').click()
        page.get_by_role('button', name='＋ 新建编辑').click()
        page.locator('#main-upload').set_input_files(str(ROOT / 'evidence' / 'samples' / 'fashion-a.png'))
        editor = page.locator('#composer-editor')
        expect(editor).to_be_visible()
        editor.click()
        page.keyboard.press('Control+A')
        page.keyboard.type(PROMPT)
        page.keyboard.press('Tab')
        generate = page.locator('#generate')
        expect(generate).to_be_enabled()
        expect(generate).to_have_text('检查模拟流程')
        expect(generate).to_have_attribute('title', '实际参考输入 0 / 12；主图和改字不计入')
        expect(page.locator('#save-status')).to_have_text('已保存到私有空间')
        generate.click()
        expect(page.locator('.status-badge')).to_have_text('模拟检查 · 未生图')
        job = page.evaluate("fetch('/api/jobs').then(r=>r.json()).then(x=>x.items[0])")
        detail = page.evaluate("id=>fetch('/api/jobs/'+id).then(r=>r.json())", job['id'])
        compiled = detail['snapshot']['compiled']
        assert detail['result']['calls'] == 0
        assert detail['snapshot']['state']['references'] == []
        assert detail['snapshot']['state']['instructions'] == PROMPT
        assert compiled['inputs'] == [detail['snapshot']['state']['main_image']]
        assert compiled['base_input']['input_index'] == 1
        assert compiled['base_input']['label'] == '主图'
        assert 'IMAGE 1 is the user’s 主图' in compiled['prompt']
        assert PROMPT in compiled['prompt']
        assert errors == [], errors
        screenshot = OUT / 'prompt-only-history.png'
        page.screenshot(path=str(screenshot), full_page=True)
        result = {
            'mode': 'simulation', 'generation_calls': 0, 'status': detail['status'],
            'button_label': '检查模拟流程', 'reference_count': 0,
            'saved_instructions': detail['snapshot']['state']['instructions'],
            'compiled_inputs': compiled['inputs'], 'base_input': compiled['base_input'],
            'compiled_prompt_contains_instruction': PROMPT in compiled['prompt'],
            'compiled_prompt_binds_main_as_image_1': 'IMAGE 1 is the user’s 主图' in compiled['prompt'],
            'console_errors': errors, 'screenshot': str(screenshot)
        }
        (OUT / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        browser.close()
finally:
    server.terminate()
    try:
        server.wait(timeout=15)
    except subprocess.TimeoutExpired:
        server.kill()
    log.close()
