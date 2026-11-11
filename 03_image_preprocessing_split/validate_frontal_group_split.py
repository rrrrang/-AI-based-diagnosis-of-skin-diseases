
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(r"D:\skin-disease-ai")
DATA_DIR = PROJECT_ROOT / "data" / "processed" / "encoded"

files = {
    "train": DATA_DIR / "frontal_train_grouped.csv",
    "val": DATA_DIR / "frontal_val_grouped.csv",
    "test": DATA_DIR / "frontal_test_grouped.csv",
}

datasets = {}

for name, path in files.items():
    df = pd.read_csv(path, encoding="utf-8-sig")
    datasets[name] = df

    print(f"\n===== {name.upper()} =====")
    print(f"이미지 수: {len(df)}")
    print(f"고유 group_id: {df['group_id'].nunique()}")

# 그룹 교집합 검사
train_groups = set(datasets["train"]["group_id"])
val_groups = set(datasets["val"]["group_id"])
test_groups = set(datasets["test"]["group_id"])

print("\n===== 그룹 중복 검사 =====")

checks = {
    "train-val": train_groups & val_groups,
    "train-test": train_groups & test_groups,
    "val-test": val_groups & test_groups,
}

for name, overlap in checks.items():
    print(f"{name} 중복 그룹: {len(overlap)}")

    if overlap:
        print(sorted(overlap))

# 전체 이미지 경로 중복 검사
print("\n===== 이미지 경로 중복 검사 =====")

for name, other in [
    ("train-val", ("train", "val")),
    ("train-test", ("train", "test")),
    ("val-test", ("val", "test")),
]:
    paths_a = set(datasets[other[0]]["path"])
    paths_b = set(datasets[other[1]]["path"])

    print(f"{name} 중복 이미지: {len(paths_a & paths_b)}")

# 전체 데이터 수 확인
total = sum(len(df) for df in datasets.values())

print("\n===== 전체 데이터 확인 =====")
print(f"전체 이미지: {total}")

print("\n===== 검사 완료 =====")
