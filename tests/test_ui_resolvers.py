from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1] / "前端代码"


def run_core(expression):
    script = f"import * as c from {json.dumps((ROOT / 'core.js').as_uri())}; console.log(JSON.stringify({expression}))"
    result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_saved_text_target_keeps_snapshot_geometry_when_ocr_cache_changes():
    result = run_core("c.textEditViewerTarget({id:'text:main:1:old-line',source:'ocr',original_text:'OLD',replacement:'NEW',bbox:[.1,.2,.4,.3],polygon:[[.1,.2],[.4,.2],[.4,.3]],confidence:.7,needs_review:false},[{id:'new-line',text:'OTHER',bbox:[.7,.7,.9,.9]}])")
    assert result["item"]["bbox"] == [.1, .2, .4, .3]
    assert result["item"]["text"] == "OLD"
    assert result["saved"]["id"] == "text:main:1:old-line"


def test_saved_group_target_uses_cached_lines_but_snapshot_edit_is_canonical():
    result = run_core("c.textEditViewerTarget({id:'text-group:main:1:a+b',source:'ocr-group',original_text:'A\\nB',replacement:'C',bbox:[.1,.1,.8,.4],polygon:[[.1,.1],[.8,.1],[.8,.4]],ocr_line_ids:['a','b']},[{id:'a',text:'fresh A',bbox:[.11,.11,.3,.2]},{id:'b',text:'fresh B',bbox:[.4,.2,.7,.3]}])")
    assert [item["id"] for item in result["group"]["items"]] == ["a", "b"]
    assert result["item"]["bbox"] == [.1, .1, .8, .4]
    assert result["saved"]["replacement"] == "C"


def test_workspace_asset_preview_resolves_all_used_elements_and_unused_raw():
    state = "{main_image:'main',references:['src','unused'],full_image_refs:[{id:'whole',image_id:'src'}],mappings:[{id:'m1',display_index:1,source:{image_id:'src',mask_id:'mask1'}},{id:'m2',display_index:2,source:{image_id:'src',mask_id:'mask2'}},{id:'m3',display_index:3,source:null,target:{image_id:'main',mask_id:'target'}}]}"
    used = run_core(f"c.workspaceAssetPreviewEntries({state},'src')")
    unused = run_core(f"c.workspaceAssetPreviewEntries({state},'unused')")
    main = run_core(f"c.workspaceAssetPreviewEntries({state},'main')")
    assert [(x["kind"], x.get("mappingId")) for x in used] == [('selected-element','m1'),('selected-element','m2'),('whole-image',None)]
    assert unused == [{"kind":"unused-original","assetId":"unused","label":"原素材 · 尚未选元素"}]
    assert [x["kind"] for x in main] == ['main-original','selected-target']


def test_history_asset_preview_uses_frozen_inputs_multiple_crops_and_unused_state():
    state = "{main_image:'main',references:['src','unused'],mappings:[{id:'m1',source:{image_id:'src'}},{id:'m2',source:{image_id:'src'}}],full_image_refs:[]}"
    compiled = "{inputs:['main','crop-a','crop-b'],bindings:[{mapping_id:'m1',original_id:'src',input_index:2,input_asset_id:'crop-a'},{mapping_id:'m2',original_id:'src',input_index:3,input_asset_id:'crop-b'}]}"
    source = run_core(f"c.historyFrozenAssetEntries({state},{compiled},'src')")
    main = run_core(f"c.historyFrozenAssetEntries({state},{compiled},'main')")
    unused = run_core(f"c.historyFrozenAssetEntries({state},{compiled},'unused')")
    assert [(x["assetId"],x["inputIndex"]) for x in source] == [('crop-a',2),('crop-b',3)]
    assert main == [{"kind":"main-input","assetId":"main","inputIndex":1,"label":"主图 · IMAGE 1 · 实际模型输入"}]
    assert unused == [{"kind":"not-sent","assetId":"unused","inputIndex":None,"label":"未发送模型"}]


def test_history_asset_preview_legacy_binding_without_kind_resolves_by_mapping_source():
    state = "{main_image:'main',references:['src'],mappings:[{id:'m1',source:{image_id:'src'}}],full_image_refs:[]}"
    compiled = "{inputs:['main','legacy-crop'],bindings:[{mapping_id:'m1',input_index:2}]}"
    assert run_core(f"c.historyFrozenAssetEntries({state},{compiled},'src')[0].assetId") == 'legacy-crop'


def test_generation_readiness_accepts_each_effective_edit_class_but_not_empty_main():
    assert run_core("c.hasGenerationIntent({main_image:'m',mappings:[],text_edits:[],full_image_refs:[],instructions:'全局要求'})") is True
    assert run_core("c.hasGenerationIntent({main_image:'m',mappings:[],text_edits:[{original_text:'A',replacement:'B'}],full_image_refs:[],instructions:''})") is True
    assert run_core("c.hasGenerationIntent({main_image:'m',mappings:[{id:'local'}],text_edits:[],full_image_refs:[],instructions:''})") is True
    assert run_core("c.hasGenerationIntent({main_image:'m',mappings:[],text_edits:[],full_image_refs:[],instructions:'   '})") is False


def test_standalone_composer_text_is_merged_into_global_instructions():
    result = run_core("c.mergeComposerGlobalText('已有全局要求',['  保留人物姿势  ','','构图和光影'])")
    assert result == '已有全局要求\n保留人物姿势\n构图和光影'
