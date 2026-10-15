import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'drive-picker-browser'
DATA = OUT / 'data'
PORT = '8823'
BASE = f'http://127.0.0.1:{PORT}'
PASSWORD = 'picker-browser-password'
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
fixtures = OUT / 'fixtures'; fixtures.mkdir()
for name, color in [('root-red.png', 'red'), ('root-blue.png', 'blue'), ('nested-green.png', 'green'), ('local-purple.png', 'purple')]:
    Image.new('RGB', (180, 120), color).save(fixtures / name)
env = {**os.environ, 'DATA_DIR': str(DATA), 'SITE_PASSWORD': PASSWORD, 'PORT': PORT, 'GENERATION_MODE': 'simulation'}
log = (OUT / 'server.log').open('w', encoding='utf-8')
server = subprocess.Popen([sys.executable, str(ROOT / 'run.py')], cwd=ROOT, env=env, stdout=log, stderr=log)
checks = {}
try:
    for _ in range(120):
        try:
            if httpx.get(BASE + '/api/health', trust_env=False, timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(.1)
    with httpx.Client(base_url=BASE, trust_env=False) as client:
        assert client.post('/api/login', json={'password': PASSWORD}).status_code == 200
        folder = client.post('/api/drive/folders', json={'name': '子文件夹'}).json()
        def put(path, mime='image/png', parent=''):
            return client.post('/api/drive/files', data={'parent_id': parent}, files={'file': (path.name, path.read_bytes(), mime)}).json()
        put(fixtures / 'root-red.png'); put(fixtures / 'root-blue.png')
        for index in range(14):
            image = fixtures / f'这是一个用于测试文件名截断与列表滚动的超长图片名称-{index:02d}.png'
            Image.new('RGB', (80, 60), (index * 13 % 255, 80, 160)).save(image)
            put(image)
        put(fixtures / 'nested-green.png', parent=folder['id'])
        client.post('/api/drive/files', files={'file': ('说明.txt', b'not an image', 'text/plain')})
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE + '/?picker-check=2')
        page.locator('#login input').fill(PASSWORD); page.locator('#login button').click()
        expect(page.locator('#reference-add-empty')).to_be_visible()
        before = page.locator('#reference-count').inner_text()
        page.locator('#reference-add-empty').click()
        menu = page.locator('.reference-source-menu')
        expect(menu).to_contain_text('本地上传云盘上传')
        mb, ab = menu.bounding_box(), page.locator('#reference-add-empty').bounding_box()
        assert mb['x'] + mb['width'] <= ab['x'] + 1
        checks['left_menu'] = True
        page.keyboard.press('Escape'); expect(menu).to_have_count(0)

        page.locator('#reference-add-empty').click(); page.locator('[data-cloud]').click()
        expect(page.locator('.drive-picker')).to_be_visible()
        expect(page.locator('.drive-picker-row')).to_have_count(18)
        expect(page.locator('[data-picker-file].unsupported')).to_contain_text('不支持导入')
        page.locator('[data-picker-file]').filter(has_text='root-red.png').hover()
        expect(page.locator('.drive-picker-preview')).to_be_visible()
        geometry = page.evaluate('''() => {const d=document.querySelector('.drive-picker').getBoundingClientRect(),p=document.querySelector('.drive-picker-preview').getBoundingClientRect(),f=document.querySelector('.drive-picker footer').getBoundingClientRect(),m=document.querySelector('.drive-picker main'),name=[...document.querySelectorAll('.drive-picker-row strong')].find(x=>x.textContent.includes('超长图片'));return {dialog:[d.left,d.top,d.right,d.bottom],preview:[p.left,p.top,p.right,p.bottom],footer:[f.left,f.top,f.right,f.bottom],scroll:[m.scrollHeight,m.clientHeight],name:[name.scrollWidth,name.clientWidth]}}''')
        checks['desktop_geometry'] = geometry
        print('desktop geometry', geometry, flush=True)
        assert geometry['preview'][0] >= geometry['dialog'][0] and geometry['preview'][2] <= geometry['dialog'][2]
        assert geometry['preview'][1] >= geometry['dialog'][1] and geometry['preview'][3] <= geometry['footer'][1]
        assert geometry['scroll'][0] > geometry['scroll'][1]
        assert geometry['name'][0] >= geometry['name'][1]
        page.screenshot(path=str(OUT / 'picker-desktop-hover.png'))
        page.locator('[data-picker-file]').filter(has_text='root-red.png').click()
        page.locator('[data-picker-folder]').click()
        expect(page.locator('[data-picker-crumbs]')).to_contain_text('子文件夹')
        expect(page.locator('[data-picker-count]')).to_contain_text('已选择1个')
        page.locator('[data-picker-file]').filter(has_text='nested-green.png').click()
        expect(page.locator('[data-picker-count]')).to_contain_text('已选择2个')
        checks['folder_and_persistent_multiselect'] = True
        page.locator('[data-cancel]').click()
        expect(page.locator('.drive-picker')).to_have_count(0)
        expect(page.locator('#reference-count')).to_have_text(before)
        checks['cancel_no_draft_change'] = True

        page.locator('#reference-add-empty').click(); page.locator('[data-cloud]').click()
        footer_y = page.locator('.drive-picker footer').bounding_box()['y']
        page.locator('.drive-picker main').evaluate('(el)=>el.scrollTop=el.scrollHeight')
        footer_after_scroll = page.locator('.drive-picker footer').bounding_box()
        assert abs(footer_after_scroll['y'] - footer_y) < 1
        checks['sticky_footer_after_scroll'] = True
        page.locator('[data-picker-file]').filter(has_text='root-red.png').click()
        page.locator('[data-picker-folder]').click()
        expect(page.locator('[data-picker-crumbs]')).to_contain_text('子文件夹')
        page.locator('[data-picker-file]').filter(has_text='nested-green.png').click()
        page.locator('[data-confirm]').click()
        expect(page.locator('.drive-picker')).to_have_count(0)
        expect(page.locator('#reference-count')).to_have_text('2 / 12')
        expect(page.locator('#filmstrip .thumb')).to_have_count(2)
        page.wait_for_timeout(900)
        page.reload(); expect(page.locator('#reference-count')).to_have_text('2 / 12')
        checks['confirmed_and_persisted'] = True

        page.locator('#reference-add').click(); page.locator('[data-local]').click()
        page.locator('#refs-upload').set_input_files(str(fixtures / 'local-purple.png'))
        expect(page.locator('#reference-count')).to_have_text('3 / 12')
        checks['local_upload_regression'] = True

        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('#reference-add').click(); page.locator('[data-cloud]').click()
        expect(page.locator('.drive-picker')).to_be_visible()
        expect(page.locator('.drive-picker-row').first).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        narrow = page.evaluate('''() => {const d=document.querySelector('.drive-picker').getBoundingClientRect(),f=document.querySelector('.drive-picker footer').getBoundingClientRect(),row=document.querySelector('.drive-picker-row').getBoundingClientRect();return {dialog:[d.left,d.top,d.right,d.bottom],footer:[f.left,f.top,f.right,f.bottom],row:[row.left,row.right],viewport:[innerWidth,innerHeight]}}''')
        assert narrow['dialog'] == [0, 0, 390, 844]
        assert narrow['footer'][3] <= narrow['viewport'][1] and narrow['row'][1] <= narrow['viewport'][0]
        checks['narrow_geometry'] = narrow
        page.screenshot(path=str(OUT / 'picker-narrow.png'))
        page.keyboard.press('Escape')
        checks['narrow_no_overflow'] = True
        checks['page_errors'] = errors
        assert not errors, errors
        browser.close()
    (OUT / 'result.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(checks, ensure_ascii=False))
finally:
    server.terminate()
    try: server.wait(10)
    except subprocess.TimeoutExpired: server.kill()
    log.close()
