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