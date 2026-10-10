"""Isolated real-SlimSAM browser check for transient select recovery."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "playwright"
OUT.mkdir(parents=True, exist_ok=True)
DATA = OUT / "sam-resilience-data"
BASE = "http://127.0.0.1:8792"
MODEL = Path(os.environ["SEGMENTATION_MODEL_DIR"])
ENV = {
    **os.environ,
    "DATA_DIR": str(DATA),
    "SITE_PASSWORD": "sam-resilience-private-password",
    "PORT": "8792",
    "GENERATION_MODE": "simulation",
    "SEGMENTATION_MODEL_DIR": str(MODEL),
    "SEGMENTATION_DEVICE": "cpu",
}
log_path = OUT / "sam-resilience-server.log"
log = log_path.open("w", encoding="utf-8")
process = subprocess.Popen([sys.executable, str(ROOT / "run.py")], cwd=ROOT, env=ENV, stdout=log, stderr=log)

try:
    for _ in range(150):
        try:
            if httpx.get(BASE + "/api/health", trust_env=False, timeout=1).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(.1)
    else:
        raise RuntimeError("isolated server did not become ready")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(180_000)
        page.goto(BASE)
        page.get_by_role("textbox", name="空间密码").fill(ENV["SITE_PASSWORD"])
        page.get_by_role("button", name="进入工作室 →").click()
        expect(page.get_by_role("heading", name="编辑操作", exact=False)).to_be_visible()
        page.get_by_role("button", name="＋ 新建编辑").click()
        page.locator("#refs-upload-empty").set_input_files(str(ROOT / "evidence" / "samples" / "bag.png"))
        expect(page.locator("#reference-status")).to_contain_text("选区已准备", timeout=180_000)

        attempts = []
        def select_route(route):
            attempts.append(time.time())
            if len(attempts) == 1:
                route.fulfill(status=503, content_type="application/json", body='{"detail":"controlled transient restart"}')
            else:
                route.continue_()
        page.route("**/api/segmentation/select", select_route)

        box = page.locator("#reference-canvas").bounding_box()
        width, height = Image.open(ROOT / "evidence" / "samples" / "bag.png").size
        scale = min(box["width"] / width, box["height"] / height)
        x = box["x"] + (box["width"] - width * scale) / 2 + width * scale * .5
        y = box["y"] + (box["height"] - height * scale) / 2 + height * scale * .5
        page.mouse.move(x, y)
        expect(page.locator("#reference-status")).to_contain_text("候选", timeout=180_000)
        status = page.locator("#reference-status").inner_text()
        result = {
            "fixture": "evidence/samples/bag.png",
            "injected_first_select_status": 503,
            "select_attempts": len(attempts),
            "final_status": status,
            "real_model": str(MODEL),
            "server_log": str(log_path.relative_to(ROOT)),
        }
        assert len(attempts) == 2, result
        (OUT / "sam-resilience-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        page.screenshot(path=str(OUT / "sam-resilience-candidate.png"), full_page=True)
        print(json.dumps(result, ensure_ascii=False))
        browser.close()
finally:
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    log.close()
