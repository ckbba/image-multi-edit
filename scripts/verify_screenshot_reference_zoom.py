import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8791/"
OUT = Path("D:/image-editor-development/mixed-input-editor/output/reference-zoom-fix")
OUT.mkdir(parents=True, exist_ok=True)


def login(page):
    page.goto(BASE, wait_until="networkidle")
    if page.locator('input[type="password"]').count():
        page.fill('input[type="password"]', "demo123")
        page.click('button:has-text("进入工作室")')
        page.wait_for_selector("#reference-canvas")


def panel_metrics(page):
    return page.eval_on_selector("#reference-canvas", """canvas => {
      const wrap=canvas.parentElement.getBoundingClientRect();
      return {viewport:[innerWidth,innerHeight],wrap:{width:wrap.width,height:wrap.height},source:canvas.dataset.imageSize,rect:JSON.parse(canvas.dataset.imageRect||'null')};
    }""")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe")
    context = browser.new_context(viewport={"width": 1440, "height": 960})
    page = context.new_page()
    writes=[]
    page.on("request", lambda request: writes.append([request.method,request.url]) if request.method in {"PUT","PATCH","DELETE"} or "/generate" in request.url else None)
    page.route("**/api/segmentation/prepare", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"status":"ready","cached":True,"elapsed_ms":0})))
    login(page)
    page.locator("#reference-canvas").evaluate("canvas => new Promise(resolve => { if(canvas.dataset.imageRect) return resolve(); const observer=new MutationObserver(()=>{if(canvas.dataset.imageRect){observer.disconnect();resolve();}}); observer.observe(canvas,{attributes:true,attributeFilter:['data-image-rect']}); })")
    wide = panel_metrics(page)
    page.screenshot(path=str(OUT / "reference-fit-1440x960.png"))
    page.set_viewport_size({"width": 1000, "height": 850})
    page.wait_for_timeout(250)
    narrow = panel_metrics(page)
    page.screenshot(path=str(OUT / "reference-fit-1000x850.png"))
    for item in (wide, narrow):
        assert abs(item["rect"]["y"]) < .01
        assert abs(item["rect"]["height"] - item["wrap"]["height"]) < .05

    # Intercept selection only: no backend selection/model call and no mutation.
    page.click("#preview-reference")
    page.wait_for_selector(".minimal-viewer canvas:not([hidden])")
    asset_id = page.locator(".minimal-viewer canvas").get_attribute("data-asset-id")
    mask_url = f"/api/assets/{asset_id}"
    page.route("**/api/segmentation/select", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"candidates":[{"id":asset_id,"bbox":[0,0,1,1]},{"id":asset_id,"bbox":[0,0,1,1]}],"recognition_cached":True,"label":"包","elapsed_ms":0,"cached":True})))
    canvas = page.locator(".minimal-viewer canvas")
    box = canvas.bounding_box()
    page.mouse.move(box["x"]+box["width"]*.5, box["y"]+box["height"]*.55)
    page.locator(".magic-status").filter(has_text="包").wait_for()
    labelled = page.locator(".magic-status").text_content()
    page.keyboard.press("Tab")
    tabbed = page.locator(".magic-status").text_content()
    page.screenshot(path=str(OUT / "zoom-returned-label.png"))
    page.click("#magic-brush")
    page.mouse.move(box["x"]+120, box["y"]+120)
    cursor = page.eval_on_selector(".magic-cursor", "e=>{const s=getComputedStyle(e),b=e.getBoundingClientRect();return {width:b.width,height:b.height,background:s.backgroundColor,pointerEvents:s.pointerEvents,display:s.display}}")
    page.screenshot(path=str(OUT / "zoom-labelled-small-cursor.png"))
    assert labelled.startswith("包 · 候选 1 / 2")
    assert tabbed.startswith("包 · 候选 2 / 2")
    assert cursor["width"] <= 18 and cursor["height"] <= 18 and cursor["pointerEvents"] == "none"

    page.keyboard.press("Escape")
    page.click("#magic-brush") if page.locator("#magic-brush").count() else None
    page.close()

    # Fresh page, unlabeled response must not invent an object name.
    page = context.new_page(); login(page)
    page.route("**/api/segmentation/select", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"candidates":[{"id":asset_id,"bbox":[0,0,1,1]}],"recognition_cached":False,"elapsed_ms":0,"cached":True})))
    page.click("#preview-reference"); page.wait_for_selector(".minimal-viewer canvas:not([hidden])")
    canvas=page.locator(".minimal-viewer canvas"); box=canvas.bounding_box(); page.mouse.move(box["x"]+box["width"]*.5,box["y"]+box["height"]*.55)
    page.locator(".magic-status").filter(has_text="选区").wait_for()
    unlabeled=page.locator(".magic-status").text_content()
    assert "包" not in unlabeled and "眼镜" not in unlabeled and "已识别元素" not in unlabeled
    assert writes == []
    report={"wide":wide,"narrow":narrow,"labelled":labelled,"tabbed":tabbed,"unlabelled":unlabeled,"cursor":cursor,"requests_stubbed":True,"write_requests":writes,"generation_called":False,"data_mutated":False}
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    browser.close()
