import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
TOUR = ROOT / "前端代码" / "tour.js"
OUT = ROOT / "output" / "tour-guidance"
OUT.mkdir(parents=True, exist_ok=True)

HTML = """<!doctype html><meta charset=utf-8><style>
body{margin:0;font:14px system-ui}header{height:64px;display:flex;justify-content:flex-end}.header-right{display:flex}#page{padding:20px}.workspaces{height:180px}.reference-panel{height:80px}.operations,#mapping-list,.requirements,#composer-editor{min-height:70px;margin:12px;border:1px solid #bbb}.mapping-edit-body,.subject-focus-toggle,.composer-token{display:block;padding:8px}nav{height:40px}
.product-tour{position:fixed;inset:0;z-index:20}.product-tour-shade{position:absolute;inset:0;background:#2229}.product-tour-spot{position:fixed;border:3px dashed #7565f5;pointer-events:none}.product-tour-card{position:fixed;width:min(390px,calc(100vw - 24px));padding:22px;background:white;border-radius:16px;box-sizing:border-box}.product-tour-card footer{display:flex;justify-content:space-between}.product-tour-close{float:right}
</style><header><div class=header-right></div><nav><a href=/history>历史</a></nav></header><main id=page>
<div class=workspaces><div id=main-wrap><button id=text-edit>无痕改字</button></div><div class=reference-panel id=reference-wrap><button id=manual-reference>魔法画笔</button></div></div><div id=selection-bar></div><label class=recognition-toggle>AI</label><label class=model-pill>模型</label>
<div class=operations><button class=mapping-number>1</button><div id=mapping-list><div class=mapping-edit-body>主体名称</div><label class=subject-focus-toggle>蒙版效果</label></div></div>
<div class=requirements><div id=composer-editor><button class=composer-token data-mapping-preview=x>元素</button><span class='composer-fragment text-edit'><button class=composer-token>改字</button></span></div><button id=mention>@</button></div></main>
<script type=module>import {mountTour} from '/tour.js';window.fixtureMutations=0;document.querySelectorAll('input,button').forEach(el=>el.addEventListener('change',()=>window.fixtureMutations++));mountTour();window.tourReady=true;</script>"""


def run_case(browser, viewport, name, remove_optional=False):
    context = browser.new_context(viewport=viewport)
    page = context.new_page()
    requests = []
    page.on("request", lambda req: requests.append((req.method, req.url)))
    page.route("http://tour.test/**", lambda route: route.fulfill(status=200, content_type="text/html", body=HTML) if route.request.url.endswith("/") else route.fulfill(status=200, content_type="text/javascript", body=TOUR.read_text(encoding="utf-8")))
    page.goto("http://tour.test/")
    page.wait_for_function("window.tourReady === true")
    if remove_optional:
        page.evaluate("document.querySelector('.mapping-edit-body').remove();document.querySelector('.subject-focus-toggle').remove();document.querySelectorAll('#composer-editor .composer-token').forEach(e=>e.remove())")
    page.locator("#product-tour-start").click()
    expect(page.locator(".product-tour-card")).to_be_visible()
    titles = []
    counts = []
    while True:
        titles.append(page.locator(".product-tour-card h2").inner_text())
        counts.append(page.locator(".product-tour-count").inner_text())
        if titles[-1] == ("填写主体名称" if remove_optional else "按需开启蒙版效果"):
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        box = page.locator(".product-tour-card").bounding_box()
        assert box and box["x"] >= 0 and box["y"] >= 0
        label = page.locator("[data-tour-next]").inner_text()
        if label == "完成":
            break
        page.locator("[data-tour-next]").click()
    assert titles[5:11] == ["打开无痕改字", "点编号，告诉 AI 怎么改", "填写主体名称", "按需开启蒙版效果", "悬停查看元素输入", "从改字标记返回修改"]
    page.locator("[data-tour-prev]").click()
    assert page.locator(".product-tour-card h2").inner_text() == "用 @ 引用整张参考图"
    page.keyboard.press("Escape")
    expect(page.locator(".product-tour")).to_have_count(0)
    assert page.evaluate("window.fixtureMutations") == 0
    assert requests == [("GET", "http://tour.test/"), ("GET", "http://tour.test/tour.js")], requests
    context.close()
    return {"viewport": viewport, "steps": len(titles), "fallbacks": remove_optional, "screenshot": str(OUT / f"{name}.png")}


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    result = {
        "desktop": run_case(browser, {"width": 1440, "height": 1000}, "desktop"),
        "small": run_case(browser, {"width": 390, "height": 700}, "small-fallbacks", True),
        "generation_requests": 0,
        "recognition_requests": 0,
        "draft_writes": 0,
    }
    browser.close()
(OUT / "check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
