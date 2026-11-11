from pathlib import Path

import pandas as pd
import torch
import matplotlib.pyplot as plt
from torch.utils.data import DataLoader
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
)

from src.dataset import SkinDiseaseDataset
from src.dataloader import ENCODED_DIR
from src.model import create_model

# 프로젝트 경로 및 파일 경로
PROJECT_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_DIR / "data" / "processed" / "encoded" / "frontal_crop_eval.csv"
MODEL_PATH = PROJECT_DIR / "models" / "resnet50_side_best.pth"
RESULT_DIR = PROJECT_DIR / "results"

RESULT_DIR.mkdir(parents=True, exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
BATCH_SIZE = 32

CLASS_NAMES = [
    "건선",
    "아토피",
    "여드름",
    "정상",
    "주사",
    "지루",
]


def main():
    print("===== ResNet50 정면 Crop 평가 =====")
    print(f"실행 장치: {DEVICE}")

    # 파일 확인
    if not CSV_PATH.is_file():
        raise FileNotFoundError(f"정면 평가 CSV를 찾을 수 없습니다: {CSV_PATH}")

    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"학습된 모델을 찾을 수 없습니다: {MODEL_PATH}")

    # 정면 Crop 평가 데이터만 불러오기
    frontal_dataset = SkinDiseaseDataset(CSV_PATH)

    if len(frontal_dataset) == 0:
        raise ValueError("정면 평가 데이터가 비어 있습니다.")

    frontal_loader = DataLoader(
        frontal_dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=0,
    )

    print(f"정면 Crop 평가 이미지: {len(frontal_dataset)}장")
    print("\n질환별 평가 이미지 수:")
    print(frontal_dataset.df["disease"].value_counts().reindex(CLASS_NAMES, fill_value=0))

    # 모델 생성 및 학습된 체크포인트 불러오기
    model = create_model()

    checkpoint = torch.load(MODEL_PATH, map_location=DEVICE)

    # 기존 학습 코드에서 저장한 체크포인트 형식 지원
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]
    else:
        state_dict = checkpoint

    model.load_state_dict(state_dict)
    model = model.to(DEVICE)
    model.eval()

    image_paths = frontal_dataset.df["path"].tolist()

    y_true = []
    y_pred = []
    y_prob = []

    # 정면 이미지 추론
    with torch.no_grad():
        for images, labels in frontal_loader:
            images = images.to(DEVICE)

            outputs = model(images)
            probabilities = torch.softmax(outputs, dim=1)
            predictions = probabilities.argmax(dim=1)

            y_true.extend(labels.tolist())
            y_pred.extend(predictions.cpu().tolist())
            y_prob.extend(probabilities.cpu().tolist())

    if not (len(image_paths) == len(y_true) == len(y_pred) == len(y_prob)):
        raise ValueError("이미지 경로와 예측 결과의 개수가 일치하지 않습니다.")

    # 평가 지표
    accuracy = accuracy_score(y_true, y_pred)

    report = classification_report(
        y_true,
        y_pred,
        labels=list(range(len(CLASS_NAMES))),
        target_names=CLASS_NAMES,
        output_dict=True,
        zero_division=0,
    )
    report_df = pd.DataFrame(report).transpose()

    report_path = RESULT_DIR / "classification_report_resnet50_frontal.csv"
    report_df.to_csv(report_path, encoding="utf-8-sig")

    print("\n===== 정면 Crop 전체 평가 결과 =====")
    print(f"평가 이미지: {len(y_true)}장")
    print(f"Accuracy: {accuracy:.4f} ({accuracy * 100:.2f}%)")
    print("\n===== 질환별 평가 결과 =====")
    print(
        classification_report(
            y_true,
            y_pred,
            labels=list(range(len(CLASS_NAMES))),
            target_names=CLASS_NAMES,
            zero_division=0,
        )
    )

    # 혼동행렬
    cm = confusion_matrix(
        y_true,
        y_pred,
        labels=list(range(len(CLASS_NAMES))),
    )

    cm_df = pd.DataFrame(cm, index=CLASS_NAMES, columns=CLASS_NAMES)
    cm_path = RESULT_DIR / "confusion_matrix_resnet50_frontal.csv"
    cm_df.to_csv(cm_path, encoding="utf-8-sig")

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
    ax.set_title("ResNet50 Frontal Crop Confusion Matrix")
    ax.set_xlabel("Predicted Label")
    ax.set_ylabel("Actual Label")
    plt.tight_layout()

    cm_image_path = RESULT_DIR / "confusion_matrix_resnet50_frontal.png"
    plt.savefig(cm_image_path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    # 이미지별 예측 결과
    actual_names = [CLASS_NAMES[label] for label in y_true]
    predicted_names = [CLASS_NAMES[label] for label in y_pred]

    prediction_data = {
        "image_path": image_paths,
        "actual_label": y_true,
        "actual_disease": actual_names,
        "predicted_label": y_pred,
        "predicted_disease": predicted_names,
        "predicted_probability": [max(prob) for prob in y_prob],
    }

    for index, class_name in enumerate(CLASS_NAMES):
        prediction_data[f"probability_{class_name}"] = [
            prob[index] for prob in y_prob
        ]

    predictions_df = pd.DataFrame(prediction_data)

    prediction_path = RESULT_DIR / "test_predictions_resnet50_frontal.csv"
    predictions_df.to_csv(
        prediction_path,
        index=False,
        encoding="utf-8-sig",
    )

    # 오분류 이미지 목록
    misclassified_df = predictions_df[
        predictions_df["actual_label"] != predictions_df["predicted_label"]
    ].copy()

    misclassified_path = RESULT_DIR / "misclassified_images_resnet50_frontal.csv"
    misclassified_df.to_csv(
        misclassified_path,
        index=False,
        encoding="utf-8-sig",
    )

    error_count = len(misclassified_df)
    error_rate = error_count / len(y_true)

    print("\n===== 오분류 결과 =====")
    print(f"전체 정면 평가 이미지: {len(y_true)}장")
    print(f"정상 분류 이미지: {len(y_true) - error_count}장")
    print(f"오분류 이미지: {error_count}장")
    print(f"오분류율: {error_rate * 100:.2f}%")

    print("\n===== 정면 평가 결과 저장 완료 =====")
    print(f"분류 보고서: {report_path}")
    print(f"혼동행렬 CSV: {cm_path}")
    print(f"혼동행렬 이미지: {cm_image_path}")
    print(f"전체 예측 결과: {prediction_path}")
    print(f"오분류 이미지 목록: {misclassified_path}")


if __name__ == "__main__":
    main()
