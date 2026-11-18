
from pathlib import Path

import torch
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
)

from src.dataloader_aspect import get_aspect_dataloaders
from src.model import create_model


PROJECT_DIR = Path(__file__).resolve().parent.parent

MODEL_PATH = (
    PROJECT_DIR / "models" / "resnet50_frontal_aspect_best.pth"
)

RESULT_DIR = PROJECT_DIR / "results" / "frontal_aspect_test"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

DEVICE = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)

CLASS_NAMES = [
    "건선",
    "아토피",
    "여드름",
    "정상",
    "주사",
    "지루",
]


def main():

    print("===== ResNet50 Frontal Aspect Ratio 테스트 평가 =====")
    print(f"실행 장치: {DEVICE}")

    # 1. 체크포인트 확인
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"학습된 모델이 없습니다: {MODEL_PATH}"
        )

    # 2. Aspect Ratio 전용 테스트 데이터 로더
    _, _, test_loader = get_aspect_dataloaders()

    print(f"테스트 이미지: {len(test_loader.dataset)}장")

    # 3. 모델 및 체크포인트 불러오기
    checkpoint = torch.load(
        MODEL_PATH,
        map_location=DEVICE,
        weights_only=False,
    )

    if checkpoint.get("class_names") != CLASS_NAMES:
        raise ValueError(
            "체크포인트의 클래스 순서가 평가 코드와 다릅니다."
        )

    if checkpoint.get("input_view") != "frontal_aspect":
        raise ValueError(
            "Aspect Ratio 모델이 아닙니다."
        )

    if "model_state_dict" not in checkpoint:
        raise ValueError(
            "체크포인트에 model_state_dict가 없습니다."
        )

    model = create_model()
    model.load_state_dict(checkpoint["model_state_dict"])

    model = model.to(DEVICE)
    model.eval()

    print(f"학습 Epoch: {checkpoint['epoch']}")
    print(f"Validation Loss: {checkpoint['val_loss']:.4f}")
    print(f"Validation Accuracy: {checkpoint['val_accuracy']:.4f}")

    # 4. 이미지 경로
    image_paths = test_loader.dataset.df["path"].tolist()

    y_true = []
    y_pred = []
    y_prob = []

    # 5. 테스트 데이터 추론
    with torch.no_grad():

        for images, labels in test_loader:

            images = images.to(DEVICE)

            outputs = model(images)

            probabilities = torch.softmax(outputs, dim=1)
            predictions = probabilities.argmax(dim=1)

            y_true.extend(labels.tolist())
            y_pred.extend(predictions.cpu().tolist())
            y_prob.extend(probabilities.cpu().tolist())

    # 6. 데이터 개수 확인
    if not (
        len(image_paths)
        == len(y_true)
        == len(y_pred)
        == len(y_prob)
    ):
        raise ValueError(
            "이미지 경로와 예측 결과의 개수가 일치하지 않습니다."
        )

    # 7. 정확도 계산
    accuracy = accuracy_score(y_true, y_pred)

    error_count = sum(
        actual != predicted
        for actual, predicted in zip(y_true, y_pred)
    )

    print("\n===== 전체 테스트 평가 결과 =====")
    print(f"전체 테스트 이미지: {len(y_true)}장")
    print(f"정상 분류 이미지: {len(y_true) - error_count}장")
    print(f"오분류 이미지: {error_count}장")
    print(f"Test Accuracy: {accuracy * 100:.2f}%")

    # 8. 실제 라벨 및 예측 라벨
    actual_names = [
        CLASS_NAMES[label] for label in y_true
    ]

    predicted_names = [
        CLASS_NAMES[label] for label in y_pred
    ]

    # 9. 클래스별 평가 보고서
    report = classification_report(
        y_true,
        y_pred,
        labels=list(range(len(CLASS_NAMES))),
        target_names=CLASS_NAMES,
        output_dict=True,
        zero_division=0,
    )

    report_df = pd.DataFrame(report).transpose()

    report_path = (
        RESULT_DIR / "aspect_test_classification_report.csv"
    )

    report_df.to_csv(
        report_path,
        encoding="utf-8-sig",
    )

    print("\n===== 클래스별 평가 결과 =====")

    print(
        classification_report(
            y_true,
            y_pred,
            labels=list(range(len(CLASS_NAMES))),
            target_names=CLASS_NAMES,
            zero_division=0,
        )
    )

    # 10. 혼동 행렬
    cm = confusion_matrix(
        y_true,
        y_pred,
        labels=list(range(len(CLASS_NAMES))),
    )

    cm_df = pd.DataFrame(
        cm,
        index=CLASS_NAMES,
        columns=CLASS_NAMES,
    )

    cm_path = (
        RESULT_DIR / "aspect_test_confusion_matrix.csv"
    )

    cm_df.to_csv(
        cm_path,
        encoding="utf-8-sig",
    )

    # 혼동 행렬 이미지
    fig, ax = plt.subplots(figsize=(9, 8))

    display = ConfusionMatrixDisplay(
        confusion_matrix=cm,
        display_labels=CLASS_NAMES,
    )

    display.plot(
        ax=ax,
        cmap="Blues",
        values_format="d",
        xticks_rotation=45,
    )

    ax.set_title("ResNet50 Frontal Aspect Ratio Confusion Matrix")
    ax.set_xlabel("Predicted Label")
    ax.set_ylabel("Actual Label")

    plt.tight_layout()

    cm_image_path = (
        RESULT_DIR / "aspect_test_confusion_matrix.png"
    )

    plt.savefig(
        cm_image_path,
        dpi=300,
        bbox_inches="tight",
    )

    plt.close(fig)

    # 11. 이미지별 예측 결과
    prediction_data = {
        "image_path": image_paths,
        "actual_label": y_true,
        "actual_disease": actual_names,
        "predicted_label": y_pred,
        "predicted_disease": predicted_names,
        "predicted_probability": [
            max(prob) for prob in y_prob
        ],
    }

    for index, class_name in enumerate(CLASS_NAMES):

        prediction_data[f"probability_{class_name}"] = [
            prob[index] for prob in y_prob
        ]

    predictions_df = pd.DataFrame(prediction_data)

    prediction_path = (
        RESULT_DIR / "aspect_test_predictions.csv"
    )

    predictions_df.to_csv(
        prediction_path,
        index=False,
        encoding="utf-8-sig",
    )

    # 12. 오분류 이미지
    misclassified_df = predictions_df[
        predictions_df["actual_label"]
        != predictions_df["predicted_label"]
    ].copy()

    misclassified_path = (
        RESULT_DIR / "aspect_test_misclassified.csv"
    )

    misclassified_df.to_csv(
        misclassified_path,
        index=False,
        encoding="utf-8-sig",
    )

    # 13. 결과 저장 경로
    print("\n===== 평가 결과 저장 완료 =====")
    print(f"분류 보고서: {report_path}")
    print(f"혼동 행렬 CSV: {cm_path}")
    print(f"혼동 행렬 이미지: {cm_image_path}")
    print(f"전체 예측 결과: {prediction_path}")
    print(f"오분류 이미지 목록: {misclassified_path}")


if __name__ == "__main__":
    main()
