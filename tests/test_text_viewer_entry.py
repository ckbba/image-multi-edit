from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1] / "前端代码"


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
    assert '>✦ 圈选多行<' in viewer
    assert '>复位<' in viewer
    assert '>关闭 ×<' in viewer
