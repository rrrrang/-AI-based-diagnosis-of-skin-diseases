import copy
import unittest

from ensemble.policy import LABELS, Prediction, decide


def yolo_rows(**scores):
    return [dict(class_id=index, name=code, label=label, score=scores.get(code), detected=code in scores)
            for index, (label, code) in enumerate(LABELS.items())]


class VotingTests(unittest.TestCase):
    thresholds = dict.fromkeys(('mobilenet', 'resnet50', 'yolo'), .8)

    def vote(self, predictions, rows=None):
        return decide(dict(zip(self.thresholds, predictions)), self.thresholds, yolo_disease_scores=rows)

    def test_rules(self):
        acne = Prediction('acne', .9)
        rosacea = Prediction('rosacea', .9)
        psoriasis = Prediction('psoriasis', .9)
        normal = Prediction('normal', .9)
        weak = Prediction('psoriasis', .3)
        thresholds = dict.fromkeys(('mobilenet', 'resnet50', 'yolo'), .8)
        for predictions, expected in (
            ((acne, acne, rosacea), ('majority', 'acne')),
            ((acne, rosacea, psoriasis), ('deferred', None)),
            ((acne, rosacea, None), ('deferred', None)),
            ((acne, weak, None), ('single_qualified', 'acne')),
            ((weak, None, None), ('undetermined', None)),
            ((normal, normal, None), ('normal_consensus', 'normal')),
            ((normal, normal, weak), ('deferred', None)),
            ((normal, acne, None), ('deferred', None)),
            ((normal, None, None), ('undetermined', None)),
        ):
            with self.subTest(predictions=predictions):
                result = decide(dict(zip(thresholds, predictions)), thresholds)
                self.assertEqual((result['decision'], result['candidate']), expected)

    def test_six_class_normal_requires_consensus_without_retained_disease(self):
        normal = Prediction('normal', .9)
        acne = Prediction('acne', .9)
        for predictions, rows, expected in (
            ((normal, None, normal), yolo_rows(normal=.9), ('normal_consensus', 'normal')),
            ((normal, normal, normal), yolo_rows(normal=.9), ('normal_consensus', 'normal')),
            ((normal, normal, None), yolo_rows(), ('normal_consensus', 'normal')),
            ((normal, acne, normal), yolo_rows(normal=.9), ('deferred', None)),
            ((normal, normal, Prediction('acne', .3)), yolo_rows(acne=.3), ('deferred', None)),
        ):
            with self.subTest(expected=expected, predictions=predictions):
                result = self.vote(predictions, rows)
                self.assertEqual((result['decision'], result['candidate']), expected)

    def test_normal_top_cannot_hide_lower_scoring_yolo_disease(self):
        normal = Prediction('normal', .95)
        for disease_score in (.25, .79, .9):
            rows = yolo_rows(normal=.95, acne=disease_score)
            for other in ((normal, normal), (normal, None), (None, None)):
                with self.subTest(disease_score=disease_score, other=other):
                    result = self.vote((*other, normal), rows)
                    self.assertEqual((result['decision'], result['candidate']), ('deferred', None))
                    self.assertEqual(result['yolo_disease_scores'][2]['score'], disease_score)

    def test_disease_majority_is_preserved_when_yolo_also_detects_normal(self):
        acne = Prediction('acne', .9)
        result = self.vote((acne, acne, Prediction('normal', .95)), yolo_rows(normal=.95, acne=.7))
        self.assertEqual((result['decision'], result['candidate']), ('majority', 'acne'))
        self.assertEqual(result['votes'], {'acne': 2, 'normal': 1})

    def test_single_normal_is_not_a_confirmed_normal_result(self):
        result = self.vote((None, None, Prediction('normal', .95)), yolo_rows(normal=.95))
        self.assertEqual((result['decision'], result['candidate']), ('undetermined', None))

    def test_nonfinite_or_nonnumeric_prediction_and_threshold_rejected(self):
        for invalid in (float('nan'), float('inf'), float('-inf'), True, '0.9', None, -0.1, 1.1):
            with self.subTest(kind=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    self.vote((Prediction('acne', invalid), None, None))
                with self.assertRaises(ValueError):
                    decide(dict.fromkeys(self.thresholds), {**self.thresholds, 'yolo': invalid})

    def test_incomplete_or_inconsistent_class_rows_rejected(self):
        valid = yolo_rows(normal=.9)
        variants = [valid[:-1], [*valid[:-1], valid[0]], {row['name']: row for row in valid}]
        for key, value in (('class_id', 6), ('class_id', True), ('name', 'eczema'), ('label', '임의 라벨'),
                           ('detected', 1), ('score', float('nan')), ('score', True), ('score', .2)):
            changed = copy.deepcopy(valid)
            changed[3][key] = value
            variants.append(changed)
        changed = copy.deepcopy(valid)
        changed[0]['score'] = .5  # An absent class cannot carry a numeric score.
        variants.append(changed)
        for rows in variants:
            with self.assertRaises(ValueError):
                self.vote((None, None, Prediction('normal', .9)), rows)

    def test_top_prediction_must_agree_with_full_scores(self):
        for top, rows in (
            (None, yolo_rows(normal=.9)),
            (Prediction('normal', .9), yolo_rows()),
            (Prediction('normal', .9), yolo_rows(normal=.8)),
            (Prediction('normal', .9), yolo_rows(normal=.9, acne=.95)),
            (Prediction('normal', .9), yolo_rows(normal=.9, acne=.9)),  # Tie selects ID 2.
        ):
            with self.assertRaises(ValueError):
                self.vote((None, None, top), rows)

    def test_complete_scores_are_preserved_as_a_snapshot(self):
        rows = yolo_rows(normal=.95, atopic_dermatitis=.4, acne=.6, rosacea=.5)
        result = self.vote((Prediction('normal', .9), None, Prediction('normal', .95)), rows)
        self.assertEqual(len(result['yolo_disease_scores']), 6)
        self.assertEqual(result['yolo_disease_scores'], rows)
        rows[2]['score'] = .99
        self.assertEqual(result['yolo_disease_scores'][2]['score'], .6)


if __name__ == '__main__':
    unittest.main()
