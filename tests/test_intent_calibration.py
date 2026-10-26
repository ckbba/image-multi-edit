import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '后端代码'))
import intent_calibration as calibration


def test_candidate_rejects_identity_and_location_changes():
    case = {'bindings': [{'kind':'element','display_index':3,'input_index':2,'target_bbox':[.2,.2,.3,.4]}],
            'prompt':'Operation 3: use IMAGE 2 at target region [.2,.2,.3,.4]. User requirement: person on upper landing.'}
    valid = {'operations':[{'display_index':3,'intent':'place','spatial':'stand on upper landing',
                            'scale':'small distant figure, both feet on tiled landing',
                            'identity':'keep IMAGE 2 identity','confidence':.85,'uncertainty':''}]}
    assert 'IMAGE 2' in calibration.validate_suggestion(case,valid)['operations'][0]['identity']
    invalid = {'operations':[{'display_index':3,'intent':'place','spatial':'move to lower floor',
                              'scale':'giant','identity':'new person from IMAGE 9','confidence':.95,'uncertainty':''}]}
    assert calibration.validate_suggestion(case,invalid)['operations'] == []


def test_candidate_respects_reference_and_size_limits():
    case = {'bindings':[{'kind':'element','display_index':1,'input_index':2,'target_bbox':[.1,.1,.3,.3]}],
            'prompt':'Operation 1: replace flowers on the table using IMAGE 2.'}
    suggestion = {'operations':[{'display_index':1,'intent':'replace','spatial':'same table position',
                                 'scale':'same footprint as replaced bouquet, not larger than cake',
                                 'identity':'IMAGE 2 flowers','confidence':.8,'uncertainty':''},
                                {'display_index':99,'intent':'replace','spatial':'somewhere','scale':'huge',
                                 'identity':'IMAGE 2','confidence':1,'uncertainty':''}]}
    result = calibration.validate_suggestion(case,suggestion)
    assert len(result['operations']) == 1
    assert result['operations'][0]['display_index'] == 1
    assert 'cake' in result['operations'][0]['scale']


def test_low_confidence_suggestion_does_not_modify_prompt():
    case = {'bindings':[{'kind':'element','display_index':1,'input_index':2,'target_bbox':[.1,.1,.3,.3]}],
            'prompt':'Operation 1: place IMAGE 2.'}
    suggestion = {'operations':[{'display_index':1,'intent':'place','spatial':'table',
                                 'scale':'small','identity':'IMAGE 2','confidence':.4,'uncertainty':''}]}
    result = calibration.validate_suggestion(case,suggestion)
    assert result['operations'] == []
    assert calibration.append_calibration(case['prompt'], result) == case['prompt']


def test_uncertainty_and_unbound_child_do_not_become_instructions():
    case = {'bindings':[{'kind':'element','display_index':3,'input_index':2,'target_bbox':[.2,.2,.3,.3]}],
            'prompt':'Operation 3: man from IMAGE 2 holds child from reference 2 on upper landing.'}
    suggestion = {'operations':[{'display_index':3,'intent':'hold child from IMAGE 3',
                                 'spatial':'upper landing','scale':'proportional to stairs',
                                 'identity':'man from IMAGE 2 and child from IMAGE 3',
                                 'confidence':.95,'uncertainty':'child image not bound'}]}
    assert calibration.validate_suggestion(case,suggestion)['operations'] == []


def test_claimed_visual_uncertainty_is_rejected_even_with_high_self_confidence():
    case = {'bindings':[{'kind':'element','display_index':1,'input_index':2,'target_bbox':[.1,.1,.3,.3]}],
            'prompt':'Operation 1: replace flower container with IMAGE 2.'}
    suggestion = {'operations':[{'display_index':1,'intent':'replace','spatial':'table',
                                 'scale':'match target','identity':'IMAGE 2',
                                 'confidence':.95,'uncertainty':'cannot determine target size from the image'}]}
    assert calibration.validate_suggestion(case,suggestion)['operations'] == []
