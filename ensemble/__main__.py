import argparse
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

from .policy import LABELS, Prediction, decide, validate_thresholds


class Ensemble:
    def __init__(self, mobilenet_root, resnet_root, yolo_root, thresholds):
        validate_thresholds(thresholds)
        self.thresholds = thresholds.copy()
        sys.path.insert(0, str(mobilenet_root / 'scripts'))
        sys.path.insert(0, str(yolo_root / 'src'))
        from inference_core import Predictor
        from backend_inference import DiseasePredictor
        import torch
        from torchvision import models, transforms

        self.mobilenet = Predictor(ckpt=mobilenet_root / 'model/best.pt')
        self.yolo = DiseasePredictor(
            weights=yolo_root / 'models/yolo11_detect/side_hard_negative/weights/best.pt'
        )
        checkpoint = torch.load(
            resnet_root / 'models/resnet50_side_best.pth',
            map_location='cpu', weights_only=True,
        )
        if checkpoint.get('input_view') != 'side' or checkpoint.get('class_names') != list(LABELS):
            raise ValueError('Unexpected ResNet50 checkpoint view or class order')
        self.resnet = models.resnet50(weights=None)
        self.resnet.fc = torch.nn.Linear(self.resnet.fc.in_features, len(LABELS))
        self.resnet.load_state_dict(checkpoint['model_state_dict'])
        self.resnet.eval()
        self.resnet_transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([.485, .456, .406], [.229, .224, .225]),
        ])

    def predict(self, image, image_id, role):
        if role != 'side_closeup':
            return {'image_id': image_id, 'input_role': role,
                    'decision': 'unsupported_input', 'candidate': None}
        predictions = self.predict_models(image, image_id)
        return {'image_id': image_id, 'input_role': role, **decide(predictions, self.thresholds)}

    def predict_models(self, image, image_id):
        import torch

        mobile = self.mobilenet.predict(image, with_cam=False)
        with torch.inference_mode():
            scores = self.resnet(self.resnet_transform(image.convert('RGB')).unsqueeze(0))
            confidence, index = scores.softmax(dim=1)[0].max(dim=0)
        yolo = self.yolo.predict(image, image_id, 'side_closeup')['top_candidate']
        return {
            'mobilenet': Prediction(LABELS[mobile['pred']], mobile['conf']),
            'resnet50': Prediction(tuple(LABELS.values())[index.item()], confidence.item()),
            'yolo': Prediction(yolo['name'], yolo['score']) if yolo is not None else None,
        }


def main():
    parser = argparse.ArgumentParser(description='Run three models on a side close-up image.')
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--role', required=True, choices=('side_closeup', 'front'))
    parser.add_argument('--mobilenet-root', type=Path)
    parser.add_argument('--resnet-root', type=Path)
    parser.add_argument('--yolo-root', type=Path)
    parser.add_argument('--thresholds', type=Path)
    args = parser.parse_args()
    if args.role == 'front':
        result = {'image_id': args.image.name, 'input_role': args.role,
                  'decision': 'unsupported_input', 'candidate': None}
    else:
        if None in (args.mobilenet_root, args.resnet_root, args.yolo_root, args.thresholds):
            parser.error('side_closeup requires all three model roots and --thresholds')
        from PIL import Image

        thresholds = json.loads(args.thresholds.read_text(encoding='utf-8-sig'))
        with redirect_stdout(sys.stderr):
            ensemble = Ensemble(args.mobilenet_root.resolve(), args.resnet_root.resolve(),
                                args.yolo_root.resolve(), thresholds)
            with Image.open(args.image) as image:
                result = ensemble.predict(image, args.image.name, args.role)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
