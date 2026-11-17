"""Portable contract regression checks; no source dataset or GPU is required."""
import math
from pathlib import Path
import pytest
import backend_inference as api


def test_empty_is_undetermined_with_six_null_scores():
    r=api.response_from_scores({},'empty')
    assert r['schema_version']=='2.0' and r['status']=='undetermined'
    assert [x['name'] for x in r['disease_scores']]==list(api.NAMES.values())
    assert all(x['score'] is None and x['detected'] is False for x in r['disease_scores'])
    assert r['top_candidate'] is None and r['normal_confirmed'] is False


def test_normal_is_a_candidate_at_three_and_rosacea_is_four():
    r=api.response_from_scores({'정상':.9,'주사':.7,'지루':.6},'normal')
    assert r['status']=='candidates_for_review'
    assert r['top_candidate']['class_id']==3 and r['top_candidate']['name']=='normal'
    assert r['disease_scores'][4]['name']=='rosacea' and r['disease_scores'][4]['score']==.7
    assert r['disease_scores'][5]['name']=='seborrheic_dermatitis'
    assert r['normal_confirmed'] is False and r['scores_sum_to_100'] is False
    assert math.isclose(sum(x['score'] or 0 for x in r['disease_scores']),2.2)


def test_front_is_unsupported_even_when_scores_are_present():
    r=api.response_from_scores({'정상':.99},'front','front')
    assert r['status']=='unsupported_input' and r['top_candidate'] is None
    assert all(x['score'] is None and not x['detected'] for x in r['disease_scores'])


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-.1,1.1,.1,True])
def test_invalid_scores_rejected(value):
    with pytest.raises(ValueError):api.response_from_scores({'정상':value},'bad')


def test_unknown_classes_rejected():
    with pytest.raises(ValueError):api.response_from_scores({'기타':.9},'bad')


def test_wrong_weights_rejected_before_model_loading(tmp_path):
    wrong=tmp_path/'wrong.pt';wrong.write_bytes(b'not approved six-class checkpoint')
    with pytest.raises(ValueError,match='six-class'):api.DiseasePredictor(wrong)


def test_tie_is_deterministic_and_response_settings_are_copied():
    r=api.response_from_scores({'정상':.8,'건선':.8},'tie')
    assert r['top_candidate']['class_id']==0
    r['inference_settings']['confidence']=.99
    assert api.SETTINGS['confidence']==.25
