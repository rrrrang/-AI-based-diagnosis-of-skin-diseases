
import pandas as pd
from pathlib import Path

BASE_DIR = Path(r"D:\skin-disease-ai")

CSV_PATH = BASE_DIR / "results" / "near_duplicate_candidates.csv"
OUTPUT_PATH = BASE_DIR / "results" / "duplicate_review_list.csv"

df = pd.read_csv(CSV_PATH)

# 해밍 거리 0~5인 후보
high = df[df["hamming_distance"] <= 5]

# 두 이미지 경로를 하나의 목록으로 합치기
images = pd.concat([
    high[["image1", "disease1"]].rename(
        columns={"image1": "path", "disease1": "disease"}
    ),
    high[["image2", "disease2"]].rename(
        columns={"image2": "path", "disease2": "disease"}
    )
])

# 중복 경로 제거
images = images.drop_duplicates(subset=["path"])

images.to_csv(
    OUTPUT_PATH,
    index=False,
    encoding="utf-8-sig"
)

print("중복 후보 쌍:", len(high))
print("중복 후보 이미지 고유 개수:", len(images))
print("저장 위치:", OUTPUT_PATH)
