"""Six-class adapter checks without loading or deserializing model weights."""
import copy
import unittest
from unittest.mock import Mock

from ensemble.__main__ import Ensemble, parse_yolo_response
from ensemble.policy import Prediction, yolo_top_row
from ensemble.test_policy import yolo_rows


def response(**scores):
    rows = yolo_rows(**scores)
    top = yolo_top_row(rows)
    return {
        'schema_version': '2.0', 'image_id': 'fixture', 'input_role': 'side_closeup',
        'status': 'candidates_for_review' if top else 'undetermined',
        'disease_scores': rows, 'top_candidate': top,
        'score_type': 'uncalibrated_detection_confidence',
        'scores_sum_to_100': False, 'normal_confirmed': False,
    }


class YoloInferenceContractTests(unittest.TestCase):
    def test_normal_uses_common_class_id_three(self):
        prediction, rows = parse_yolo_response(response(normal=.95), 'fixture')
        self.assertEqual(prediction, Prediction('normal', .95))
        self.assertEqual((rows[3]['class_id'], rows[3]['name'], rows[3]['label']), (3, 'normal', '정상'))

    def test_no_detection_is_absent_not_normal(self):
        prediction, rows = parse_yolo_response(response(), 'fixture')
        self.assertIsNone(prediction)
        self.assertTrue(all(not row['detected'] and row['score'] is None for row in rows))

    def test_predict_passes_lower_scoring_disease_metadata_into_policy(self):
        raw = response(normal=.95, acne=.4)
        prediction, rows = parse_yolo_response(raw, 'fixture')
        ensemble = Ensemble.__new__(Ensemble)
        ensemble.thresholds = {'mobilenet': .82, 'resnet50': .85, 'yolo': .70}
        ensemble.predict_models_with_metadata = Mock(return_value=(
            {'mobilenet': Prediction('normal', .99), 'resnet50': Prediction('normal', .99), 'yolo': prediction}, rows))
        result = ensemble.predict(object(), 'fixture', 'side_closeup')
        self.assertEqual((result['decision'], result['candidate']), ('deferred', None))
        self.assertEqual(result['yolo_disease_scores'], raw['disease_scores'])

    def test_schema_role_or_image_mismatch_is_rejected(self):
        for field, value in (('schema_version', '1.0'), ('input_role', 'front'), ('image_id', 'different')):
            raw = response(normal=.9)
            raw[field] = value
            with self.assertRaises(ValueError):
                parse_yolo_response(raw, 'fixture')

    def test_status_or_top_disagreement_is_rejected(self):
        variants = []
        for field, value in (('status', 'undetermined'), ('top_candidate', None)):
            raw = response(normal=.9)
            raw[field] = value
            variants.append(raw)
        raw = response(normal=.9, acne=.8)
        raw['top_candidate'] = raw['disease_scores'][2]
        variants.append(raw)
        for raw in variants:
            with self.assertRaises(ValueError):
                parse_yolo_response(raw, 'fixture')

    def test_invalid_or_partial_six_class_rows_are_rejected(self):
        valid = response(normal=.9)
        for rows in (valid['disease_scores'][:5], [], None):
            raw = copy.deepcopy(valid)
            raw['disease_scores'] = rows
            with self.assertRaises(ValueError):
                parse_yolo_response(raw, 'fixture')

    def test_detector_scores_cannot_claim_confirmed_or_calibrated_diagnosis(self):
        for field, value in (('normal_confirmed', True), ('scores_sum_to_100', True),
                             ('score_type', 'probability')):
            raw = response(normal=.9)
            raw[field] = value
            with self.assertRaises(ValueError):
                parse_yolo_response(raw, 'fixture')

    def test_front_is_unsupported_without_running_models(self):
        ensemble = Ensemble.__new__(Ensemble)
        ensemble.predict_models_with_metadata = Mock(side_effect=AssertionError('Must not infer a front image'))
        result = ensemble.predict(object(), 'fixture', 'front')
        self.assertEqual((result['decision'], result['candidate']), ('unsupported_input', None))
        ensemble.predict_models_with_metadata.assert_not_called()


if __name__ == '__main__':
    unittest.main()
