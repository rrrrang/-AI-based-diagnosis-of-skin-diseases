
from pathlib import Path
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent

# 최종 중복 제거 데이터의 train/val/test
SPLIT_FILES = [
    PROJECT_DIR / "data/processed/encoded/side_train_deduplicated.csv",
    PROJECT_DIR / "data/processed/encoded/side_val_deduplicated.csv",
    PROJECT_DIR / "data/processed/encoded/side_test_deduplicated.csv",
]

LABELING_CSV = (
    PROJECT_DIR / "data/processed/encoded/labeling_metadata.csv"
)

OUTPUT_CSV = (
    PROJECT_DIR / "results/labeling_quality_summary.csv"
)


def main():
    # 데이터 분할 파일 통합
    datasets = []

    for file in SPLIT_FILES:
        if not file.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file}")

        df = pd.read_csv(file)
        datasets.append(df)

    dataset = pd.concat(datasets, ignore_index=True)

    # 이미지 파일명에서 identifier 추출
    dataset["identifier"] = dataset["path"].apply(
        lambda x: Path(str(x)).stem
    )

    # 측면 라벨링 데이터 불러오기
    labeling = pd.read_csv(LABELING_CSV)
    labeling = labeling[labeling["view"] == "측면"].copy()

    # 중복 식별자 확인
    duplicate_count = labeling["identifier"].duplicated().sum()

    print(f"최종 이미지 수: {len(dataset)}")
    print(f"측면 라벨링 데이터 수: {len(labeling)}")
    print(f"라벨링 식별자 중복 수: {duplicate_count}")

    # 이미지 데이터와 라벨링 정보 연결
    merged = dataset.merge(
        labeling,
        on="identifier",
        how="left",
        suffixes=("_image", "_label"),
        validate="one_to_one"
    )

    merged = dataset.merge(
        labeling,
        on="identifier",
        how="left",
        suffixes=("_image", "_label"),
        validate="one_to_one"
    )

    # 원천 이미지 질환명과 라벨링 진단명 비교
    merged["label_match"] = (
            merged["disease_image"].astype(str).str.strip()
            ==
            merged["diagnosis_name"].astype(str).str.strip()
    )

    # 불일치 데이터 추출
    mismatch = merged[~merged["label_match"]].copy()

    print("\n===== 질환명 일치 여부 검사 =====")
    print(f"전체 이미지: {len(merged)}")
    print(f"일치: {merged['label_match'].sum()}")
    print(f"불일치: {len(mismatch)}")

    if not mismatch.empty:
        print("\n===== 불일치 데이터 =====")
        print(
            mismatch[
                ["identifier", "disease_image", "diagnosis_name"]
            ].to_string(index=False)
        )

        mismatch.to_csv(
            PROJECT_DIR / "results/label_mismatch.csv",
            index=False,
            encoding="utf-8-sig"
        )

    # 기존 코드 계속 진행
    fields = [
        "diagnosis_name",
        "diagnosis_bodypart",
        "desc",
        "gender",
        "generated_bodypart",
        "photograph_width",
        "photograph_height",
    ]

    fields = [
        "diagnosis_name",
        "diagnosis_bodypart",
        "desc",
        "gender",
        "generated_bodypart",
        "photograph_width",
        "photograph_height",
    ]

    results = []

    for disease, group in merged.groupby("disease_image"):
        for field in fields:
            missing = group[field].isna().sum()

            results.append({
                "disease": disease,
                "total_images": len(group),
                "field": field,
                "missing_count": int(missing),
                "missing_rate_percent": round(
                    missing / len(group) * 100, 2
                ),
            })

    result_df = pd.DataFrame(results)

    result_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n===== 전체 라벨링 품질 분석 =====")
    print(result_df.to_string(index=False))

    print("\n===== 매칭 상태 =====")
    print(f"전체 이미지: {len(merged)}")
    print(f"라벨링 진단명 누락: {merged['diagnosis_name'].isna().sum()}")
    print(f"라벨링 설명 누락: {merged['desc'].isna().sum()}")

    print(f"\n저장 경로: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
