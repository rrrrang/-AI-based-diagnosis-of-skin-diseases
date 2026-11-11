from pathlib import Path
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent

RESULT_CSV = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "frontal_cropped"
    / "frontal_crop_results.csv"
)

MISSING_CSV = (
    PROJECT_DIR
    / "results"
    / "frontal_split_missing.csv"
)

df = pd.read_csv(RESULT_CSV, encoding="utf-8-sig")
missing = pd.read_csv(MISSING_CSV, encoding="utf-8-sig")

print("===== 전체 Crop 처리 결과 =====")
print("전체 처리 이미지:", len(df))
print("\n상태별 이미지 수:")
print(df["status"].value_counts(dropna=False))

print("\n===== 질환별 처리 상태 =====")
print(
    pd.crosstab(
        df["disease"],
        df["status"]
    )
)

# 누락 이미지와 Crop 결과 연결
missing_ids = set(missing["identifier"].astype(str))

df["identifier"] = (
    df["filename"]
    .astype(str)
    .str.replace(r"\.[^.]+$", "", regex=True)
)

missing_results = df[
    df["identifier"].isin(missing_ids)
].copy()

print("\n===== 누락된 385개 이미지의 Crop 기록 =====")
print("매칭된 이미지:", len(missing_results))

print("\n상태별 결과:")
print(missing_results["status"].value_counts(dropna=False))

print("\n질환별 상태:")
print(
    pd.crosstab(
        missing_results["disease"],
        missing_results["status"]
    )
)

print("\n누락 이미지 중 일부:")
print(
    missing_results[
        ["identifier", "disease", "status", "error"]
    ].head(20).to_string(index=False)
)

output_path = PROJECT_DIR / "results" / "missing_crop_failure_details.csv"

missing_results.to_csv(
    output_path,
    index=False,
    encoding="utf-8-sig"
)

print("\n결과 저장:", output_path)