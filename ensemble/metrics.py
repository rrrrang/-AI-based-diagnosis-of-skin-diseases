"""Summarize a completed labeled inference run."""
import argparse
import json
from collections import Counter
from pathlib import Path

from .policy import LABELS, MODELS


def summarize(rows, prediction):
    matrix = {label: Counter() for label in LABELS.values()}
    for row in rows:
        matrix[row['label']][prediction(row) or 'abstain'] += 1
    total = len(rows)
    correct = sum(counts[label] for label, counts in matrix.items())
    abstained = sum(counts['abstain'] for counts in matrix.values())
    normal_count = sum(matrix['normal'].values())
    false_positive = sum(count for code, count in matrix['normal'].items()
                         if code not in ('normal', 'abstain'))
    missed_as_normal = sum(counts['normal'] for label, counts in matrix.items() if label != 'normal')

    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    return {
        'images': total,
        'correct': correct,
        'abstained': abstained,
        'accuracy_all': ratio(correct, total),
        'accuracy_when_returned': ratio(correct, total - abstained),
        'abstention_rate': ratio(abstained, total),
        'normal_false_positive_rate': ratio(false_positive, normal_count),
        'disease_predicted_normal_rate': ratio(missed_as_normal, total - normal_count),
        'per_class_recall': {
            label: ratio(counts[label], sum(counts.values())) for label, counts in matrix.items()
        },
        'confusion_counts': matrix,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('predictions', type=Path)
    parser.add_argument('--expected-count', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.predictions.open(encoding='utf-8') as source:
        rows = [json.loads(line) for line in source]
    if not rows or len(rows) != args.expected_count or len({row['image_id'] for row in rows}) != len(rows):
        parser.error('Inference results are empty, incomplete, or contain duplicate image IDs')

    def single_model(row, model):
        prediction = row['models'][model]
        if prediction and prediction['score'] >= row['thresholds'][model]:
            return prediction['candidate']
        return None

    summary = {
        'thresholds': rows[0]['thresholds'],
        'decisions': Counter(row['decision'] for row in rows),
        'ensemble': summarize(rows, lambda row: row['candidate']),
        'standalone': {model: summarize(rows, lambda row: single_model(row, model)) for model in MODELS},
    }
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(summary, output, ensure_ascii=False, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
