
from pathlib import Path

import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold


# 프로젝트 경로
PROJECT_ROOT = Path(r"D:\skin-disease-ai")
IMAGE_ROOT = PROJECT_ROOT / "data" / "processed" / "frontal_cropped"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "processed" / "encoded"

OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

# 질환 라벨
LABEL_MAP = {
    "건선": 0,
    "아토피": 1,
    "여드름": 2,
    "정상": 3,
    "주사": 4,
    "지루": 5,
}

# 1. 이미지 목록 수집
records = []

for folder in sorted(IMAGE_ROOT.glob("TS_*_정면")):
    disease = folder.name.replace("TS_", "").replace("_정면", "")

    if disease not in LABEL_MAP:
        continue

    for image_path in folder.glob("*.png"):
        identifier = image_path.stem
        group_id = "_".join(identifier.split("_")[:2])

        records.append({
            "path": str(image_path.resolve()),
            "disease": disease,
            "label": LABEL_MAP[disease],
            "group_id": group_id,
        })

df = pd.DataFrame(records)

if df.empty:
    raise ValueError("정면 이미지가 없습니다. 폴더 경로를 확인하세요.")

if df["path"].duplicated().any():
    raise ValueError("중복 이미지 경로가 발견됐습니다.")

print("===== 정면 데이터 수집 =====")
print(f"전체 이미지: {len(df)}")
print(f"고유 그룹: {df['group_id'].nunique()}")
print("\n질환별 이미지 수:")
print(df["disease"].value_counts().sort_index())


# 2. Train / Test 분리
# 10개 그룹 단위 Fold 중 1개를 Test로 사용
X = df["path"]
y = df["label"]
groups = df["group_id"]

splitter_test = StratifiedGroupKFold(
    n_splits=10,
    shuffle=True,
    random_state=42
)

train_val_idx, test_idx = next(
    splitter_test.split(X, y, groups)
)

train_val_df = df.iloc[train_val_idx].copy()
test_df = df.iloc[test_idx].copy()


# 3. Train / Validation 분리
# 남은 데이터의 1/9을 Validation으로 사용
splitter_val = StratifiedGroupKFold(
    n_splits=9,
    shuffle=True,
    random_state=42
)

train_idx, val_idx = next(
    splitter_val.split(
        train_val_df["path"],
        train_val_df["label"],
        train_val_df["group_id"]
    )
)

train_df = train_val_df.iloc[train_idx].copy()
val_df = train_val_df.iloc[val_idx].copy()


# 4. 그룹 중복 검사
train_groups = set(train_df["group_id"])
val_groups = set(val_df["group_id"])
test_groups = set(test_df["group_id"])

assert train_groups.isdisjoint(val_groups)
assert train_groups.isdisjoint(test_groups)
assert val_groups.isdisjoint(test_groups)

# 전체 이미지가 정확히 한 번씩 분할됐는지 검사
assert len(train_df) + len(val_df) + len(test_df) == len(df)

all_paths = (
    set(train_df["path"])
    | set(val_df["path"])
    | set(test_df["path"])
)

assert len(all_paths) == len(df)


# 5. CSV 저장
columns = ["path", "disease", "label", "group_id"]

train_df[columns].to_csv(
    OUTPUT_ROOT / "frontal_train_grouped.csv",
    index=False,
    encoding="utf-8-sig"
)

val_df[columns].to_csv(
    OUTPUT_ROOT / "frontal_val_grouped.csv",
    index=False,
    encoding="utf-8-sig"
)

test_df[columns].to_csv(
    OUTPUT_ROOT / "frontal_test_grouped.csv",
    index=False,
    encoding="utf-8-sig"
)


# 6. 결과 출력
print("\n===== 그룹 단위 분할 결과 =====")

for name, part in [
    ("Train", train_df),
    ("Validation", val_df),
    ("Test", test_df),
]:
    print(f"\n[{name}]")
    print(f"이미지 수: {len(part)}")
    print(f"고유 그룹 수: {part['group_id'].nunique()}")
    print(part["disease"].value_counts().sort_index())

print("\n===== 그룹 중복 검사 =====")
print(f"Train-Val 중복: {len(train_groups & val_groups)}")
print(f"Train-Test 중복: {len(train_groups & test_groups)}")
print(f"Val-Test 중복: {len(val_groups & test_groups)}")

print("\n정면 데이터 그룹 분할 완료!")
print(f"저장 위치: {OUTPUT_ROOT}")
