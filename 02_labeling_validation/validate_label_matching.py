import pandas as pd
from pathlib import Path

BASE_DIR = Path(r"D:\skin-disease-ai")

LABEL_PATH = BASE_DIR / "data/processed/encoded/labeling_metadata_side_clean.csv"
SOURCE_PATH = BASE_DIR / "data/processed/encoded/side_only_clean.csv"

# 데이터 불러오기
label_df = pd.read_csv(LABEL_PATH)
source_df = pd.read_csv(SOURCE_PATH)


# 식별자 정규화
def normalize_id(value):
    filename = str(value).replace("\\", "/").split("/")[-1]
    return filename.rsplit(".", 1)[0]


label_df["join_id"] = label_df["identifier"].apply(normalize_id)
source_df["join_id"] = source_df["image_name"].apply(normalize_id)


# 데이터 병합
merged = pd.merge(
    label_df,
    source_df,
    on="join_id",
    how="inner",
    suffixes=("_label", "_source"),
    validate="one_to_one"
)


# 질환명 검증
disease_match = (
    merged["disease_label"].astype(str).str.strip()
    == merged["disease_source"].astype(str).str.strip()
)

# 이미지 크기 검증
width_match = (
    pd.to_numeric(merged["photograph_width"], errors="coerce")
    == pd.to_numeric(merged["width"], errors="coerce")
)

height_match = (
    pd.to_numeric(merged["photograph_height"], errors="coerce")
    == pd.to_numeric(merged["height"], errors="coerce")
)


print("===== 매칭 데이터 검증 결과 =====")
print("매칭 데이터:", len(merged))
print("질환명 일치:", disease_match.sum())
print("질환명 불일치:", (~disease_match).sum())
print("너비 일치:", width_match.sum())
print("너비 불일치:", (~width_match).sum())
print("높이 일치:", height_match.sum())
print("높이 불일치:", (~height_match).sum())
print("중복 식별자:", merged["join_id"].duplicated().sum())


# 질환명 불일치 데이터 저장
mismatch = merged[~disease_match].copy()

output_dir = BASE_DIR / "data/processed/encoded"
mismatch.to_csv(
    output_dir / "labeling_disease_mismatch.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\n검증 완료")