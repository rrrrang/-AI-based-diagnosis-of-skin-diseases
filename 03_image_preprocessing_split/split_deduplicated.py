
import pandas as pd
from pathlib import Path
from sklearn.model_selection import train_test_split

BASE_DIR = Path(r"D:\skin-disease-ai")

INPUT_PATH = (
    BASE_DIR / "data" / "processed" /
    "encoded" / "side_only_deduplicated.csv"
)

OUTPUT_DIR = BASE_DIR / "data" / "processed" / "encoded"

RANDOM_STATE = 42

# 데이터 불러오기
df = pd.read_csv(INPUT_PATH)

print("전체 데이터:", len(df))

# 1차 분할: 학습 70%, 나머지 30%
train_df, temp_df = train_test_split(
    df,
    test_size=0.30,
    stratify=df["disease"],
    random_state=RANDOM_STATE
)

# 2차 분할: 나머지 30%를 검증 15%, 테스트 15%로 분할
val_df, test_df = train_test_split(
    temp_df,
    test_size=0.50,
    stratify=temp_df["disease"],
    random_state=RANDOM_STATE
)

# 파일 저장
train_df.to_csv(
    OUTPUT_DIR / "side_train_deduplicated.csv",
    index=False,
    encoding="utf-8-sig"
)

val_df.to_csv(
    OUTPUT_DIR / "side_val_deduplicated.csv",
    index=False,
    encoding="utf-8-sig"
)

test_df.to_csv(
    OUTPUT_DIR / "side_test_deduplicated.csv",
    index=False,
    encoding="utf-8-sig"
)

# 분할 결과 출력
print("\n===== 데이터 분할 결과 =====")
print("Train:", len(train_df))
print("Validation:", len(val_df))
print("Test:", len(test_df))
print("합계:", len(train_df) + len(val_df) + len(test_df))

print("\n===== 질환별 분포 =====")

for name, data in [
    ("Train", train_df),
    ("Validation", val_df),
    ("Test", test_df)
]:
    print(f"\n[{name}]")
    print(data["disease"].value_counts().sort_index())

# 경로 중복 검사
train_paths = set(train_df["path"])
val_paths = set(val_df["path"])
test_paths = set(test_df["path"])

print("\n===== 데이터 누수 검사 =====")
print("Train-Val:", len(train_paths & val_paths))
print("Train-Test:", len(train_paths & test_paths))
print("Val-Test:", len(val_paths & test_paths))

assert len(train_df) + len(val_df) + len(test_df) == len(df)
assert len(train_paths & val_paths) == 0
assert len(train_paths & test_paths) == 0
assert len(val_paths & test_paths) == 0

print("\n모든 분할 및 중복 검사 통과!")
