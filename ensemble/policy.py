from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
import math

MODELS = ('mobilenet', 'resnet50', 'yolo')
LABELS = {
    '건선': 'psoriasis',
    '아토피': 'atopic_dermatitis',
    '여드름': 'acne',
    '정상': 'normal',
    '주사': 'rosacea',
    '지루': 'seborrheic_dermatitis',
}


@dataclass(frozen=True)
class Prediction:
    candidate: str
    score: float


def validate_thresholds(thresholds):
    if not isinstance(thresholds, Mapping) or set(thresholds) != set(MODELS) or any(
        not _valid_score(value) for value in thresholds.values()
    ):
        raise ValueError('Provide a threshold in [0, 1] for each of: ' + ', '.join(MODELS))


def _valid_score(value, minimum=0):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and minimum <= value <= 1 and math.isfinite(value))


def validate_yolo_scores(rows):
    """Validate and copy all six retained-score rows, including normal and absences."""
    if not isinstance(rows, list) or len(rows) != len(LABELS):
        raise ValueError('YOLO metadata must contain all six class rows')
    expected = list(LABELS.items())
    copied = []
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {'class_id', 'name', 'label', 'score', 'detected'}:
            raise ValueError('Unexpected YOLO class-score row')
        class_id = row['class_id']
        if type(class_id) is not int or class_id not in range(len(expected)) or class_id in seen:
            raise ValueError('Unknown or repeated YOLO class ID')
        seen.add(class_id)
        label, code = expected[class_id]
        if row['name'] != code or row['label'] != label or type(row['detected']) is not bool:
            raise ValueError('YOLO class ID, code or label is inconsistent')
        if ((row['detected'] and not _valid_score(row['score'], .25))
                or (not row['detected'] and row['score'] is not None)):
            raise ValueError('Expected retained YOLO confidence in [0.25, 1], or an absent null score')
        copied.append(dict(row))
    return sorted(copied, key=lambda row: row['class_id'])


def yolo_top_row(rows):
    present = [row for row in rows if row['detected']]
    return min(present, key=lambda row: (-row['score'], row['class_id'])) if present else None


def decide(predictions, thresholds, *, yolo_disease_scores=None):
    """Provisional technical voting rule; thresholds require separate model evaluation.

    Real six-class inference must supply the full YOLO rows. None keeps legacy
    synthetic callers compatible, where the supplied YOLO candidate is the
    only available evidence of a retained detection.
    """
    validate_thresholds(thresholds)
    if not isinstance(predictions, Mapping) or set(predictions) != set(MODELS):
        raise ValueError('A result is required from each model; use None for abstention')
    votes = Counter()
    for model, prediction in predictions.items():
        if prediction is None:
            continue
        if (not isinstance(prediction, Prediction) or prediction.candidate not in LABELS.values()
                or not _valid_score(prediction.score)):
            raise ValueError(f'Invalid prediction from {model}')
        if prediction.score >= thresholds[model]:
            votes[prediction.candidate] += 1

    raw_scores = None
    if yolo_disease_scores is not None:
        raw_scores = validate_yolo_scores(yolo_disease_scores)
        top = yolo_top_row(raw_scores)
        yolo = predictions['yolo']
        if ((top is None) != (yolo is None)
                or (top is not None and (yolo.candidate != top['name'] or yolo.score != top['score']))):
            raise ValueError('YOLO top candidate disagrees with its full retained scores')
        raw_yolo_disease = any(row['detected'] and row['name'] != 'normal' for row in raw_scores)
    else:
        raw_yolo_disease = predictions['yolo'] is not None and predictions['yolo'].candidate != 'normal'

    diseases = {code: count for code, count in votes.items() if code != 'normal'}
    majority = next((code for code, count in diseases.items() if count >= 2), None)
    candidate = None
    if majority is not None:
        decision, candidate = 'majority', majority
    elif votes['normal'] >= 2 and not diseases and not raw_yolo_disease:
        decision, candidate = 'normal_consensus', 'normal'
    elif len(votes) > 1 or (votes['normal'] and raw_yolo_disease):
        decision = 'deferred'
    elif diseases:
        decision, candidate = 'single_qualified', next(iter(diseases))
    else:
        decision = 'undetermined'

    return {
        'decision': decision,
        'candidate': candidate,
        'votes': dict(votes),
        'thresholds': dict(thresholds),
        'models': {
            model: asdict(prediction) if prediction is not None else None
            for model, prediction in predictions.items()
        },
        'yolo_disease_scores': raw_scores,
    }
