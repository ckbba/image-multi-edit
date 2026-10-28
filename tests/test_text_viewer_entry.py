from pathlib import Path
import json
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1] / "前端代码"


def run_viewer_module(expression):
    script = f"import * as v from {json.dumps((ROOT / 'viewer.js').as_uri())}; console.log(JSON.stringify({expression}))"
    result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_text_viewer_assets_share_a_cache_busting_release_token():
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    style_token = re.search(r'/static/style\.css\?v=([\w-]+)', index)
    app_token = re.search(r'/static/app\.js\?v=([\w-]+)', index)
    viewer_token = re.search(r"from './viewer\.js\?v=([\w-]+)'", app)
    assert style_token and app_token and viewer_token
    assert style_token.group(1) == app_token.group(1) == viewer_token.group(1)


def test_text_viewer_exposes_requested_floating_tool_labels():
    viewer = (ROOT / "viewer.js").read_text(encoding="utf-8")
    assert '>选择文字<' in viewer
    assert 'aria-hidden="true">✦</i> 圈选多行<' in viewer
    assert '>复位<' in viewer
    assert '>关闭 ×<' in viewer


def test_default_bubble_prefers_right_then_left_outside_rendered_image():
    result = run_viewer_module("[v.defaultTextBubblePosition({width:1440,height:1000},{left:260,top:80,right:1060,bottom:880},{width:300,height:320},{bottom:100}),v.defaultTextBubblePosition({width:1024,height:768},{left:400,top:80,right:930,bottom:680},{width:280,height:300},{bottom:90})]")
    assert result[0]["left"] >= 1072
    assert result[1]["left"] + 280 <= 388


def test_bubble_clamps_away_from_toolbar_and_restores_normalized_position():
    result = run_viewer_module("(()=>{const bounds={width:1024,height:768,bottom:96};const p=v.clampTextBubblePosition({left:990,top:740},{width:300,height:260},bounds);const saved=v.normalizeTextBubblePosition(p,bounds);const restored=v.restoreTextBubblePosition(saved,{width:1440,height:1000,bottom:110},{width:300,height:260});return {p,saved,restored}})()")
    assert result["p"]["left"] == 712
    assert result["p"]["top"] == 400
    assert 0 <= result["saved"]["x"] <= 1 and 0 <= result["saved"]["y"] <= 1
    assert result["restored"]["left"] + 300 <= 1432
    assert result["restored"]["top"] + 260 <= 882


def test_bubble_drag_only_starts_from_handle_not_form_fields():
    viewer = (ROOT / "viewer.js").read_text(encoding="utf-8")
    assert "closest('[data-text-bubble-drag]')" in viewer
    assert "setPointerCapture" in viewer
    assert "textEditBubblePosition" in viewer


def test_saved_text_chip_opens_viewer_with_initial_bubble_and_region_focus():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    viewer = (ROOT / "viewer.js").read_text(encoding="utf-8")
    assert "openTextEditor(state.text_edits.find" in app
    assert "await openTextEditor(null,p.textHover)" in app
    assert "textEditViewerTarget(saved,result.items||[])" in app
    assert "options.textEdit?.initial&&!initialTextOpened" in viewer
    assert "focusTextItem(options.textEdit.initial?.item||textHover)" in viewer
    assert "data-text-bubble-close aria-label=\"关闭改字框\"" in app


def test_saved_text_click_uses_polygon_and_square_marker():
    viewer = (ROOT / "viewer.js").read_text(encoding="utf-8")
    assert "exact=findTextRegion(edits" in viewer
    assert "savedEdit=savedTextAt(pos)" in viewer
    assert "ctx.fillRect(marker.left,marker.top,marker.size,marker.size)" in viewer
