"""Run the three models once per labeled side image and record their decisions."""
import argparse
import csv
import json
import sys
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

from .__main__ import Ensemble
from .policy import LABELS, decide


def discover_images(root):
    for path in sorted(root.rglob('Z4_*.png')):
        folder = path.parent.name.split('_')
        if len(folder) == 3 and folder[0] == 'VS' and folder[1] in LABELS and folder[2] == '측면':
            yield path, LABELS[folder[1]]


def read_manifest(manifest):
    seen_ids = set()
    seen_paths = set()
    with manifest.open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        if not {'image_id', 'path', 'label'}.issubset(reader.fieldnames or ()):
            raise ValueError('Manifest requires image_id,path,label columns')
        for line, row in enumerate(reader, 2):
            image_id = (row['image_id'] or '').strip()
            image_path = (row['path'] or '').strip()
            label = (row['label'] or '').strip()
            path = (manifest.parent / image_path).resolve()
            if (not image_id or not image_path or label not in LABELS.values()
                    or image_id in seen_ids or path in seen_paths or not path.is_file()):
                raise ValueError(f'Invalid or duplicate image entry at manifest line {line}')
            seen_ids.add(image_id)
            seen_paths.add(path)
            yield image_id, path, label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--dataset', type=Path)
    source.add_argument('--manifest', type=Path)
    for name in ('output', 'mobilenet-root', 'resnet-root', 'yolo-root', 'thresholds'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        images = (list(read_manifest(args.manifest)) if args.manifest else
                  [(path.name, path, label) for path, label in discover_images(args.dataset)])
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if not images:
        parser.error('No labeled side images found')
    if len({image_id for image_id, _, _ in images}) != len(images):
        parser.error('Duplicate image IDs in dataset')
    thresholds = json.loads(args.thresholds.read_text(encoding='utf-8-sig'))

    import torch
    from PIL import Image

    torch.set_num_threads(4)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with redirect_stdout(sys.stderr), args.output.open('x', encoding='utf-8') as results:
        ensemble = Ensemble(args.mobilenet_root.resolve(), args.resnet_root.resolve(),
                            args.yolo_root.resolve(), thresholds)
        for index, (image_id, path, label) in enumerate(images, 1):
            with Image.open(path) as image:
                prediction = ensemble.predict_models(image, image_id)
            row = {'image_id': image_id, 'label': label, **decide(prediction, thresholds)}
            results.write(json.dumps(row, ensure_ascii=False) + '\n')
            if index % 25 == 0 or index == len(images):
                results.flush()
                print(f'{index}/{len(images)}', file=sys.stderr, flush=True)
    print(json.dumps({'images': len(images), 'labels': Counter(label for _, _, label in images)}))


if __name__ == '__main__':
    main()
