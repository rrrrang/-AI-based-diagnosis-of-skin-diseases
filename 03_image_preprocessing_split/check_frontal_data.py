
from pathlib import Path
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data" / "processed" / "encoded"

FILES = [
    "frontal_train_grouped.csv",
    "frontal_val_grouped.csv",
    "frontal_test_grouped.csv",
]

dfs = {}

# 1. CSV 불러오기
for filename in FILES:
    path = DATA_DIR / filename

    df = pd.read_csv(path)
    dfs[filename] = df

    print(f"\n===== {filename} =====")
    print(f"전체 이미지: {len(df)}개")
    print(f"고유 group_id: {df['group_id'].nunique()}개")

# 2. 데이터셋 간 group_id 중복 검사
print("\n===== group_id 중복 검사 =====")

pairs = [
    (FILES[0], FILES[1]),
    (FILES[0], FILES[2]),
    (FILES[1], FILES[2]),
]

for name1, name2 in pairs:
    groups1 = set(dfs[name1]["group_id"].dropna())
    groups2 = set(dfs[name2]["group_id"].dropna())

    overlap = groups1 & groups2

    print(f"\n{name1} ↔ {name2}")
    print(f"중복 group_id: {len(overlap)}개")

    if overlap:
        print("중복 group_id 예시:", list(overlap)[:5])
    else:
        print("중복 없음")

# 3. group_id 결측값 검사
print("\n===== group_id 결측값 검사 =====")

for filename, df in dfs.items():
    print(
        f"{filename}: "
        f"{df['group_id'].isna().sum()}개"
    )

print("\n===== 검사 완료 =====")
