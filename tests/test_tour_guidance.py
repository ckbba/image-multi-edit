from pathlib import Path


TOUR = Path(__file__).resolve().parents[1] / "前端代码" / "tour.js"


def test_guided_tour_covers_requested_editor_controls_truthfully():
    source = TOUR.read_text(encoding="utf-8")
    expected = {
        "点击无痕改字，修改主图文字": ["圈选多行", "加入编辑", "生成"],
        "填写主体名称": ["文字提示", "不会新建或重新识别选区", "纠正源选区"],
        "按需开启蒙版效果": ["压暗周边", "不是把背景变透明"],
        "悬停查看元素输入": ["实际模型输入", "不会触发识别、保存或生成"],
        "从改字标记返回修改": ["对应主图文字", "只取消这处待生成改字"],
    }
    for title, phrases in expected.items():
        assert f"title:'{title}'" in source
        for phrase in phrases:
            assert phrase in source


def test_optional_mapping_and_text_targets_have_non_mutating_fallbacks():
    source = TOUR.read_text(encoding="utf-8")
    assert "selector:'#mapping-list .mapping-edit-body',fallback:'#mapping-list'" in source
    assert "selector:'#mapping-list .subject-focus-toggle',fallback:'#mapping-list'" in source
    assert "selector:'#composer-editor [data-mapping-preview]',fallback:'#composer-editor'" in source
    assert "selector:'#composer-editor .composer-fragment.text-edit .composer-token',fallback:'#composer-editor'" in source
    assert "function resolve(step){return $(step.selector)||$(step.fallback)||$('#page');}" in source
    assert "fetch(" not in source
    assert "/api/" not in source
