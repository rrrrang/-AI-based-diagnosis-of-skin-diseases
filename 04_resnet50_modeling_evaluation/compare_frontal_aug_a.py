
from pathlib import Path

import pandas as pd
import torch

from torch.utils.data import DataLoader
from torchvision import transforms

from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

from src.dataset import SkinDiseaseDataset
from src.model import create_model


# ==========================================
# 1. 경로 및 기본 설정
# ==========================================

PROJECT_DIR = Path(__file__).resolve().parent.parent

CSV_PATH = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "encoded"
    / "frontal_test_grouped.csv"
)

CROP_MODEL_PATH = (
    PROJECT_DIR
    / "models"
    / "resnet50_frontal_crop_best.pth"
)

AUG_A_MODEL_PATH = (
    PROJECT_DIR
    / "models"
    / "resnet50_frontal_aug_a_best.pth"
)

RESULT_DIR = (
    PROJECT_DIR
    / "results"
    / "frontal_aug_a_comparison"
)

RESULT_DIR.mkdir(parents=True, exist_ok=True)

DEVICE = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)

BATCH_SIZE = 32

CLASS_NAMES = [
    "건선",
    "아토피",
    "여드름",
    "정상",
    "주사",
    "지루",
]


# ==========================================
# 2. 평가 전처리
# ==========================================

eval_transform = transforms.Compose([
    transforms.Resize((224, 224)),

    transforms.ToTensor(),

    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
    ),
])


# ==========================================
# 3. 체크포인트 불러오기
# ==========================================

def load_checkpoint(model_path, expected_view):

    if not model_path.is_file():
        raise FileNotFoundError(
            f"체크포인트를 찾을 수 없습니다: {model_path}"
        )

    checkpoint = torch.load(
        model_path,
        map_location=DEVICE,
        weights_only=False,
    )

    if "model_state_dict" not in checkpoint:
        raise ValueError(
            f"모델 가중치가 없습니다: {model_path}"
        )

    if checkpoint.get("class_names") != CLASS_NAMES:
        raise ValueError(
            f"클래스 순서가 일치하지 않습니다: {model_path}"
        )

    if checkpoint.get("input_view") != expected_view:
        raise ValueError(
            f"모델 입력 유형이 일치하지 않습니다: {model_path}"
        )

    model = create_model()

    model.load_state_dict(
        checkpoint["model_state_dict"]
    )

    model = model.to(DEVICE)
    model.eval()

    return model, checkpoint


# ==========================================
# 4. 모델 평가
# ==========================================

def evaluate_model(model, dataloader, dataset, model_name):

    print(f"\n===== {model_name} 평가 시작 =====")

    y_true = []
    y_pred = []
    y_prob = []

    with torch.no_grad():

        for images, labels in dataloader:

            images = images.to(DEVICE)

            outputs = model(images)

            probabilities = torch.softmax(
                outputs,
                dim=1,
            )

            predictions = probabilities.argmax(dim=1)

            y_true.extend(labels.tolist())
            y_pred.extend(predictions.cpu().tolist())
            y_prob.extend(probabilities.cpu().tolist())

    image_paths = dataset.df["path"].tolist()

    if not (
        len(image_paths)
        == len(y_true)
        == len(y_pred)
        == len(y_prob)
    ):
        raise ValueError(
            f"{model_name}: 이미지와 예측 결과 개수가 다릅니다."
        )

    accuracy = accuracy_score(y_true, y_pred)

    report = classification_report(
        y_true,
        y_pred,
        labels=list(range(len(CLASS_NAMES))),
        target_names=CLASS_NAMES,
        output_dict=True,
        zero_division=0,
    )

    cm = confusion_matrix(
        y_true,
        y_pred,
        labels=list(range(len(CLASS_NAMES))),
    )

    error_count = sum(
        actual != predicted
        for actual, predicted in zip(y_true, y_pred)
    )

    print(f"평가 이미지: {len(y_true)}장")
    print(f"Accuracy: {accuracy:.4f} ({accuracy * 100:.2f}%)")
    print(f"오분류: {error_count}장")
    print(f"오분류율: {error_count / len(y_true) * 100:.2f}%")

    print("\n질환별 평가 결과")

    print(
        classification_report(
            y_true,
            y_pred,
            labels=list(range(len(CLASS_NAMES))),
            target_names=CLASS_NAMES,
            zero_division=0,
        )
    )

    prediction_data = {
        "image_path": image_paths,
        "actual_label": y_true,
        "actual_disease": [
            CLASS_NAMES[label] for label in y_true
        ],
        "predicted_label": y_pred,
        "predicted_disease": [
            CLASS_NAMES[label] for label in y_pred
        ],
        "predicted_probability": [
            max(prob) for prob in y_prob
        ],
    }

    for index, class_name in enumerate(CLASS_NAMES):

        prediction_data[f"probability_{class_name}"] = [
            prob[index] for prob in y_prob
        ]

    predictions_df = pd.DataFrame(prediction_data)

    misclassified_df = predictions_df[
        predictions_df["actual_label"]
        != predictions_df["predicted_label"]
    ].copy()

    predictions_df.to_csv(
        RESULT_DIR / f"{model_name}_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    misclassified_df.to_csv(
        RESULT_DIR / f"{model_name}_misclassified.csv",
        index=False,
        encoding="utf-8-sig",
    )

    cm_df = pd.DataFrame(
        cm,
        index=CLASS_NAMES,
        columns=CLASS_NAMES,
    )

    cm_df.to_csv(
        RESULT_DIR / f"{model_name}_confusion_matrix.csv",
        encoding="utf-8-sig",
    )

    report_df = pd.DataFrame(report).transpose()

    report_df.to_csv(
        RESULT_DIR / f"{model_name}_classification_report.csv",
        encoding="utf-8-sig",
    )

    return {
        "accuracy": accuracy,
        "error_count": error_count,
        "error_rate": error_count / len(y_true),
        "report": report,
        "predictions": predictions_df,
    }


# ==========================================
# 5. 메인 실행
# ==========================================

def main():

    print("======================================")
    print("ResNet50 정면 Crop 실험 A 성능 평가")
    print("======================================")

    print(f"실행 장치: {DEVICE}")

    if not CSV_PATH.is_file():
        raise FileNotFoundError(
            f"테스트 CSV를 찾을 수 없습니다: {CSV_PATH}"
        )

    dataset = SkinDiseaseDataset(
        CSV_PATH,
        transform=eval_transform,
    )

    if len(dataset) == 0:
        raise ValueError("테스트 데이터가 비어 있습니다.")

    print(f"\n테스트 이미지: {len(dataset)}장")

    print("\n질환별 테스트 이미지 수:")

    print(
        dataset.df["disease"]
        .value_counts()
        .reindex(CLASS_NAMES, fill_value=0)
    )

    dataloader = DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=0,
    )

    # 기존 Crop 모델
    crop_model, crop_checkpoint = load_checkpoint(
        CROP_MODEL_PATH,
        "frontal_crop",
    )

    # 실험 A 모델
    aug_a_model, aug_a_checkpoint = load_checkpoint(
        AUG_A_MODEL_PATH,
        "frontal_crop",
    )

    print("\n===== 체크포인트 학습 정보 =====")

    for name, checkpoint in [
        ("Frontal Crop", crop_checkpoint),
        ("Frontal Aug A", aug_a_checkpoint),
    ]:

        print(f"\n[{name}]")
        print(f"Epoch: {checkpoint.get('epoch')}")
        print(f"Val Loss: {checkpoint.get('val_loss')}")
        print(f"Val Accuracy: {checkpoint.get('val_accuracy')}")

    crop_result = evaluate_model(
        crop_model,
        dataloader,
        dataset,
        "frontal_crop",
    )

    aug_a_result = evaluate_model(
        aug_a_model,
        dataloader,
        dataset,
        "frontal_aug_a",
    )

    # ======================================
    # 6. 최종 비교 결과
    # ======================================

    comparison_df = pd.DataFrame([

        {
            "model": "Frontal Crop",
            "checkpoint": CROP_MODEL_PATH.name,
            "epoch": crop_checkpoint.get("epoch"),
            "val_loss": crop_checkpoint.get("val_loss"),
            "val_accuracy": crop_checkpoint.get("val_accuracy"),
            "test_accuracy": crop_result["accuracy"],
            "error_count": crop_result["error_count"],
            "error_rate": crop_result["error_rate"],
        },

        {
            "model": "Frontal Aug A",
            "checkpoint": AUG_A_MODEL_PATH.name,
            "epoch": aug_a_checkpoint.get("epoch"),
            "val_loss": aug_a_checkpoint.get("val_loss"),
            "val_accuracy": aug_a_checkpoint.get("val_accuracy"),
            "test_accuracy": aug_a_result["accuracy"],
            "error_count": aug_a_result["error_count"],
            "error_rate": aug_a_result["error_rate"],
        },

    ])

    comparison_path = (
        RESULT_DIR / "frontal_aug_a_comparison.csv"
    )

    comparison_df.to_csv(
        comparison_path,
        index=False,
        encoding="utf-8-sig",
    )

    # ======================================
    # 7. 이미지별 예측 비교
    # ======================================

    crop_predictions = crop_result["predictions"]
    aug_a_predictions = aug_a_result["predictions"]

    image_comparison_df = pd.DataFrame({

        "image_path": crop_predictions["image_path"],
        "actual_disease": crop_predictions["actual_disease"],

        "crop_prediction": crop_predictions["predicted_disease"],
        "crop_confidence": crop_predictions["predicted_probability"],

        "aug_a_prediction": aug_a_predictions["predicted_disease"],
        "aug_a_confidence": aug_a_predictions["predicted_probability"],

    })

    image_comparison_df["crop_correct"] = (
        image_comparison_df["actual_disease"]
        == image_comparison_df["crop_prediction"]
    )

    image_comparison_df["aug_a_correct"] = (
        image_comparison_df["actual_disease"]
        == image_comparison_df["aug_a_prediction"]
    )

    image_comparison_df.to_csv(
        RESULT_DIR / "image_prediction_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # ======================================
    # 8. 최종 출력
    # ======================================

    print("\n======================================")
    print("기존 Crop vs 실험 A 비교 결과")
    print("======================================")

    print(comparison_df.to_string(index=False))

    print("\n===== 결과 저장 완료 =====")
    print(f"비교 결과: {comparison_path}")
    print(f"결과 폴더: {RESULT_DIR}")


if __name__ == "__main__":
    main()
