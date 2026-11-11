import pandas as pd
from pathlib import Path

BASE_DIR = Path(r"D:\skin-disease-ai")

LABEL_PATH = (
    BASE_DIR / "data/processed/encoded/labeling_metadata_side_clean.csv"
)

SOURCE_PATH = (
    BASE_DIR / "data/processed/encoded/side_only_clean.csv"
)

# 데이터 불러오기
label_df = pd.read_csv(LABEL_PATH)
source_df = pd.read_csv(SOURCE_PATH)

print("라벨링데이터 컬럼:", label_df.columns.tolist())
print("원천데이터 컬럼:", source_df.columns.tolist())


# 식별자 정규화 함수
def normalize_id(value):
    filename = str(value).replace("\\", "/").split("/")[-1]
    return filename.rsplit(".", 1)[0]


# 식별자 생성
label_df["join_id"] = label_df["identifier"].apply(normalize_id)
source_df["join_id"] = source_df["image_name"].apply(normalize_id)


# 식별자 비교
label_ids = set(label_df["join_id"])
source_ids = set(source_df["join_id"])

matched_ids = label_ids & source_ids
label_only_ids = label_ids - source_ids
source_only_ids = source_ids - label_ids

print("\n===== 식별자 매칭 결과 =====")
print("라벨링데이터:", len(label_df))
print("원천데이터:", len(source_df))
print("매칭된 식별자:", len(matched_ids))
print("라벨링에만 존재:", len(label_only_ids))
print("원천에만 존재:", len(source_only_ids))

print("\n===== 매칭되지 않은 라벨링데이터 샘플 =====")
print(list(label_only_ids)[:10])

print("\n===== 매칭되지 않은 원천데이터 샘플 =====")
print(list(source_only_ids)[:10])