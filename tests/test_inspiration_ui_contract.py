from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / '前端代码' / 'app.js').read_text(encoding='utf-8')
PAGE = (ROOT / '前端代码' / 'inspiration.js').read_text(encoding='utf-8')
CSS = (ROOT / '前端代码' / 'inspiration.css').read_text(encoding='utf-8')
INDEX = (ROOT / '前端代码' / 'index.html').read_text(encoding='utf-8')


def test_inspiration_is_a_first_class_public_route():
    assert "path==='/inspiration'||!currentUser" in APP
    assert 'href="/inspiration"' in APP
    assert '>灵感</a>' in APP
    assert "from './inspiration.js?v=3'" in APP


def test_feed_has_real_favorite_and_workspace_actions():
    for token in ('data-favorite', 'data-workspace', 'data-drive', '/workspace', '/favorite', '/drive'):
        assert token in PAGE
    assert '添加到工作区' in PAGE
    assert '已收藏到云盘' in PAGE


def test_workspace_action_selects_the_added_inspiration_reference():
    assert 'deps.setEditorState(result.draft,result.asset.id)' in PAGE
    assert 'if(state.references.includes(selectedReference))currentRef=selectedReference' in APP


def test_auth_dialog_close_bypasses_validation_and_cancels_pending_action():
    assert 'class="auth-close" type="button" aria-label="关闭"' in APP
    assert "dialog.querySelector('.auth-close').onclick=()=>{pendingAuthAction=null;dialog.close('cancel');}" in APP
    assert "dialog.addEventListener('cancel',()=>{pendingAuthAction=null;});" in APP
    assert '/static/app.js?v=accounts-5' in INDEX


def test_masonry_and_mobile_layout_are_wired():
    assert '/static/inspiration.css?v=6' in INDEX
    assert 'columns:4 240px' in CSS
    assert '@media(max-width:760px)' in CSS
    assert 'columns:2 145px' in CSS


def test_category_tabs_stay_inside_the_page_container():
    assert 'max-width:100%;min-width:0;height:auto;flex-wrap:wrap' in CSS
    assert 'top:var(--inspiration-header-height' in CSS
    assert 'border-bottom:1px solid #e7e4eb' in CSS
    assert '.inspiration-tabs button.active::after{content:none}' in CSS
    assert 'flex-wrap:nowrap;justify-content:flex-start;overflow-x:auto;overflow-y:hidden' in CSS
    assert '.inspiration-tabs::-webkit-scrollbar{display:none}' in CSS
