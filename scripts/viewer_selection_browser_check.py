"""Isolated, zero-fee browser regression for enlarged-image selection and toolbar."""
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'output' / 'viewer-selection-check' / 'data'
BASE = 'http://127.0.0.1:8796'
PASSWORD = 'isolated-viewer-check-password'
DATA.mkdir(parents=True, exist_ok=True)
ENV = {**os.environ, 'DATA_DIR': str(DATA), 'SITE_PASSWORD': PASSWORD, 'PORT': '8796', 'GENERATION_MODE': 'simulation', 'SEGMENTATION_MODEL_DIR': str(DATA / 'no-model')}
with (DATA.parent / 'server.log').open('w', encoding='utf-8') as log:
    proc = subprocess.Popen([sys.executable, str(ROOT / 'run.py')], cwd=ROOT, env=ENV, stdout=log, stderr=log)
try:
    for _ in range(100):
        try:
            if httpx.get(BASE + '/api/health', trust_env=False, timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(.1)
    else:
        raise RuntimeError('isolated server did not start')
    with httpx.Client(base_url=BASE, trust_env=False) as client:
        client.post('/api/login', json={'password': PASSWORD}).raise_for_status()
        ids = []
        for color in ('#d4a682', '#69acd2'):
            buf = io.BytesIO(); Image.new('RGB', (640, 480), color).save(buf, 'PNG')
            response = client.post('/api/assets', files={'file': ('fixture.png', buf.getvalue(), 'image/png')})
            response.raise_for_status(); ids.append(response.json()['id'])
        state = client.post('/api/drafts').json()
        state.update(main_image=ids[0], references=[ids[1]])
        client.put('/api/drafts/' + state['id'], json=state).raise_for_status()
        before_jobs = client.get('/api/jobs').json()['count']
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1120, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE)
        page.get_by_role('textbox', name='空间密码').fill(PASSWORD)
        page.get_by_role('button', name='进入工作室 →').click()
        expect(page.locator('#preview-main')).to_be_visible()
        expect(page.locator('#new-draft')).to_have_css('border-top-style', 'dashed')
        expect(page.locator('#attention-mode,#attention-overlay')).to_have_count(0)
        expect(page.locator('#main-canvas')).to_be_visible()

        # A saved manual reference remains actionable inside its enlarged viewer.
        page.locator('#preview-reference').click()
        dialog = page.locator('#image-viewer'); expect(dialog).to_be_visible()
        dialog.locator('#magic-brush').click()
        stage = dialog.locator('.viewer-stage'); box = stage.bounding_box()
        def xy(nx, ny):
            return (box['x'] + box['width'] * nx, box['y'] + box['height'] * ny)
        polygon = [(0.38, 0.38), (0.60, 0.38), (0.60, 0.62), (0.38, 0.62), (0.38, 0.38)]
        page.mouse.move(*xy(*polygon[0])); page.mouse.down()
        for point in polygon[1:]: page.mouse.move(*xy(*point), steps=5)
        page.mouse.up()
        expect(dialog.locator('.magic-status')).to_contain_text('选区已保存')
        expect(dialog.locator('canvas')).to_have_attribute('data-manual-selection', 'true')
        # Clicking inside the new region must not dismiss it or be swallowed by panning.
        page.mouse.click(*xy(0.49, 0.49))
        expect(dialog.locator('canvas')).to_have_attribute('data-manual-selection', 'true')
        # Clicking outside the selected mask cancels only the pending reference region.
        page.mouse.click(*xy(0.70, 0.70))
        expect(dialog.locator('canvas')).to_have_attribute('data-manual-selection', 'false')
        expect(dialog).to_be_visible()
        dialog.locator('#magic-close').click()

        # Main-image brush selection is also cancelable on the same image.
        page.locator('#preview-main').click()
        dialog = page.locator('#image-viewer'); expect(dialog).to_be_visible()
        dialog.locator('#magic-brush').click()
        box = dialog.locator('.viewer-stage').bounding_box()
        page.mouse.move(*xy(*polygon[0])); page.mouse.down()
        for point in polygon[1:]: page.mouse.move(*xy(*point), steps=5)
        page.mouse.up()
        expect(dialog.locator('canvas')).to_have_attribute('data-manual-selection', 'true')
        # Ctrl+B hides, then restores all controls; selected pixels remain visible.
        dialog.locator('canvas').focus()
        page.keyboard.press('Control+b')
        expect(dialog.locator('.magic-tools')).to_be_hidden()
        expect(dialog.locator('canvas')).to_have_attribute('data-manual-selection', 'true')
        page.keyboard.press('Control+b')
        expect(dialog.locator('.magic-tools')).to_be_visible()
        page.mouse.click(*xy(0.70, 0.70))
        expect(dialog.locator('canvas')).to_have_attribute('data-manual-selection', 'false')
        dialog.locator('#magic-close').click()
        # The main canvas uses the same outside-mask cancellation without opening a preview.
        page.locator('#manual-main').click()
        main_canvas = page.locator('#main-canvas'); rect = main_canvas.bounding_box()
        image_rect = page.evaluate("JSON.parse(document.querySelector('#main-canvas').dataset.imageRect)")
        def canvas_xy(nx, ny):
            return (rect['x'] + image_rect['x'] + image_rect['width'] * nx,
                    rect['y'] + image_rect['y'] + image_rect['height'] * ny)
        page.mouse.move(*canvas_xy(0.35, 0.35)); page.mouse.down()
        for point in [(0.55, 0.35), (0.55, 0.55), (0.35, 0.55), (0.35, 0.35)]:
            page.mouse.move(*canvas_xy(*point), steps=5)
        page.mouse.up()
        expect(page.locator('[data-main-transient]')).to_be_visible()
        page.mouse.click(*canvas_xy(0.75, 0.75))
        expect(page.locator('[data-main-transient]')).to_have_count(0)
        expect(page.locator('#image-viewer')).to_have_count(0)
        # A fresh marked region in the enlarged main image can be clicked to edit.
        page.locator('#preview-main').click()
        dialog = page.locator('#image-viewer'); expect(dialog).to_be_visible()
        dialog.locator('#magic-brush').click()
        box = dialog.locator('.viewer-stage').bounding_box()
        page.mouse.move(*xy(*polygon[0])); page.mouse.down()
        for point in polygon[1:]: page.mouse.move(*xy(*point), steps=5)
        page.mouse.up()
        expect(dialog.locator('canvas')).to_have_attribute('data-manual-selection', 'true')
        page.mouse.click(*xy(0.49, 0.49))
        expect(dialog).to_be_visible()
        expect(dialog.locator('#bubble-editor[data-transient]')).to_be_visible()
        dialog.locator('#bubble-editor textarea').fill('更换局部背景颜色')
        dialog.locator('#bubble-editor button').click()
        expect(dialog).to_be_visible()
        expect(dialog.locator('#bubble-editor')).to_have_count(0)
        expect(page.locator('#mapping-list .mapping')).to_have_count(1)
        page.keyboard.press('Escape')
        assert not errors, errors
        browser.close()
    with httpx.Client(base_url=BASE, trust_env=False) as client:
        client.post('/api/login', json={'password': PASSWORD}).raise_for_status()
        assert client.get('/api/jobs').json()['count'] == before_jobs
    print({'main_and_reference_cancel': True, 'toolbar_shortcut': True, 'jobs_created': 0, 'page_errors': []})
finally:
    proc.terminate()
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
