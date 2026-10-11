"""Mixed-input interaction acceptance in isolated simulation data.

Exercises preview cross-layer drag, magic-brush transforms, stacked assets,
composer bindings, history, and restore. Never calls a paid provider.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "mixed-input-acceptance"
DATA = OUT / "data"
PORT = int(os.getenv("ACCEPTANCE_PORT", "8792"))
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "mixed-acceptance-password"
OUT.mkdir(parents=True, exist_ok=True)
if DATA.exists():
    shutil.rmtree(DATA)
DATA.mkdir(parents=True)
log = (OUT / "server.log").open("w", encoding="utf-8")
env = os.environ.copy()
env.update(
    DATA_DIR=str(DATA),
    SITE_PASSWORD=PASSWORD,
    GENERATION_MODE="simulation",
    PORT=str(PORT),
    SOURCE_STRATEGY="context-crop",
    SEGMENTATION_MODEL_DIR=str(DATA / "no-model"),
)
proc = subprocess.Popen([sys.executable, str(ROOT / "run.py")], cwd=ROOT, env=env, stdout=log, stderr=log)
result = {"checks": [], "measurements": {}, "console_errors": [], "paid_generation": False, "mock_generation": True}
try:
    for _ in range(150):
        try:
            if json.load(urlopen(BASE + "/api/health"))["ok"]:
                break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("acceptance server not ready")

    with sync_playwright() as pw:
        chrome = next(
            (
                p
                for p in [
                    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
                    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
                    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
                ]
                if p.is_file()
            ),
            None,
        )
        if not chrome:
            raise RuntimeError("local Chrome not found")
        browser = pw.chromium.launch(headless=True, executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        mask_payloads = []
        job_posts = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on(
            "request",
            lambda request: (
                mask_payloads.append(json.loads(request.post_data))
                if request.method == "POST" and request.url.endswith("/api/masks") and request.post_data
                else job_posts.append(request.url)
                if request.method == "POST" and request.url.endswith("/api/jobs")
                else None
            ),
        )
        page.goto(BASE)
        page.locator("input[name=password]").fill(PASSWORD)
        page.locator("#login button").click()
        expect(page.locator("#composer-editor")).to_be_visible()
        ctx = page.context.request

        def sample(name):
            return (ROOT / "evidence" / "samples" / name).read_bytes()

        def upload(name, source):
            return ctx.post(
                BASE + "/api/assets",
                multipart={"file": {"name": name, "mimeType": "image/png", "buffer": sample(source)}},
            ).json()

        main = upload("main-fashion.png", "fashion-a.png")
        ref = upload("reference-fashion.png", "fashion-b.png")
        ref2 = upload("bag.png", "bag.png")
        ref3 = upload("shoes.png", "shoes.png")
        main_mask = ctx.post(BASE + "/api/masks", data={"image_id": main["id"], "points": [[0.2, 0.2], [0.7, 0.2], [0.7, 0.8], [0.2, 0.8]]}).json()
        ref_mask = ctx.post(BASE + "/api/masks", data={"image_id": ref["id"], "points": [[0.15, 0.15], [0.75, 0.15], [0.75, 0.85], [0.15, 0.85]]}).json()
        mapping = {
            "id": "acceptance-mapping",
            "display_index": 1,
            "color": "#8b5cf6",
            "mode": "replace",
            "requirement": "保留衣服纹理",
            "source": {"image_id": ref["id"], "image_version": 1, "mask_id": ref_mask["id"], "anchor": {"x": 0.45, "y": 0.5}, "label": "参考外套"},
            "target": {"image_id": main["id"], "image_version": 1, "mask_id": main_mask["id"], "edit_region_id": main_mask["id"], "anchor": {"x": 0.45, "y": 0.5}},
        }
        draft = ctx.post(BASE + "/api/drafts").json()
        draft.update(
            {
                "name": "混合输入候选验收",
                "main_image": main["id"],
                "references": [ref["id"], ref2["id"], ref3["id"]],
                "mappings": [mapping],
                "next_display_index": 2,
                "full_image_refs": [],
                "instructions": "保持自然光",
            }
        )
        assert ctx.put(BASE + "/api/drafts/" + draft["id"], data=draft).ok
        page.reload()
        expect(page.locator("#mapping-list .mapping")).to_have_count(1)

        # Stacked assets expand on hover and collapse after leaving.
        stack_buttons = page.locator("#composer-assets [data-asset-menu]")
        expect(stack_buttons).to_have_count(4)
        page.mouse.move(20, 20)
        page.wait_for_timeout(300)
        collapsed = stack_buttons.evaluate_all("els => els.map(e => e.getBoundingClientRect().left)")
        page.locator("#composer-assets .asset-stack").hover()
        page.wait_for_timeout(300)
        expanded = stack_buttons.evaluate_all("els => els.map(e => e.getBoundingClientRect().left)")
        page.mouse.move(20, 20)
        page.wait_for_timeout(300)
        recollapsed = stack_buttons.evaluate_all("els => els.map(e => e.getBoundingClientRect().left)")
        assert len(set(round(x) for x in expanded)) == 4
        assert max(expanded) - min(expanded) > 50
        assert max(abs(a - b) for a, b in zip(expanded, recollapsed)) > 10
        result["measurements"]["asset_stack_left"] = {"collapsed": collapsed, "expanded": expanded, "recollapsed": recollapsed}
        result["checks"].append("asset stack expands on hover and collapses on leave")
        page.locator("#composer-assets .asset-stack").hover()
        page.screenshot(path=str(OUT / "asset-stack-expanded.png"), full_page=True)

        # Unified composer binds a dragged element and a whole image in one task.
        page.locator("#composer-editor").click()
        page.keyboard.press("End")
        page.keyboard.type(" @")
        expect(page.locator("#mention-menu")).to_be_visible()
        expect(page.locator("[data-insert-element='acceptance-mapping']")).to_be_visible()
        page.locator("[data-insert-element='acceptance-mapping']").click()
        page.locator("#mention").click()
        page.locator(f"[data-add-whole='{ref['id']}']").click()
        whole_text = page.locator(".composer-fragment.full-image .composer-text")
        assert whole_text.evaluate("e => document.activeElement === e.closest('#composer-editor') && e.contains(getSelection().anchorNode)")
        page.keyboard.type("参考完整背景氛围")
        page.locator(".workspace-heading").click()
        page.wait_for_timeout(800)
        expect(page.locator(".composer-fragment.mapping")).to_have_count(1)
        expect(page.locator(".composer-fragment.full-image")).to_have_count(1)
        expect(page.locator(".composer-fragment.full-image .composer-token")).to_contain_text("整图 · 参考图 1")
        expect(page.locator(".composer-fragment.mapping .composer-token")).to_contain_text("元素 1 · 参考外套")
        expect(page.locator(".composer-fragment.full-image .token-image em")).to_have_text("完整图片")
        expect(page.locator(".composer-fragment.mapping .token-image em")).to_have_text("选区裁剪")
        expect(page.locator("#reference-scope")).to_have_count(0)
        expect(page.locator("#generate")).to_contain_text("参考输入 2 / 12")
        result["checks"].append("one composer contains element and whole-image bindings")
        page.screenshot(path=str(OUT / "mixed-composer.png"), full_page=True)

        # Preview drag: an invalid drop restores the preview and opacity; no operation is added.
        page.locator("#preview-reference").click()
        viewer = page.locator("#image-viewer")
        canvas = viewer.locator("canvas")
        expect(canvas).to_have_attribute("data-regions", "1")
        before_count = page.locator("#mapping-list .mapping").count()
        box = canvas.bounding_box()
        start = (box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.5)
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(20, 100, steps=12)
        assert "drag-fading" in (viewer.get_attribute("class") or "")
        proxy = page.locator("#preview-drag-proxy")
        expect(proxy).to_be_visible()
        fade_opacity = float(viewer.evaluate("e => getComputedStyle(e).opacity"))
        proxy_opacity = float(proxy.evaluate("e => getComputedStyle(e).opacity"))
        page.screenshot(path=str(OUT / "preview-drag-fading.png"))
        page.mouse.up()
        expect(viewer).to_be_visible()
        assert "drag-fading" not in (viewer.get_attribute("class") or "")
        expect(proxy).to_have_count(0)
        assert page.locator("#mapping-list .mapping").count() == before_count
        result["measurements"]["preview_drag_opacity"] = {"viewer": fade_opacity, "proxy": proxy_opacity}
        result["checks"].append("preview drag fades viewer, keeps proxy visible, and invalid drop restores")

        # Valid cross-layer drop reaches the main image, then manual target confirmation creates operation 2.
        main_box = page.locator("#main-canvas").bounding_box()
        target = (main_box["x"] + main_box["width"] * 0.48, main_box["y"] + main_box["height"] * 0.5)
        box = canvas.bounding_box()
        start = (box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.5)
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(*target, steps=18)
        page.mouse.up()
        expect(viewer).to_have_count(0)
        expect(page.locator("#confirm-target")).to_be_visible()
        page.locator("#manual-main").click()
        main_box = page.locator("#main-canvas").bounding_box()
        poly = [(0.36, 0.38), (0.60, 0.38), (0.60, 0.64), (0.36, 0.64)]
        page.mouse.move(main_box["x"] + main_box["width"] * poly[0][0], main_box["y"] + main_box["height"] * poly[0][1])
        page.mouse.down()
        for x, y in poly[1:]:
            page.mouse.move(main_box["x"] + main_box["width"] * x, main_box["y"] + main_box["height"] * y, steps=8)
        page.mouse.up()
        expect(page.locator("#confirm-target")).to_be_visible()
        page.locator("#confirm-target").click()
        expect(page.locator("#duplicate-dialog")).to_be_visible()
        page.get_by_role("button", name="保留两条关系").click()
        expect(page.locator("#mapping-list .mapping")).to_have_count(2)
        result["checks"].append("preview element crosses modal layer and creates operation on main image")

        # Magic brush remains aligned after zoom and pan; posted normalized points equal transformed canvas fractions.
        page.locator("#preview-reference").click()
        canvas = page.locator("#image-viewer canvas")
        expect(canvas).to_be_visible()
        stage = page.locator("#image-viewer .viewer-stage")
        stage_box = stage.bounding_box()
        page.mouse.move(stage_box["x"] + stage_box["width"] / 2, stage_box["y"] + stage_box["height"] / 2)
        page.mouse.wheel(0, -500)
        page.mouse.down()
        page.mouse.move(stage_box["x"] + stage_box["width"] / 2 + 70, stage_box["y"] + stage_box["height"] / 2 + 45, steps=8)
        page.mouse.up()
        page.locator("#magic-brush").click()
        transformed = canvas.bounding_box()
        brush_poly = [(0.28, 0.30), (0.62, 0.30), (0.62, 0.66), (0.28, 0.66)]
        start_index = len(mask_payloads)
        page.mouse.move(transformed["x"] + transformed["width"] * brush_poly[0][0], transformed["y"] + transformed["height"] * brush_poly[0][1])
        page.mouse.down()
        for x, y in brush_poly[1:]:
            page.mouse.move(transformed["x"] + transformed["width"] * x, transformed["y"] + transformed["height"] * y, steps=10)
        page.screenshot(path=str(OUT / "magic-brush-zoom-pan.png"))
        page.mouse.up()
        expect(page.locator("#image-viewer")).to_have_count(0)
        assert len(mask_payloads) == start_index + 1
        posted = mask_payloads[-1]["points"]
        bbox = [min(p[0] for p in posted), min(p[1] for p in posted), max(p[0] for p in posted), max(p[1] for p in posted)]
        expected_bbox = [0.28, 0.30, 0.62, 0.66]
        assert all(abs(a - b) < 0.015 for a, b in zip(bbox, expected_bbox)), (bbox, expected_bbox)
        result["measurements"]["brush_bbox"] = {"posted": bbox, "expected": expected_bbox, "tolerance": 0.015}
        result["checks"].append("magic brush coordinates and save stay aligned after zoom and pan")

        # Submit simulation, verify per-item read-only history and restore consistency.
        page.locator("#generate").click()
        expect(page.locator("#overlap-dialog")).to_be_visible()
        page.locator("#overlap-dialog button[value='proceed']").click()
        expect(page.locator(".status-badge")).to_contain_text("模拟检查", timeout=15000)
        sidebar = page.locator(".detail-sidebar")
        expect(sidebar).to_contain_text("参考外套")
        expect(sidebar).to_contain_text("保留衣服纹理")
        expect(sidebar).to_contain_text("整图 · 参考图 1")
        expect(sidebar).to_contain_text("参考完整背景氛围")
        expect(sidebar).to_contain_text("元素 1 → IMAGE 2")
        expect(sidebar).to_contain_text("整图 IMAGE")
        page.screenshot(path=str(OUT / "mixed-history.png"), full_page=True)
        page.locator("#restore").click()
        expect(page.locator(".composer-fragment.mapping")).to_have_count(2)
        expect(page.locator(".composer-fragment.full-image")).to_have_count(1)
        expect(page.locator(".composer-fragment.full-image .composer-text")).to_have_text("参考完整背景氛围")
        expect(page.locator(".composer-fragment.mapping").first.locator(".composer-text")).to_have_text("保留衣服纹理")
        page.screenshot(path=str(OUT / "mixed-restored.png"), full_page=True)
        result["checks"].append("history shows per-item mixed inputs and restore preserves composer bindings")

        relevant_errors = [error for error in errors if "401 (Unauthorized)" not in error]
        result["console_errors"] = relevant_errors
        result["expected_prelogin_401"] = any("401 (Unauthorized)" in error for error in errors)
        result["job_posts"] = job_posts
        assert not relevant_errors, relevant_errors
        assert len(job_posts) == 1, job_posts
        (OUT / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True), flush=True)
        browser.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    log.close()
