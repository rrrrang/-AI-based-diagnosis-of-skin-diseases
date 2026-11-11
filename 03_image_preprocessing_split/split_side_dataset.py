
from pathlib import Path
import pandas as pd
from sklearn.model_selection import train_test_split

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENCODED_DIR = PROJECT_DIR / "data" / "processed" / "encoded"

INPUT_PATH = ENCODED_DIR / "side_only_clean.csv"

# 데이터 불러오기
df = pd.read_csv(INPUT_PATH)

# Train 70%, 나머지 30%
train_df, temp_df = train_test_split(
    df,
    test_size=0.30,
    random_state=42,
    stratify=df["label"]
)

# Validation 15%, Test 15%
val_df, test_df = train_test_split(
    temp_df,
    test_size=0.50,
    random_state=42,
    stratify=temp_df["label"]
)

# CSV 저장
train_df.to_csv(
    ENCODED_DIR / "side_train.csv",
    index=False,
    encoding="utf-8-sig"
)

val_df.to_csv(
    ENCODED_DIR / "side_val.csv",
    index=False,
    encoding="utf-8-sig"
)

test_df.to_csv(
    ENCODED_DIR / "side_test.csv",
    index=False,
    encoding="utf-8-sig"
)

# 결과 확인
print("[데이터 분리 결과]")
print(f"Train: {len(train_df):,}개")
print(f"Validation: {len(val_df):,}개")
print(f"Test: {len(test_df):,}개")
print(f"전체: {len(train_df) + len(val_df) + len(test_df):,}개")

print("\n[Train 질환별 분포]")
print(train_df["disease"].value_counts().sort_index())

print("\n[Validation 질환별 분포]")
print(val_df["disease"].value_counts().sort_index())

print("\n[Test 질환별 분포]")
print(test_df["disease"].value_counts().sort_index())

print("\n[이미지 경로 중복 검증]")
all_paths = pd.concat([
    train_df["path"],
    val_df["path"],
    test_df["path"]
])

print(f"전체 경로 중복: {all_paths.duplicated().sum()}개")

print("\n[저장 완료]")
print("side_train.csv")
print("side_val.csv")
print("side_test.csv")
