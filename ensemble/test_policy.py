import unittest

from ensemble.policy import Prediction, decide


class VotingTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
