import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:8791"
OUT = Path("evidence/live-ocr-fix")
OUT.mkdir(parents=True, exist_ok=True)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1800, "height": 1125}, device_scale_factor=1)
    page = context.new_page()
    login_response = page.request.post(BASE + "/api/login", data={"password": "demo123"})
    assert login_response.ok
    console = []
    errors = []
    failed = []
    responses = []
    page.on("console", lambda message: console.append({"type": message.type, "text": message.text}))
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("requestfailed", lambda request: failed.append({"url": request.url, "error": request.failure}))
    page.on("response", lambda response: responses.append({"url": response.url, "status": response.status}) if "/text-recognition/" in response.url else None)

    page.goto(BASE, wait_until="networkidle")
    if page.locator('input[name="password"]').count():
        page.locator('input[name="password"]').fill("demo123")
        page.locator('#login button[type="submit"]').click()
        expect(page.locator("#text-edit")).to_be_visible(timeout=15_000)

    before_draft = page.request.get(BASE + "/api/drafts/latest").json()
    before_jobs = page.request.get(BASE + "/api/jobs").json()
    page.locator("#text-edit").click()
    viewer = page.locator("#image-viewer")
    expect(viewer).to_be_visible(timeout=120_000)
    expect(viewer).to_have_class("image-viewer minimal-viewer text-edit-viewer")
    expect(page.locator("#text-select")).to_have_text("选择文字")
    expect(page.locator("#text-brush")).to_be_visible()
    expect(page.locator("#text-fit")).to_be_visible()
    expect(page.locator("#text-close")).to_be_visible()
    canvas = viewer.locator("canvas")
    expect(canvas).to_be_visible(timeout=15_000)
    page.wait_for_timeout(500)

    state = page.evaluate("""() => {
      const dialog=document.querySelector('#image-viewer');
      const canvas=dialog.querySelector('canvas');
      const ctx=canvas.getContext('2d');
      return {
        classes: dialog.className,
        toolbarText: dialog.querySelector('.text-tools')?.innerText,
        hiddenChrome: ['.viewer-head','.viewer-options','.viewer-gallery','.viewer-foot'].map(s=>getComputedStyle(dialog.querySelector(s)).display),
        stageBackground: getComputedStyle(dialog.querySelector('.viewer-stage')).backgroundColor,
        dialogBackground: getComputedStyle(dialog).backgroundColor,
        canvas: {width:canvas.width,height:canvas.height,assetId:canvas.dataset.assetId,scale:canvas.dataset.scale},
        textItemCount: performance.getEntriesByType('resource').filter(e=>e.name.includes('/text-recognition/')).length,
        toolButtons: [...dialog.querySelectorAll('.text-tools button')].map(b=>({id:b.id,text:b.innerText,visible:!!(b.offsetWidth||b.offsetHeight)})),
        viewport: {width:innerWidth,height:innerHeight,devicePixelRatio},
        samplePixel: [...ctx.getImageData(Math.floor(canvas.width/2),Math.floor(canvas.height/2),1,1).data]
      };
    }""")
    page.screenshot(path=str(OUT / "text-viewer-live.png"), full_page=False)

    transform = canvas.evaluate("""canvas => {
      const matrix=new DOMMatrixReadOnly(getComputedStyle(canvas).transform);
      const stage=canvas.parentElement.getBoundingClientRect();
      return {left:stage.left+matrix.m41,top:stage.top+matrix.m42,scale:matrix.a,width:canvas.width,height:canvas.height};
    }""")
    page.mouse.move(transform["left"] + transform["width"] * transform["scale"] * .09,
                    transform["top"] + transform["height"] * transform["scale"] * .09)
    expect(page.locator(".text-tools .magic-status")).to_contain_text("ANNA")
    hover_status = page.locator(".text-tools .magic-status").text_content()

    page.mouse.click(transform["left"] + transform["width"] * transform["scale"] * .09,
                     transform["top"] + transform["height"] * transform["scale"] * .09)
    expect(page.locator("#text-region-editor")).to_be_visible()
    expect(page.locator("#text-region-editor [data-text-original]")).to_have_value("ANNA")
    page.keyboard.press("Escape")
    expect(page.locator("#text-region-editor")).not_to_be_attached()
    expect(viewer).to_be_visible()

    page.locator("#text-brush").click()
    expect(page.locator("#text-brush")).to_have_attribute("aria-pressed", "true")
    brush_status = page.locator(".text-tools .magic-status").text_content()
    start = (transform["left"] + transform["width"] * transform["scale"] * .01,
             transform["top"] + transform["height"] * transform["scale"] * .05)
    end = (transform["left"] + transform["width"] * transform["scale"] * .22,
           transform["top"] + transform["height"] * transform["scale"] * .27)
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(end[0], start[1], steps=6)
    page.mouse.move(*end, steps=6)
    page.mouse.move(start[0], end[1], steps=6)
    page.mouse.move(*start, steps=6)
    page.mouse.up()
    expect(page.locator("#text-region-editor")).to_be_visible()
    expect(page.locator("#text-region-editor b")).to_contain_text("已选")
    grouped_original = page.locator("#text-region-editor [data-text-original]").input_value()
    assert "ANNA" in grouped_original and "KARINA" in grouped_original, grouped_original
    page.screenshot(path=str(OUT / "text-viewer-brush-live.png"), full_page=False)
    page.keyboard.press("Escape")
    expect(page.locator("#text-region-editor")).not_to_be_attached()
    expect(viewer).to_be_visible()
    page.keyboard.press("Escape")
    expect(viewer).to_be_visible()
    expect(page.locator("#text-brush")).to_have_attribute("aria-pressed", "false")
    page.locator("#text-close").click()
    expect(page.locator("#image-viewer")).not_to_be_attached()

    after_draft = page.request.get(BASE + "/api/drafts/latest").json()
    after_jobs = page.request.get(BASE + "/api/jobs").json()
    result = {
        **state,
        "hoverStatus": hover_status,
        "brushStatus": brush_status,
        "groupedOriginal": grouped_original,
        "console": console,
        "pageErrors": errors,
        "requestFailures": failed,
        "ocrResponses": responses,
        "draftUnchanged": digest(before_draft) == digest(after_draft),
        "jobsUnchanged": digest(before_jobs) == digest(after_jobs),
        "screenshots": [str(OUT / "text-viewer-live.png"), str(OUT / "text-viewer-brush-live.png")],
    }
    (OUT / "text-viewer-live.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    browser.close()
