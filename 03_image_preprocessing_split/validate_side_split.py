
from pathlib import Path
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENCODED_DIR = PROJECT_DIR / "data" / "processed" / "encoded"

FILES = {
    "Train": ENCODED_DIR / "side_train.csv",
    "Validation": ENCODED_DIR / "side_val.csv",
    "Test": ENCODED_DIR / "side_test.csv",
}

datasets = {}

for name, path in FILES.items():
    datasets[name] = pd.read_csv(path)

# 1. 전체 데이터 합치기
all_df = pd.concat(datasets.values(), ignore_index=True)

# 2. 경로 중복 확인
print("[1. 이미지 경로 중복 확인]")

print("전체 경로 중복:", all_df["path"].duplicated().sum())

for name1, name2 in [
    ("Train", "Validation"),
    ("Train", "Test"),
    ("Validation", "Test")
]:
    overlap = set(datasets[name1]["path"]) & set(datasets[name2]["path"])
    print(f"{name1} - {name2} 중복:", len(overlap))

# 3. SHA256 중복 확인
print("\n[2. SHA256 중복 확인]")

print("전체 SHA256 중복:", all_df["sha256"].duplicated().sum())

# 4. 실제 이미지 경로 확인
print("\n[3. 이미지 파일 존재 여부 확인]")

missing_paths = []

for path in all_df["path"]:
    image_path = PROJECT_DIR / path

    if not image_path.exists():
        missing_paths.append(path)

print("전체 이미지:", len(all_df))
print("누락 이미지:", len(missing_paths))

if missing_paths:
    print("\n누락 이미지 예시:")
    print(missing_paths[:10])

# 5. 촬영 방향 확인
print("\n[4. 촬영 방향 확인]")

front_count = all_df["path"].str.contains("_정면/", na=False).sum()
side_count = all_df["path"].str.contains("_측면/", na=False).sum()

print("정면 이미지:", front_count)
print("측면 이미지:", side_count)

print("\n[검증 완료]")
