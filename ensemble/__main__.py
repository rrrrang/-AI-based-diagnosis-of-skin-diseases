
import argparse
import json
import sys
from collections.abc import Mapping
from contextlib import redirect_stdout
from pathlib import Path

from .policy import (
    LABELS,
    Prediction,
    decide,
    validate_thresholds,
    validate_yolo_scores,
    yolo_top_row,
)


# YOLO 6클래스 응답 검증
def parse_yolo_response(response, image_id):
    """Reject incompatible detector output before any ensemble vote is counted."""

    if (
        not isinstance(response, Mapping)
        or response.get('schema_version') != '2.0'
        or response.get('image_id') != image_id
        or response.get('input_role') != 'side_closeup'
    ):
        raise ValueError(
            'Expected six-class YOLO schema 2.0 for the requested side/close-up image'
        )

    rows = validate_yolo_scores(response.get('disease_scores'))
    top = yolo_top_row(rows)

    expected_status = (
        'candidates_for_review'
        if top is not None
        else 'undetermined'
    )

    if (
        response.get('status') != expected_status
        or response.get('top_candidate') != top
    ):
        raise ValueError(
            'YOLO response status or top candidate disagrees with the full scores'
        )

    if (
        response.get('score_type') != 'uncalibrated_detection_confidence'
        or response.get('scores_sum_to_100') is not False
        or response.get('normal_confirmed') is not False
    ):
        raise ValueError(
            'YOLO scores must remain uncalibrated candidates, not a confirmed diagnosis'
        )

    return (
        Prediction(top['name'], top['score'])
        if top else None
    ), rows


class Ensemble:
    def __init__(
        self,
        mobilenet_root,
        resnet_root,
        yolo_root,
        thresholds
    ):
        validate_thresholds(thresholds)
        self.thresholds = thresholds.copy()

        sys.path.insert(
            0, str(mobilenet_root / 'scripts')
        )

        sys.path.insert(
            0, str(yolo_root / 'src')
        )

        from inference_core import Predictor
        from backend_inference import DiseasePredictor
        import torch
        from torchvision import models, transforms

        # MobileNetV3 모델
        self.mobilenet = Predictor(
            ckpt=mobilenet_root / 'model/best.pt'
        )

        # YOLO11n 최신 6클래스 모델
        self.yolo = DiseasePredictor(
            weights=yolo_root /
            'models/yolo11_detect/side_six_class_augmented/weights/best.pt'
        )

        # ResNet50 모델
        checkpoint = torch.load(
            resnet_root / 'models/resnet50_side_best.pth',
            map_location='cpu',
            weights_only=True,
        )

        if (
            checkpoint.get('input_view') != 'side'
            or checkpoint.get('class_names') != list(LABELS)
        ):
            raise ValueError(
                'Unexpected ResNet50 checkpoint view or class order'
            )

        self.resnet = models.resnet50(weights=None)

        self.resnet.fc = torch.nn.Linear(
            self.resnet.fc.in_features,
            len(LABELS)
        )

        self.resnet.load_state_dict(
            checkpoint['model_state_dict']
        )

        self.resnet.eval()

        self.resnet_transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(
                [.485, .456, .406],
                [.229, .224, .225]
            ),
        ])

    # 앙상블 분석 결과
    def predict(self, image, image_id, role):

        if role != 'side_closeup':
            return {
                'image_id': image_id,
                'input_role': role,
                'decision': 'unsupported_input',
                'candidate': None
            }

        predictions, yolo_scores, class_scores = (
            self.predict_models_with_metadata(
                image, image_id
            )
        )

        return {
            'image_id': image_id,
            'input_role': role,

            # 최신 YOLO 6클래스 앙상블 판단
            **decide(
                predictions,
                self.thresholds,
                yolo_disease_scores=yolo_scores
            ),

            # 의사 UI 세로 막대그래프 데이터
            'resnetClassScores': class_scores
        }

    # Grad-CAM 마스킹 이미지
    def overlay(self, image):
        """MobileNet이 주목한 부위를 색으로 표시한 그림."""

        return self.mobilenet.predict(
            image, with_cam=True
        )['overlay']

    # 기존 모델별 분석 접근 기능
    def predict_models(self, image, image_id):

        predictions, _, _ = (
            self.predict_models_with_metadata(
                image, image_id
            )
        )

        return predictions

    # 모델별 분석 및 메타데이터 반환
    def predict_models_with_metadata(
        self, image, image_id
    ):
        import torch

        # MobileNetV3 분석
        mobile = self.mobilenet.predict(
            image, with_cam=False
        )

        # ResNet50 분석
        with torch.inference_mode():

            scores = self.resnet(
                self.resnet_transform(
                    image.convert('RGB')
                ).unsqueeze(0)
            )

            # 정상 포함 6개 클래스 전체 예측 점수
            probabilities = scores.softmax(dim=1)[0]

            # 가장 높은 예측 점수
            confidence, index = probabilities.max(dim=0)

            # 질환별 전체 점수 저장
            class_scores = dict(
                zip(
                    LABELS.values(),
                    probabilities.tolist()
                )
            )

        # 최신 YOLO11n 6클래스 분석
        yolo, yolo_scores = parse_yolo_response(
            self.yolo.predict(
                image,
                image_id,
                'side_closeup'
            ),
            image_id
        )

        # 모델별 분석 결과
        return {
            'mobilenet': Prediction(
                LABELS[mobile['pred']],
                mobile['conf']
            ),

            'resnet50': Prediction(
                tuple(LABELS.values())[index.item()],
                confidence.item()
            ),

            'yolo': yolo,

        }, yolo_scores, class_scores


def main():
    parser = argparse.ArgumentParser(
        description='Run three models on a side close-up image.'
    )

    parser.add_argument(
        '--image', required=True, type=Path
    )

    parser.add_argument(
        '--role',
        required=True,
        choices=('side_closeup', 'front')
    )

    parser.add_argument(
        '--mobilenet-root', type=Path
    )

    parser.add_argument(
        '--resnet-root', type=Path
    )

    parser.add_argument(
        '--yolo-root', type=Path
    )

    parser.add_argument(
        '--thresholds', type=Path
    )

    args = parser.parse_args()

    if args.role == 'front':
        result = {
            'image_id': args.image.name,
            'input_role': args.role,
            'decision': 'unsupported_input',
            'candidate': None
        }

    else:
        if None in (
            args.mobilenet_root,
            args.resnet_root,
            args.yolo_root,
            args.thresholds
        ):
            parser.error(
                'side_closeup requires all three model roots and --thresholds'
            )

        from PIL import Image

        thresholds = json.loads(
            args.thresholds.read_text(
                encoding='utf-8-sig'
            )
        )

        with redirect_stdout(sys.stderr):

            ensemble = Ensemble(
                args.mobilenet_root.resolve(),
                args.resnet_root.resolve(),
                args.yolo_root.resolve(),
                thresholds
            )

            with Image.open(args.image) as image:
                result = ensemble.predict(
                    image,
                    args.image.name,
                    args.role
                )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == '__main__':
    main()
