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
OUT = ROOT / 'output' / 'drive-browser'
DATA = OUT / 'data'
PASSWORD = 'drive-browser-password'
PORT = '8817'
BASE = f'http://127.0.0.1:{PORT}'
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
env = {**os.environ, 'DATA_DIR': str(DATA), 'SITE_PASSWORD': PASSWORD,
       'PORT': PORT, 'GENERATION_MODE': 'simulation'}
log = (OUT / 'server.log').open('w', encoding='utf-8')
server = subprocess.Popen([sys.executable, str(ROOT / 'run.py')], cwd=ROOT, env=env,
                          stdout=log, stderr=log)
checks = {}
try:
    for _ in range(120):
        try:
            if httpx.get(BASE + '/api/health', trust_env=False, timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(.1)
    else:
        raise RuntimeError('isolated drive server did not start')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        errors = []
        page.on('pageerror', lambda e: errors.append(getattr(e, 'stack', None) or str(e)))
        page.goto(BASE + '/drive')
        page.locator('#login input').fill(PASSWORD)
        page.locator('#login button[type=submit]').click()
        expect(page.locator('header nav')).to_contain_text('编辑工作区云盘生成历史')
        expect(page.locator('nav a.active')).to_have_text('云盘')

        page.locator('#drive-new').click()
        page.locator('[data-new-folder]').click()
        page.locator('.drive-dialog input').fill('验收文件夹')
        page.locator('.drive-dialog .drive-primary').click()
        expect(page.locator('.drive-name')).to_contain_text('验收文件夹')
        page.locator('.drive-name').dblclick()
        expect(page.locator('#drive-crumbs')).to_contain_text('验收文件夹')
        page.locator('[data-view=grid]').click()
        expect(page.locator('.drive-empty')).to_be_visible()
        empty = page.evaluate('''() => {const container=document.querySelector('#drive-collection').getBoundingClientRect(), box=document.querySelector('.drive-empty').getBoundingClientRect();return {container:[container.x,container.width],box:[box.x,box.width],overflow:document.documentElement.scrollWidth>innerWidth}}''')
        assert abs(empty['box'][0]+empty['box'][1]/2-(empty['container'][0]+empty['container'][1]/2)) < 2,empty
        assert not empty['overflow'],empty
        checks['empty_centered'] = empty
        page.locator('[data-view=list]').click()

        fixtures = OUT / 'fixtures'; fixtures.mkdir()
        for index, color in enumerate(('red', 'green', 'blue', 'purple')):
            Image.new('RGB', (80 + index, 60), color).save(fixtures / f'pic-{index}.png')
        page.locator('#drive-files').set_input_files([str(p) for p in fixtures.glob('*.png')])
        expect(page.locator('.drive-task')).to_have_count(4)
        expect(page.locator('.drive-task small').filter(has_text='成功')).to_have_count(4, timeout=10000)
        expect(page.locator('.drive-row[data-item]')).to_have_count(4)
        expect(page.locator('#drive-tasks')).to_be_visible()
        page.screenshot(path=str(OUT / 'drive-upload-status.png'), full_page=True)
        used_before = page.locator('#drive-used').inner_text()
        checks['parallel_upload'] = used_before

        folder_fixture = OUT / 'folder-fixture' / 'selected-root'
        (folder_fixture / 'left').mkdir(parents=True)
        (folder_fixture / 'right').mkdir(parents=True)
        (folder_fixture / 'left' / 'same.bin').write_bytes(b'left copy')
        (folder_fixture / 'right' / 'same.bin').write_bytes(b'right copy')
        (folder_fixture / 'readme.txt').write_text('non-image fixture', encoding='utf-8')
        page.locator('#drive-new').click()
        page.locator('[data-folder-upload]').click()
        page.locator('#drive-folder-files').set_input_files(str(folder_fixture))
        expect(page.locator('.drive-task small').filter(has_text='成功')).to_have_count(7, timeout=10000)
        expect(page.locator('.drive-row[data-item]')).to_have_count(5)
        expect(page.locator('.drive-name').filter(has_text='selected-root')).to_have_count(1)
        checks['folder_picker_relative_paths'] = True

        page.locator('[data-view=grid]').click()
        expect(page.locator('.drive-card')).to_have_count(5)
        assert page.locator('.drive-rail').count() == 0
        assert page.locator('.drive-main').bounding_box()['x'] == page.locator('.drive-page').bounding_box()['x']
        checks['no_sidebar_or_left_gutter'] = True
        page.locator('#drive-sort-trigger').click()
        page.locator('[data-sort="name"]').click()
        page.locator('#drive-direction').click()
        checks['grid_and_sort'] = page.locator('.drive-card-main>span:nth-child(2)').all_inner_texts()
        page.screenshot(path=str(OUT / 'drive-grid.png'), full_page=True)
        page.locator('#drive-new').click()
        page.screenshot(path=str(OUT / 'drive-new-menu.png'), full_page=True)
        page.locator('#drive-new').click()

        page.locator('#drive-search').fill('pic-2')
        expect(page.locator('#drive-search-results')).to_contain_text('/验收文件夹')
        page.locator('#drive-search-results [data-search-id]').click()
        expect(page.locator('.cloud-image-preview')).to_be_visible()
        assert page.url.endswith('#p_fid=' + page.locator('.cloud-image-preview .cloud-preview-stage img').get_attribute('src').split('/')[4].split('?')[0])
        page.get_by_role('button', name='关闭预览').click()
        expect(page.locator('.cloud-image-preview')).to_have_count(0)
        page.keyboard.press('Escape')
        page.locator('#drive-search').fill('')
        expect(page.locator('#drive-search-results')).to_contain_text('pic-2')
        checks['search_recent'] = True

        page.locator('[data-view=list]').click()
        page.locator('.drive-row[data-item] input').first.check()
        expect(page.locator('#drive-actions')).to_contain_text('1 个项目已选择')
        page.locator('#drive-actions [data-delete]').click()
        expect(page.locator('.drive-dialog')).to_contain_text('删除项目？')
        page.locator('.drive-dialog .danger-fill').click()
        expect(page.locator('.drive-row[data-item]')).to_have_count(4)
        checks['selection_delete'] = True

        page.locator('a[href="/drive/trash"]').click()
        expect(page.locator('#drive-trash-page')).to_contain_text('将于')
        page.screenshot(path=str(OUT / 'drive-trash.png'), full_page=True)
        page.locator('[data-trash] input').check()
        page.locator('#trash-actions [data-restore]').click()
        page.locator('.drive-dialog .drive-primary').click()
        expect(page.locator('.drive-empty')).to_contain_text('回收站为空')
        checks['trash_restore'] = True

        page.goto(BASE + '/drive')
        expect(page.locator('.drive-name')).to_contain_text('验收文件夹')
        page.locator('.drive-name').dblclick()
        expect(page.locator('.drive-row[data-item]')).to_have_count(5)
        checks['persistence_reload'] = page.locator('#drive-used').inner_text()
        page.screenshot(path=str(OUT / 'drive-list.png'), full_page=True)

        page.locator('.drive-name').filter(has_text='selected-root').dblclick()
        expect(page.locator('.drive-row[data-item]')).to_have_count(3)
        names = page.locator('.drive-name').all_inner_texts()
        assert set(names) == {'left', 'right', 'readme.txt'}, names
        page.locator('.drive-name').filter(has_text='left').dispatch_event('dblclick')
        expect(page.locator('.drive-row[data-item]')).to_have_count(1)
        expect(page.locator('.drive-name').filter(has_text='same.bin')).to_have_count(1)
        page.reload()
        expect(page.locator('.drive-name')).to_contain_text('same.bin')
        checks['nested_tree_reload'] = True

        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(BASE + '/drive')
        checks['narrow_no_overflow'] = page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert checks['narrow_no_overflow']
        page.screenshot(path=str(OUT / 'drive-narrow.png'), full_page=True)

        page.goto(BASE + '/')
        expect(page.locator('.workspace-heading')).to_be_visible()
        page.goto(BASE + '/history')
        expect(page.locator('nav a.active')).to_have_text('生成历史')
        checks['editor_history_regression'] = True
        checks['page_errors'] = errors
        assert not errors, errors
        browser.close()
    (OUT / 'result.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(checks, ensure_ascii=False))
finally:
    server.terminate()
    try:
        server.wait(10)
    except subprocess.TimeoutExpired:
        server.kill()
    log.close()
