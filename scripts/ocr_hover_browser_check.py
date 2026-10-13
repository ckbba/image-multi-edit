import json
import time
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:8792'
ROOT = Path(__file__).resolve().parents[1]
IMAGE = Path('C:/Users/Lenovo/AppData/Roaming/Hermes/composer-images/image_242fd5.png')
OUT = ROOT / 'output' / 'playwright'
OUT.mkdir(parents=True, exist_ok=True)


def wait_until(predicate, timeout=120, interval=.25, description='condition'):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:
            last = repr(exc)
        time.sleep(interval)
    raise AssertionError(f'timed out waiting for {description}; last={last!r}')


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    context.on('dialog', lambda dialog: dialog.accept())
    page = context.new_page()
    page.on('dialog', lambda dialog: dialog.accept())
    page.set_default_timeout(120000)
    job_requests, ocr_requests, ocr_results = [], [], {}

    def capture_request(request):
        if request.method == 'POST' and request.url.endswith('/api/jobs'):
            job_requests.append(request.post_data_json)
        if request.method == 'POST' and '/api/text-recognition/' in request.url:
            ocr_requests.append(request.url)

    def capture_response(response):
        if response.request.method == 'POST' and '/api/text-recognition/' in response.url and response.ok:
            ocr_results[response.url.rsplit('/', 1)[-1]] = response.json()

    page.on('request', capture_request)
    page.on('response', capture_response)
    page.goto(BASE)
    page.locator('input[name=password]').fill('ocr-hover-fixture')
    page.locator('#login button[type=submit]').click()
    expect(page.locator('#new-draft')).to_be_visible()
    page.locator('#new-draft').click()
    page.locator('#main-upload-empty').set_input_files(str(IMAGE))
    canvas = page.locator('#main-canvas')
    expect(canvas).to_have_attribute('data-image-size', '1024x1280', timeout=30000)
    image_id = wait_until(lambda: page.request.get(BASE + '/api/drafts/latest').json().get('main_image'), 30, description='uploaded main image id')
    ocr_result = page.request.post(BASE + f'/api/text-recognition/{image_id}').json()

    target = next((item for item in ocr_result['items'] if 'COMING' in item['text'].upper() and 'SOON' in item['text'].upper()), None)
    if target is None:
        raise AssertionError('COMING SOON was not recognized: ' + repr([item['text'] for item in ocr_result['items']]))
    x_norm = (target['bbox'][0] + target['bbox'][2]) / 2
    y_norm = (target['bbox'][1] + target['bbox'][3]) / 2
    rect = json.loads(canvas.get_attribute('data-image-rect'))
    box = canvas.bounding_box()
    x = box['x'] + rect['x'] + rect['width'] * x_norm
    y = box['y'] + rect['y'] + rect['height'] * y_norm

    page.mouse.move(x + 8, y)
    page.mouse.move(x, y)
    highlighted = wait_until(lambda: canvas.get_attribute('data-text-hover'), 10, description='OCR hover highlight')
    page.screenshot(path=str(OUT / 'ocr-main-hover.png'), full_page=True)
    wait_until(lambda: 'Tab' in page.locator('#main-status').text_content(), 180, description='SAM candidates beside OCR text')
    canvas.press('Tab')
    object_status = wait_until(lambda: (value if '物体' in (value := page.locator('#main-status').text_content()) else None), 20,
                               description='Tab switches OCR to SAM object')
    assert not canvas.get_attribute('data-text-hover')
    page.screenshot(path=str(OUT / 'ocr-sam-tab-candidate.png'), full_page=True)
    page.get_by_role('button', name='添加主图局部编辑').click()
    expect(page.locator('#bubble-editor')).to_be_visible()
    for _ in range(12):
        canvas.press('Tab')
        if '文字' in page.locator('#main-status').text_content():
            break
    assert '文字' in page.locator('#main-status').text_content()
    assert canvas.get_attribute('data-text-hover') == highlighted
    expect(page.locator('#bubble-editor')).to_have_count(0)
    page.mouse.click(x, y)
    expect(page.locator('#text-region-editor')).to_be_visible()
    original = page.locator('[data-text-original]').input_value().strip()
    assert 'COMING' in original.upper() and 'SOON' in original.upper()
    page.locator('[data-text-replacement]').fill('IN CINEMAS NOW')
    page.screenshot(path=str(OUT / 'ocr-main-bubble.png'), full_page=True)
    page.get_by_label('确认改字').click()
    expect(page.locator('.composer-fragment.text-edit')).to_have_count(1)
    expect(page.locator('#save-status')).to_have_text('已保存到私有空间', timeout=30000)
    assert job_requests == []

    draft = page.request.get(BASE + '/api/drafts/latest').json()
    assert len(draft['text_edits']) == 1
    assert draft['text_edits'][0]['original_text'] == original
    assert draft['text_edits'][0]['replacement'] == 'IN CINEMAS NOW'
    assert draft['mappings'] == [] and draft['references'] == [] and draft['full_image_refs'] == []
    expect(page.locator('#generate')).to_be_enabled(timeout=30000)
    page.locator('#generate').click()
    wait_until(lambda: len(job_requests) == 1, 30, description='one generation submission')
    wait_until(lambda: '/history/' in page.url, 30, description='history detail navigation')
    job_id = page.url.rstrip('/').split('/')[-1]

    def job_detail():
        value = page.request.get(f'{BASE}/api/jobs/{job_id}').json()
        return value if value['status'] in ('succeeded', 'failed', 'unknown', 'save_failed') else None

    job = wait_until(job_detail, 420, 1, 'terminal generation status')
    if job['status'] != 'succeeded':
        raise AssertionError(f'live generation did not succeed: {job["status"]} {job.get("result")}')
    compiled = job['snapshot']['compiled']
    bindings = compiled['bindings']
    assert len(bindings) == 1 and bindings[0]['kind'] == 'text-edit'
    assert bindings[0]['original_text'] == original
    assert bindings[0]['replacement'] == 'IN CINEMAS NOW'
    assert compiled['inputs'] == [draft['main_image']]
    assert 'ANNA KARINA' not in compiled['prompt'] and 'JEAN-LUC GODARD' not in compiled['prompt']
    assert job['result']['calls'] == 1 and len(job['result']['assets']) == 1

    output_id = job['result']['assets'][0]
    response = page.request.get(f'{BASE}/api/assets/{output_id}?download=true')
    assert response.ok
    output_path = OUT / f'live-text-edit-{job_id}.png'
    output_path.write_bytes(response.body())
    with Image.open(output_path) as generated:
        output_size = generated.size
        assert output_size[0] > 0 and output_size[1] > 0
    expect(page.locator('.status-badge')).to_have_text('已完成', timeout=30000)
    page.screenshot(path=str(OUT / f'live-text-edit-{job_id}-result.png'), full_page=True)

    health_checks = []
    for _ in range(7):
        response = httpx.get(BASE + '/api/health', timeout=5, trust_env=False)
        health_checks.append(response.status_code == 200 and response.json() == {'ok': True})
        time.sleep(10)
    assert all(health_checks)

    result = {
        'job_id': job_id, 'status': job['status'], 'model_calls': job['result']['calls'],
        'request_id': job['result'].get('request_id'), 'elapsed_s': job['result'].get('elapsed_s'),
        'cost_usd': job['result'].get('cost_usd'), 'output_asset_id': output_id,
        'output_path': str(output_path), 'output_size': output_size, 'highlighted_region_id': highlighted,
        'original': original, 'replacement': 'IN CINEMAS NOW', 'ocr_posts': len(ocr_requests),
        'job_posts': len(job_requests), 'bindings': bindings, 'input_count': len(compiled['inputs']),
        'sentinel_absent': True, 'object_status': object_status,
        'health_checks_after_generation': len(health_checks), 'health_window_seconds': 60,
        'screenshots': [str(OUT / 'ocr-main-hover.png'), str(OUT / 'ocr-sam-tab-candidate.png'),
                        str(OUT / 'ocr-main-bubble.png'), str(OUT / f'live-text-edit-{job_id}-result.png')],
    }
    (OUT / 'ocr-hover-live-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    context.close()
    browser.close()
