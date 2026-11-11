
import pandas as pd
from pathlib import Path

# 경로 설정
BASE = Path(r"D:\skin-disease-ai\data\processed")
SPLIT_DIR = BASE / "encoded"

LABELING_PATH = BASE / "라벨링_측면_정리본.csv"

# 데이터 불러오기
labeling = pd.read_csv(LABELING_PATH)

train = pd.read_csv(SPLIT_DIR / "final_train.csv")
val = pd.read_csv(SPLIT_DIR / "final_val.csv")
test = pd.read_csv(SPLIT_DIR / "final_test.csv")

# 질환명과 숫자 라벨 매핑
label_mapping = {
    "건선": 0,
    "아토피": 1,
    "여드름": 2,
    "정상": 3,
    "주사": 4,
    "지루": 5
}

# JSON 질환명을 숫자 라벨로 변환
labeling["label_json"] = labeling["diagnosis_name"].map(label_mapping)

# 분할 데이터 구분
train["split"] = "train"
val["split"] = "val"
test["split"] = "test"

# 전체 분할 데이터 합치기
split_df = pd.concat(
    [train, val, test],
    ignore_index=True
)

# 이미지 ID 기준으로 JSON 데이터 연결
merged = split_df.merge(
    labeling[["identifier", "diagnosis_name", "label_json"]],
    left_on="image_id",
    right_on="identifier",
    how="left",
    validate="one_to_one"
)

# 연결 결과 확인
print("\n===== 데이터 연결 결과 =====")
print("기존 분할 데이터:", len(split_df))
print("JSON 연결 성공:", merged["diagnosis_name"].notna().sum())
print("JSON 연결 실패:", merged["diagnosis_name"].isna().sum())

# 질환명 불일치 확인
matched = merged["diagnosis_name"].notna()

disease_mismatch = (
    merged.loc[matched, "disease"]
    != merged.loc[matched, "diagnosis_name"]
)

# 숫자 라벨 불일치 확인
label_mismatch = (
    merged.loc[matched, "label"]
    != merged.loc[matched, "label_json"]
)

print("\n===== 라벨 검증 결과 =====")
print("질환명 불일치:", disease_mismatch.sum())
print("숫자 라벨 불일치:", label_mismatch.sum())

# 중복 확인
print("\n===== 중복 확인 =====")
print("기존 이미지 ID 중복:", split_df["image_id"].duplicated().sum())
print("JSON 식별자 중복:", labeling["identifier"].duplicated().sum())

# 분할별 데이터 수
print("\n===== 분할별 데이터 수 =====")
print(merged.groupby("split").size())

# 분할별 질환 수
print("\n===== 분할별 질환 분포 =====")
print(
    merged.groupby(["split", "diagnosis_name"])
    .size()
    .unstack(fill_value=0)
)

# 연결 실패 데이터 확인
print("\n===== JSON 연결 실패 데이터 =====")
print(
    merged.loc[
        ~matched,
        ["image_id", "disease", "split"]
    ].head(10)
)

# 질환명 불일치 데이터 확인
print("\n===== 질환명 불일치 데이터 =====")
print(
    merged.loc[
        matched & (merged["disease"] != merged["diagnosis_name"]),
        ["image_id", "disease", "diagnosis_name"]
    ].head(10)
)

print("\n검증 완료!")
