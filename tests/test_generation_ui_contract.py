from pathlib import Path


APP = (Path(__file__).resolve().parents[1] / '前端代码' / 'app.js').read_text(encoding='utf-8')


def test_generate_button_label_has_no_reference_counter():
    assert "'✦ 生成'}（参考输入" not in APP
    assert "'✦ 生成'" in APP


def test_composer_sync_collects_free_text_outside_fragments():
    assert 'composerStandaloneText(editor)' in APP
    assert 'mergeComposerGlobalText' in APP


def test_global_prompt_guidance_names_main_image_without_promising_fidelity():
    assert '主图（IMAGE 1）' in APP
    assert '尽量保留' in APP


def test_waiting_overlay_distinguishes_text_edits_from_image_mappings():
    assert 'textEdits=modifiedTextEdits(snapshot).map' in APP
    assert 'textEditOverlayGeometry(edit)' in APP
    assert 'generation-wait-text' in APP
    assert 'data-region-source="${geometry.source}"' in APP
    assert "textEdits.length?'':'<i class=\"generation-wait-region whole-image\"" in APP


def test_history_comparison_never_reveals_edit_annotations():
    assert 'historyBubbles.hidden=historyTextLayer.hidden=!regionsVisible' in APP
    assert 'if(regionPanel.hidden||Number(regionSelect?.value)!==mainRegionIndex||!historyTextEdits.length)' in APP
    assert 'const geometry=textEditOverlayGeometry(edit)' in APP
    assert 'shape.style.clipPath=geometry.polygon' in APP


def test_history_text_regions_use_distinct_square_number_markers():
    assert "marker.className='history-text-marker'" in APP
    assert "shape.className='history-text-region-shape'" in APP
    assert 'anchor=textEditMarkerAnchor(edit)' in APP


def test_mapping_hover_compares_selected_object_with_truthful_model_input():
    assert '选中的源对象' in APP
    assert '实际模型输入' in APP
    assert 'mapping-comparison-preview' in APP
