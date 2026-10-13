import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:8791"
OUT = Path("evidence/text-bubble-toolbar")
OUT.mkdir(parents=True, exist_ok=True)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def login(page):
    assert page.request.post(BASE + "/api/login", data={"password": "demo123"}).ok
    page.goto(BASE, wait_until="networkidle")
    if page.locator('input[name="password"]').count():
        page.locator('input[name="password"]').fill("demo123")
        page.locator('#login button[type="submit"]').click()
    expect(page.locator("#text-edit")).to_be_visible(timeout=15_000)


def open_bubble(page):
    page.locator("#text-edit").click()
    canvas = page.locator("#image-viewer canvas")
    expect(canvas).to_be_visible(timeout=120_000)
    page.wait_for_timeout(400)
    box = canvas.bounding_box()
    page.mouse.move(box["x"] + box["width"] * .09, box["y"] + box["height"] * .09)
    expect(page.locator(".text-tools .magic-status")).to_contain_text("ANNA")
    page.mouse.click(box["x"] + box["width"] * .09, box["y"] + box["height"] * .09)
    expect(page.locator("#text-region-editor")).to_be_visible()
    page.wait_for_timeout(350)
    return canvas


def rect(page, selector):
    return page.locator(selector).evaluate("e=>{const r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}}")


def intersects(a, b):
    return max(a["left"], b["left"]) < min(a["right"], b["right"]) and max(a["top"], b["top"]) < min(a["bottom"], b["bottom"])


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    cases = [
        ("large-150", {"width": 2560, "height": 1247}, 1.5),
        ("normal", {"width": 1440, "height": 1000}, 1),
        ("small", {"width": 1024, "height": 768}, 1),
    ]
    results = {}
    for name, viewport, dpr in cases:
        context = browser.new_context(viewport=viewport, device_scale_factor=dpr)
        page = context.new_page()
        errors = []
        writes = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: writes.append({"method": request.method, "url": request.url}) if request.method not in ("GET", "HEAD", "OPTIONS") and "/api/login" not in request.url and "/text-recognition/" not in request.url else None)
        login(page)
        before_draft = page.request.get(BASE + "/api/drafts/latest").json()
        before_jobs = page.request.get(BASE + "/api/jobs").json()
        canvas = open_bubble(page)
        bubble = rect(page, "#text-region-editor")
        image = rect(page, "#image-viewer canvas")
        toolbar = rect(page, ".text-tools")
        buttons = page.locator(".text-tools button").evaluate_all("els=>els.map(e=>{const r=e.getBoundingClientRect();return {id:e.id,left:r.left,top:r.top,right:r.right,bottom:r.bottom,visible:!!(r.width&&r.height)}})")
        button_overlap = any(intersects(a, b) for i, a in enumerate(buttons) for b in buttons[i+1:] if a["visible"] and b["visible"])
        status = rect(page, ".text-tools .magic-status")
        input_box = rect(page, "#text-region-editor [data-text-original]")
        handle = page.locator("[data-text-bubble-drag]")
        hb = handle.bounding_box()
        old_selection = page.locator("[data-text-original]").evaluate("e=>{e.focus();e.setSelectionRange(1,3);return [e.selectionStart,e.selectionEnd]}")
        page.mouse.move(hb["x"] + 30, hb["y"] + hb["height"] / 2)
        page.mouse.down()
        page.mouse.move(max(20, hb["x"] - 120), max(20, hb["y"] + 75), steps=5)
        page.mouse.up()
        dragged = rect(page, "#text-region-editor")
        new_selection = page.locator("[data-text-original]").evaluate("e=>[e.selectionStart,e.selectionEnd]")
        stored = page.evaluate("JSON.parse(localStorage.getItem('textEditBubblePosition'))")
        page.keyboard.press("Escape")
        expect(page.locator("#text-region-editor")).not_to_be_attached()
        expect(page.locator("#image-viewer")).to_be_visible()
        page.locator("#text-close").click()
        expect(page.locator("#image-viewer")).not_to_be_attached()
        open_bubble(page)
        reopened = rect(page, "#text-region-editor")
        filename = OUT / f"{name}.png"
        if name == "large-150":
            page.screenshot(path=str(filename), clip={"x": 0, "y": 0, "width": 2560, "height": 1246.6666667})
        else:
            page.screenshot(path=str(filename))
        page.keyboard.press("Escape")
        expect(page.locator("#text-region-editor")).not_to_be_attached()
        expect(page.locator("#image-viewer")).to_be_visible()
        after_draft = page.request.get(BASE + "/api/drafts/latest").json()
        after_jobs = page.request.get(BASE + "/api/jobs").json()
        results[name] = {
            "viewport": viewport, "dpr": dpr, "bubble": bubble, "image": image, "toolbar": toolbar,
            "defaultImageIntersection": intersects(bubble, image), "toolbarIntersection": intersects(bubble, toolbar),
            "buttonOverlap": button_overlap, "status": status, "input": input_box,
            "dragChanged": abs(dragged["left"] - bubble["left"]) > 20 or abs(dragged["top"] - bubble["top"]) > 20,
            "inputSelectionBefore": old_selection, "inputSelectionAfter": new_selection,
            "storedPosition": stored, "reopenDelta": [abs(reopened["left"] - dragged["left"]), abs(reopened["top"] - dragged["top"])],
            "draftUnchanged": digest(before_draft) == digest(after_draft), "jobsUnchanged": digest(before_jobs) == digest(after_jobs),
            "writes": writes, "pageErrors": errors, "screenshot": str(filename),
        }
        assert not results[name]["defaultImageIntersection"]
        assert not results[name]["toolbarIntersection"]
        assert not button_overlap
        assert results[name]["dragChanged"]
        assert old_selection == new_selection
        assert max(results[name]["reopenDelta"]) <= 2
        assert results[name]["draftUnchanged"] and results[name]["jobsUnchanged"] and not errors
        context.close()
    (OUT / "acceptance.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))
    browser.close()
