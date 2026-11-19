
from pathlib import Path

import pandas as pd
import torch

from torch.utils.data import DataLoader
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

from src.dataset import SkinDiseaseDataset, base_transform
from src.dataloader_aspect import eval_transform_aspect
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

RESULT_DIR = (
    PROJECT_DIR
    / "results"
    / "frontal_two_models_test"
)

MODEL_CONFIGS = {
    "aspect": {
        "checkpoint": (
            PROJECT_DIR
            / "models"
            / "resnet50_frontal_aspect_best.pth"
        ),
        "transform": eval_transform_aspect,
        "input_view": "frontal_aspect",
    },
    "aug_a": {
        "checkpoint": (
            PROJECT_DIR
            / "models"
            / "resnet50_frontal_aug_a_best.pth"
        ),
        "transform": base_transform,
        "input_view": "frontal_crop",
    },
}

BATCH_SIZE = 32
NUM_WORKERS = 0

DEVICE = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)


# ==========================================
# 2. 기본 환경 확인
# ==========================================

def check_paths():

    print("\n===== 파일 경로 확인 =====")

    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"테스트 CSV 파일이 없습니다: {CSV_PATH}"
        )

    for name, config in MODEL_CONFIGS.items():

        checkpoint = config["checkpoint"]

        if not checkpoint.exists():
            raise FileNotFoundError(
                f"{name} 모델 파일이 없습니다: {checkpoint}"
            )

        print(f"[확인] {name}: {checkpoint.name}")

    print(f"[확인] 테스트 CSV: {CSV_PATH.name}")
    print(f"[확인] 장치: {DEVICE}")


# ==========================================
# 3. 모델 불러오기
# ==========================================

def load_model(name, config):

    checkpoint_path = config["checkpoint"]

    checkpoint = torch.load(
        checkpoint_path,
        map_location=DEVICE,
        weights_only=True,
    )

    class_names = checkpoint.get("class_names")

    expected_classes = [
        "건선",
        "아토피",
        "여드름",
        "정상",
        "주사",
        "지루",
    ]

    if class_names != expected_classes:
        raise ValueError(
            f"{name} 모델의 클래스 순서가 예상과 다릅니다: "
            f"{class_names}"
        )

    input_view = checkpoint.get("input_view")

    if input_view != config["input_view"]:
        raise ValueError(
            f"{name} 모델의 입력 유형이 다릅니다: {input_view}"
        )

    model = create_model()

    model.load_state_dict(checkpoint["model_state_dict"])

    model = model.to(DEVICE)
    model.eval()

    print(f"\n[{name.upper()} 모델 로드 완료]")
    print(f"체크포인트: {checkpoint_path.name}")
    print(f"학습 epoch: {checkpoint.get('epoch')}")
    print(f"검증 정확도: {checkpoint.get('val_accuracy')}")
    print(f"입력 유형: {input_view}")

    return model, class_names


# ==========================================
# 4. 테스트 데이터 불러오기
# ==========================================

def load_test_data(transform):

    dataset = SkinDiseaseDataset(
        csv_path=CSV_PATH,
        transform=transform,
    )

    loader = DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS,
    )

    return dataset, loader


# ==========================================
# 5. 동적 추론 실행
# ==========================================

def run_inference(model, loader, class_names):

    all_labels = []
    all_predictions = []
    all_probabilities = []

    model.eval()

    with torch.no_grad():

        for images, labels in loader:

            images = images.to(DEVICE)

            outputs = model(images)

            probabilities = torch.softmax(
                outputs,
                dim=1,
            )

            predictions = torch.argmax(
                probabilities,
                dim=1,
            )

            all_labels.extend(labels.tolist())

            all_predictions.extend(
                predictions.cpu().tolist()
            )

            all_probabilities.extend(
                probabilities.cpu().tolist()
            )

    all_probabilities = torch.tensor(
        all_probabilities
    ).numpy()

    return (
        all_labels,
        all_predictions,
        all_probabilities,
    )


# ==========================================
# 6. 결과 분석 및 저장
# ==========================================

def save_results(
    model_name,
    dataset,
    class_names,
    labels,
    predictions,
    probabilities,
):

    accuracy = accuracy_score(
        labels,
        predictions,
    )

    report = classification_report(
        labels,
        predictions,
        labels=list(range(len(class_names))),
        target_names=class_names,
        output_dict=True,
        zero_division=0,
    )

    matrix = confusion_matrix(
        labels,
        predictions,
        labels=list(range(len(class_names))),
    )

    result_df = dataset.df.copy()

    result_df["true_label"] = labels

    result_df["true_disease"] = [
        class_names[label] for label in labels
    ]

    result_df["pred_label"] = predictions

    result_df["pred_disease"] = [
        class_names[pred] for pred in predictions
    ]

    result_df["confidence"] = probabilities.max(
        axis=1
    ) * 100

    result_df["correct"] = (
        result_df["true_label"]
        == result_df["pred_label"]
    )

    for index, disease in enumerate(class_names):

        result_df[f"prob_{disease}"] = (
            probabilities[:, index] * 100
        )

    result_path = (
        RESULT_DIR
        / f"{model_name}_predictions.csv"
    )

    misclassified_path = (
        RESULT_DIR
        / f"{model_name}_misclassified.csv"
    )

    report_path = (
        RESULT_DIR
        / f"{model_name}_classification_report.csv"
    )

    matrix_path = (
        RESULT_DIR
        / f"{model_name}_confusion_matrix.csv"
    )

    result_df.to_csv(
        result_path,
        index=False,
        encoding="utf-8-sig",
    )

    result_df[
        result_df["correct"] == False
    ].to_csv(
        misclassified_path,
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame(report).transpose().to_csv(
        report_path,
        encoding="utf-8-sig",
    )

    pd.DataFrame(
        matrix,
        index=class_names,
        columns=class_names,
    ).to_csv(
        matrix_path,
        encoding="utf-8-sig",
    )

    correct_count = sum(
        true == pred
        for true, pred in zip(labels, predictions)
    )

    print(f"\n===== {model_name.upper()} 평가 결과 =====")

    print(f"전체 테스트 이미지: {len(labels)}")
    print(f"정확하게 예측: {correct_count}")
    print(f"오분류: {len(labels) - correct_count}")
    print(f"정확도: {accuracy * 100:.2f}%")

    print("\n[질환별 성능]")
    print(
        classification_report(
            labels,
            predictions,
            labels=list(range(len(class_names))),
            target_names=class_names,
            zero_division=0,
        )
    )

    return {
        "model": model_name,
        "test_count": len(labels),
        "correct": correct_count,
        "incorrect": len(labels) - correct_count,
        "accuracy": accuracy * 100,
    }, result_df


# ==========================================
# 7. 두 모델 비교
# ==========================================

def compare_predictions(aspect_df, aug_a_df):

    if not aspect_df["path"].equals(
        aug_a_df["path"]
    ):
        raise ValueError(
            "두 모델의 테스트 이미지 순서가 일치하지 않습니다."
        )

    if not aspect_df["true_label"].equals(
        aug_a_df["true_label"]
    ):
        raise ValueError(
            "두 모델의 실제 정답이 일치하지 않습니다."
        )

    comparison_df = pd.DataFrame({

        "path": aspect_df["path"],

        "true_disease": aspect_df["true_disease"],

        "aspect_prediction": aspect_df["pred_disease"],

        "aspect_confidence": aspect_df["confidence"],

        "aspect_correct": aspect_df["correct"],

        "aug_a_prediction": aug_a_df["pred_disease"],

        "aug_a_confidence": aug_a_df["confidence"],

        "aug_a_correct": aug_a_df["correct"],

    })

    comparison_df.to_csv(
        RESULT_DIR / "image_prediction_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    return comparison_df


# ==========================================
# 8. 메인 실행
# ==========================================

def main():

    print("\n======================================")
    print("정면 ResNet50 두 모델 동적 확인 테스트")
    print("======================================")

    check_paths()

    RESULT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary_results = []
    prediction_results = {}

    for model_name, config in MODEL_CONFIGS.items():

        print(f"\n\n===== {model_name.upper()} 테스트 시작 =====")

        model, class_names = load_model(
            model_name,
            config,
        )

        dataset, loader = load_test_data(
            config["transform"]
        )

        labels, predictions, probabilities = run_inference(
            model,
            loader,
            class_names,
        )

        summary, result_df = save_results(
            model_name,
            dataset,
            class_names,
            labels,
            predictions,
            probabilities,
        )

        summary_results.append(summary)

        prediction_results[model_name] = result_df

        del model

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    comparison_df = compare_predictions(
        prediction_results["aspect"],
        prediction_results["aug_a"],
    )

    summary_df = pd.DataFrame(
        summary_results
    )

    summary_df.to_csv(
        RESULT_DIR / "model_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("\n======================================")
    print("최종 모델 성능 비교")
    print("======================================")

    print(
        summary_df.to_string(
            index=False
        )
    )

    print("\n[이미지별 예측 비교]")
    print(f"비교 이미지: {len(comparison_df)}")

    print("\n[결과 저장 위치]")
    print(RESULT_DIR)

    print("\n동적 확인 테스트 완료")


if __name__ == "__main__":
    main()
