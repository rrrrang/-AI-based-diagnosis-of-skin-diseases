
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(r"D:\skin-disease-ai")
DATA_DIR = PROJECT_ROOT / "data" / "processed" / "encoded"

source_path = DATA_DIR / "labeling_metadata.csv"

split_files = {
    "train": DATA_DIR / "frontal_train_grouped.csv",
    "val": DATA_DIR / "frontal_val_grouped.csv",
    "test": DATA_DIR / "frontal_test_grouped.csv",
}

# 원본 정면 데이터
source = pd.read_csv(source_path, encoding="utf-8-sig")
source = source[source["view"] == "정면"].copy()

# 원본 identifier 기준
source["identifier"] = source["identifier"].astype(str).str.strip()

# 분할 데이터 불러오기
split_dfs = []

for name, file_path in split_files.items():
    df = pd.read_csv(file_path, encoding="utf-8-sig")

    # 경로에서 파일명 추출
    df["filename"] = df["path"].astype(str).apply(
        lambda x: x.replace("\\", "/").split("/")[-1]
    )

    # 확장자 제거하여 identifier 생성
    df["identifier"] = df["filename"].apply(
        lambda x: Path(x).stem
    )

    df["split"] = name
    split_dfs.append(df)

split = pd.concat(split_dfs, ignore_index=True)

# 식별자 비교
source_ids = set(source["identifier"])
split_ids = set(split["identifier"])

missing_ids = source_ids - split_ids
extra_ids = split_ids - source_ids

print("===== 전체 데이터 비교 =====")
print(f"원본 정면 이미지: {len(source)}")
print(f"분할 이미지: {len(split)}")
print(f"원본 고유 identifier: {len(source_ids)}")
print(f"분할 고유 identifier: {len(split_ids)}")
print(f"누락 이미지: {len(missing_ids)}")
print(f"원본에 없는 이미지: {len(extra_ids)}")

# 누락 데이터 상세
missing = source[
    source["identifier"].isin(missing_ids)
].copy()

print("\n===== 누락 이미지 질환별 분포 =====")
print(missing["disease"].value_counts())

print("\n===== 누락 이미지 샘플 =====")
print(
    missing[["identifier", "disease"]]
    .head(20)
    .to_string(index=False)
)

# 중복 identifier 검사
print("\n===== 중복 검사 =====")
print("원본 중복 identifier:", source["identifier"].duplicated().sum())
print("분할 중복 identifier:", split["identifier"].duplicated().sum())

# 저장
output_path = PROJECT_ROOT / "results" / "frontal_split_missing.csv"
output_path.parent.mkdir(parents=True, exist_ok=True)

missing.to_csv(output_path, index=False, encoding="utf-8-sig")

print("\n검사 완료")
print("저장 위치:", output_path)
