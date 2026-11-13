from collections import Counter
from dataclasses import asdict, dataclass

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
    if set(thresholds) != set(MODELS) or any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not 0 <= value <= 1 for value in thresholds.values()
    ):
        raise ValueError('Provide a threshold in [0, 1] for each of: ' + ', '.join(MODELS))


def decide(predictions, thresholds):
    validate_thresholds(thresholds)
    if set(predictions) != set(MODELS):
        raise ValueError('A result is required from each model; use None for abstention')
    votes = Counter()
    for model, prediction in predictions.items():
        if prediction is None:
            continue
        if (prediction.candidate not in LABELS.values() or not 0 <= prediction.score <= 1
                or (model == 'yolo' and prediction.candidate == 'normal')):
            raise ValueError(f'Invalid prediction from {model}')
        if prediction.score >= thresholds[model]:
            votes[prediction.candidate] += 1

    diseases = {code: count for code, count in votes.items() if code != 'normal'}
    majority = next((code for code, count in diseases.items() if count >= 2), None)
    candidate = None
    if votes['normal'] == 2:
        if predictions['yolo'] is None:
            decision, candidate = 'normal_consensus', 'normal'
        else:
            decision = 'deferred'
    elif majority is not None:
        decision, candidate = 'majority', majority
    elif len(votes) > 1:
        decision = 'deferred'
    elif diseases:
        decision, candidate = 'single_qualified', next(iter(diseases))
    else:
        decision = 'undetermined'

    return {
        'decision': decision,
        'candidate': candidate,
        'votes': dict(votes),
        'thresholds': thresholds,
        'models': {
            model: asdict(prediction) if prediction is not None else None
            for model, prediction in predictions.items()
        },
    }
