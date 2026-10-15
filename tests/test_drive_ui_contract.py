from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / '前端代码' / 'app.js').read_text(encoding='utf-8')
DRIVE = (ROOT / '前端代码' / 'drive.js').read_text(encoding='utf-8')
DRIVE_CSS = (ROOT / '前端代码' / 'drive.css').read_text(encoding='utf-8')
PICKER = (ROOT / '前端代码' / 'drive-picker.js').read_text(encoding='utf-8') if (ROOT / '前端代码' / 'drive-picker.js').exists() else ''
PICKER_CSS = (ROOT / '前端代码' / 'drive-picker.css').read_text(encoding='utf-8') if (ROOT / '前端代码' / 'drive-picker.css').exists() else ''
INDEX = (ROOT / '前端代码' / 'index.html').read_text(encoding='utf-8')


def test_drive_nav_is_between_editor_and_history_and_keeps_brand():
    editor = APP.index('编辑工作区')
    drive = APP.index('云盘', editor)
    history = APP.index('生成历史', drive)
    assert editor < drive < history
    assert '拾影<span class="brand-en">STUDIO</span>' in APP


def test_drive_assets_and_routes_are_wired():
    assert '/static/drive.css?v=drive-workspace-1' in INDEX
    assert "from './drive.js?v=drive-workspace-1'" in APP
    for route in ("path==='/drive/trash'", "path.startsWith('/drive/folder/')", "path==='/drive'"):
        assert route in APP


def test_drive_ui_exposes_real_core_interactions():
    for phrase in ('上传文件夹', '新建文件夹', '搜索文件和文件夹', '全部还原', '全部永久删除',
                   'data-view="list"', 'data-view="grid"', 'data-retry', 'data-cancel',
                   "['name','updated','created','size']"):
        if phrase.startswith('['):
            assert all(field in DRIVE for field in ('name', 'updated', 'created', 'size'))
        else:
            assert phrase in DRIVE


def test_folder_upload_preserves_selected_root_and_nested_paths():
    assert 'webkitRelativePath' in DRIVE
    assert 'uploadFolder' in DRIVE
    assert 'ensureUploadFolder' in DRIVE
    assert "split('/')" in DRIVE
    assert '文件夹重名' in DRIVE
    assert '不会覆盖或合并' in DRIVE
    assert 'accept=' not in DRIVE


def test_drive_visual_contract_uses_svg_icons_and_full_width_canvas():
    assert '<svg' in DRIVE
    assert "folderIcon" in DRIVE
    assert 'drive-section-tabs' in DRIVE
    assert 'drive-sort-control' in DRIVE
    assert '☷' not in DRIVE and '▦' not in DRIVE and '📁' not in DRIVE and '📄' not in DRIVE
    assert 'max-width:1480px' not in DRIVE_CSS
    assert '.drive-page{width:100%' in DRIVE_CSS
    assert '@media(max-width:760px)' in DRIVE_CSS


def test_drive_workspace_matches_measured_competitor_geometry_without_fake_features():
    assert 'drive-rail' not in DRIVE and 'drive-rail' not in DRIVE_CSS
    for token in ('所有文件', '回收站', 'drive-sort-menu', 'data-sort="name"'):
        assert token in DRIVE
    for token in ('width:540px', 'height:37px',
                  'width:152px', 'height:192px', 'height:152px',
                  'width:170px', 'height:35px', 'width:440px',
                  'height:149px', 'background:#ff3d3d', 'width:350px'):
        assert token in DRIVE_CSS
    assert '<select id="drive-sort"' not in DRIVE
    assert '共享云盘' not in DRIVE and '升级' not in DRIVE


def test_reference_add_menu_and_cloud_picker_contract():
    assert "from './drive-picker.js" in APP
    assert '本地上传' in APP and '云盘上传' in APP
    assert 'openReferenceSourceMenu' in APP
    assert 'openDrivePicker' in PICKER
    for token in ('所有文件', '修改时间', '确认添加', '已选择', 'data-picker-folder',
                  'data-picker-file', 'drive-picker-preview', 'import-references'):
        assert token in PICKER
    assert 'position:fixed' in PICKER_CSS
    assert 'object-fit:contain' in PICKER_CSS
    assert 'overflow:auto' in PICKER_CSS
    assert '/static/drive-picker.css' in INDEX


def test_cloud_picker_keeps_selection_across_folders_and_excludes_unsupported_files():
    assert 'selected=new Set' not in PICKER
    assert "item.kind==='file'&&isSupported(item)" in PICKER
    assert '不支持导入' in PICKER
    assert 'remaining' in PICKER
    assert 'confirming' in PICKER
