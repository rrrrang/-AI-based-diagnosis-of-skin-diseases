
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent.parent

VALIDATION_CSV = (
    PROJECT_DIR / "data" / "processed" / "encoded"
    / "frontal_val_grouped.csv"
)

PREDICTIONS_CSV = (
    PROJECT_DIR / "results" / "frontal_aug_a_validation"
    / "frontal_aug_a_validation_predictions.csv"
)

RESULT_DIR = (
    PROJECT_DIR / "results" / "frontal_aug_a_validation"
)


def normalize_path(path):
    return str(Path(path).resolve()).lower()


def main():

    print("=" * 60)
    print("실험 A 검증 데이터 동일 대상자별 분석")
    print("=" * 60)

    validation = pd.read_csv(VALIDATION_CSV)
    predictions = pd.read_csv(PREDICTIONS_CSV)

    required_columns = {
        "path", "disease", "group_id"
    }

    if not required_columns.issubset(validation.columns):
        raise ValueError("검증 CSV 필수 컬럼이 누락되었습니다.")

    if "image_path" not in predictions.columns:
        raise ValueError("예측 CSV에 image_path가 없습니다.")

    # 이미지 경로 기준 병합
    validation["match_path"] = validation["path"].apply(
        lambda p: normalize_path(
            p if Path(p).is_absolute() else PROJECT_DIR / p
        )
    )

    predictions["match_path"] = predictions["image_path"].apply(
        normalize_path
    )

    if validation["match_path"].duplicated().any():
        raise ValueError("검증 CSV에 중복 이미지 경로가 있습니다.")

    if predictions["match_path"].duplicated().any():
        raise ValueError("예측 CSV에 중복 이미지 경로가 있습니다.")

    merged = validation.merge(
        predictions,
        on="match_path",
        how="left",
        validate="one_to_one",
        indicator=True,
    )

    unmatched = merged[merged["_merge"] != "both"]

    if len(unmatched) > 0:
        raise ValueError(
            f"예측 결과와 연결되지 않은 이미지가 {len(unmatched)}장 있습니다."
        )

    if len(merged) != 430:
        print(f"주의: 예상한 430장과 다릅니다. 실제 {len(merged)}장")

    merged["is_correct"] = (
        merged["disease"] == merged["predicted_disease"]
    )

    # ======================================
    # 이미지별 상세 결과
    # ======================================

    image_columns = [
        "group_id",
        "path",
        "disease",
        "predicted_disease",
        "is_correct",
        "predicted_probability",
    ]

    image_result = merged[image_columns].copy()

    image_result = image_result.rename(columns={
        "path": "image_path",
        "disease": "actual_disease",
    })

    image_result.to_csv(
        RESULT_DIR / "frontal_aug_a_validation_group_images.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # ======================================
    # 대상자별 집계
    # ======================================

    group_result = (
        merged.groupby("group_id")
        .agg(
            image_count=("image_path", "count"),
            actual_diseases=(
                "disease",
                lambda x: ", ".join(sorted(set(x)))
            ),
            predicted_diseases=(
                "predicted_disease",
                lambda x: ", ".join(sorted(set(x)))
            ),
            correct_count=("is_correct", "sum"),
        )
        .reset_index()
    )

    group_result["incorrect_count"] = (
        group_result["image_count"]
        - group_result["correct_count"]
    )

    group_result["group_accuracy"] = (
        group_result["correct_count"]
        / group_result["image_count"]
        * 100
    ).round(2)

    group_result["all_correct"] = (
        group_result["incorrect_count"] == 0
    )

    group_result = group_result.sort_values(
        ["incorrect_count", "image_count"],
        ascending=[False, False],
    )

    group_result.to_csv(
        RESULT_DIR / "frontal_aug_a_validation_group_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # ======================================
    # 오분류가 있는 대상자만 추출
    # ======================================

    error_groups = group_result[
        group_result["incorrect_count"] > 0
    ].copy()

    error_groups.to_csv(
        RESULT_DIR / "frontal_aug_a_validation_error_groups.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # ======================================
    # 동일 대상자 내 질환 혼합 확인
    # ======================================

    mixed_groups = group_result[
        group_result["actual_diseases"].str.contains(",")
    ].copy()

    mixed_groups.to_csv(
        RESULT_DIR / "frontal_aug_a_validation_mixed_disease_groups.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # ======================================
    # 최종 출력
    # ======================================

    print("\n===== 전체 대상자 분석 =====")
    print(f"검증 이미지: {len(merged)}장")
    print(f"고유 대상자: {len(group_result)}명")
    print(f"오분류 이미지: {(~merged['is_correct']).sum()}장")
    print(f"오분류 대상자: {len(error_groups)}명")
    print(f"모든 이미지 정답인 대상자: {group_result['all_correct'].sum()}명")
    print(f"질환 혼합 대상자: {len(mixed_groups)}명")

    print("\n===== 오분류가 있는 대상자 상위 20명 =====")

    print(
        error_groups.head(20).to_string(index=False)
    )

    print("\n===== 질환 혼합 대상자 =====")

    if len(mixed_groups) > 0:
        print(mixed_groups.to_string(index=False))
    else:
        print("질환 혼합 대상자가 없습니다.")

    print("\n===== 저장 완료 =====")
    print(f"저장 위치: {RESULT_DIR}")


if __name__ == "__main__":
    main()
