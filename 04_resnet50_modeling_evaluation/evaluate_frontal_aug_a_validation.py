
from pathlib import Path

import pandas as pd
import torch

from torch.utils.data import DataLoader
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

from src.model import create_model
from src.dataset import SkinDiseaseDataset, base_transform


# ==========================================
# 경로 및 기본 설정
# ==========================================

PROJECT_DIR = Path(__file__).resolve().parent.parent

MODEL_PATH = (
    PROJECT_DIR
    / "models"
    / "resnet50_frontal_aug_a_best.pth"
)

VALIDATION_CSV = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "encoded"
    / "frontal_val_grouped.csv"
)

RESULT_DIR = (
    PROJECT_DIR
    / "results"
    / "frontal_aug_a_validation"
)

RESULT_DIR.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 32
NUM_WORKERS = 0

CLASS_NAMES = [
    "건선",
    "아토피",
    "여드름",
    "정상",
    "주사",
    "지루",
]

DEVICE = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)


# ==========================================
# 체크포인트 불러오기
# ==========================================

def load_checkpoint():

    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}"
        )

    try:
        checkpoint = torch.load(
            MODEL_PATH,
            map_location=DEVICE,
            weights_only=True,
        )

    except TypeError:
        # weights_only 옵션을 지원하지 않는 구버전 대응
        checkpoint = torch.load(
            MODEL_PATH,
            map_location=DEVICE,
        )

    if "model_state_dict" not in checkpoint:
        raise KeyError(
            "체크포인트에 model_state_dict가 없습니다."
        )

    saved_classes = checkpoint.get("class_names")

    if saved_classes != CLASS_NAMES:
        raise ValueError(
            f"클래스 순서 불일치\n"
            f"체크포인트: {saved_classes}\n"
            f"평가 코드: {CLASS_NAMES}"
        )

    return checkpoint


# ==========================================
# 검증 평가
# ==========================================

def main():

    print("=" * 55)
    print("ResNet50 정면 Crop 실험 A 검증 평가")
    print("=" * 55)

    print(f"실행 장치: {DEVICE}")
    print(f"모델 경로: {MODEL_PATH}")
    print(f"검증 데이터: {VALIDATION_CSV}")

    if not VALIDATION_CSV.is_file():
        raise FileNotFoundError(
            f"검증 CSV를 찾을 수 없습니다: {VALIDATION_CSV}"
        )

    # 체크포인트 불러오기
    checkpoint = load_checkpoint()

    print(f"\n최적 모델 Epoch: {checkpoint['epoch']}")
    print(f"학습 당시 Val Loss: {checkpoint['val_loss']:.4f}")
    print(f"학습 당시 Val Accuracy: {checkpoint['val_accuracy']:.4f}")

    # 검증 데이터만 불러오기
    val_dataset = SkinDiseaseDataset(
        VALIDATION_CSV,
        transform=base_transform,
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS,
    )

    print(f"\n검증 이미지 수: {len(val_dataset)}개")

    # 모델 생성 및 체크포인트 적용
    model = create_model()

    model.load_state_dict(
        checkpoint["model_state_dict"],
        strict=True,
    )

    model = model.to(DEVICE)
    model.eval()

    predictions = []

    # 추론 전용: 학습 및 역전파 없음
    with torch.no_grad():

        for images, labels in val_loader:

            images = images.to(DEVICE)

            outputs = model(images)

            if outputs.shape[1] != len(CLASS_NAMES):
                raise ValueError(
                    "모델 출력 클래스 수가 6개가 아닙니다."
                )

            probabilities = torch.softmax(
                outputs,
                dim=1,
            )

            predicted_labels = probabilities.argmax(dim=1)

            confidence = probabilities.max(dim=1).values

            for i in range(len(labels)):

                predictions.append({
                    "actual_label": int(labels[i].item()),
                    "predicted_label": int(
                        predicted_labels[i].item()
                    ),
                    "predicted_probability": float(
                        confidence[i].item()
                    ),
                    **{
                        f"probability_{CLASS_NAMES[j]}":
                            float(probabilities[i][j].item())
                        for j in range(len(CLASS_NAMES))
                    }
                })

    # ======================================
    # 결과 데이터 생성
    # ======================================

    result_df = pd.DataFrame(predictions)

    # Dataset의 CSV 순서와 DataLoader 순서는 동일
    source_df = val_dataset.df.reset_index(drop=True)

    if len(source_df) != len(result_df):
        raise ValueError(
            "검증 데이터와 예측 결과의 행 수가 일치하지 않습니다."
        )

    result_df.insert(
        0,
        "image_path",
        source_df["path"].apply(
            lambda p: str(
                Path(p) if Path(p).is_absolute()
                else PROJECT_DIR / p
            )
        ),
    )

    result_df.insert(
        1,
        "actual_disease",
        result_df["actual_label"].map(
            dict(enumerate(CLASS_NAMES))
        ),
    )

    result_df.insert(
        3,
        "predicted_disease",
        result_df["predicted_label"].map(
            dict(enumerate(CLASS_NAMES))
        ),
    )

    # ======================================
    # 정확도 및 오분류 결과
    # ======================================

    y_true = result_df["actual_label"]
    y_pred = result_df["predicted_label"]

    accuracy = accuracy_score(y_true, y_pred)

    misclassified_df = result_df[
        result_df["actual_label"] != result_df["predicted_label"]
    ].copy()

    # ======================================
    # 질환별 Classification Report
    # ======================================

    report = classification_report(
        y_true,
        y_pred,
        labels=list(range(len(CLASS_NAMES))),
        target_names=CLASS_NAMES,
        output_dict=True,
        zero_division=0,
    )

    report_df = pd.DataFrame(report).transpose()

    # ======================================
    # Confusion Matrix
    # ======================================

    matrix = confusion_matrix(
        y_true,
        y_pred,
        labels=list(range(len(CLASS_NAMES))),
    )

    confusion_df = pd.DataFrame(
        matrix,
        index=CLASS_NAMES,
        columns=CLASS_NAMES,
    )

    confusion_df.index.name = "actual_disease"

    # ======================================
    # CSV 저장
    # ======================================

    result_df.to_csv(
        RESULT_DIR / "frontal_aug_a_validation_predictions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    misclassified_df.to_csv(
        RESULT_DIR / "frontal_aug_a_validation_misclassified.csv",
        index=False,
        encoding="utf-8-sig",
    )

    report_df.to_csv(
        RESULT_DIR / "frontal_aug_a_validation_classification_report.csv",
        encoding="utf-8-sig",
    )

    confusion_df.to_csv(
        RESULT_DIR / "frontal_aug_a_validation_confusion_matrix.csv",
        encoding="utf-8-sig",
    )

    # ======================================
    # 최종 출력
    # ======================================

    print("\n" + "=" * 55)
    print("검증 평가 결과")
    print("=" * 55)

    print(f"전체 검증 이미지: {len(result_df)}개")
    print(f"정상 예측: {len(result_df) - len(misclassified_df)}개")
    print(f"오분류: {len(misclassified_df)}개")
    print(f"검증 정확도: {accuracy * 100:.2f}%")

    print("\n===== 질환별 평가 결과 =====")
    print(report_df)

    print("\n===== 혼동행렬 =====")
    print(confusion_df)

    print("\n===== 결과 저장 완료 =====")
    print(f"저장 위치: {RESULT_DIR}")


if __name__ == "__main__":
    main()
