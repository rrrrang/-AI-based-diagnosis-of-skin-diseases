
from pathlib import Path
from collections import Counter

import pandas as pd
from PIL import Image

# 프로젝트 경로
PROJECT_DIR = Path(__file__).resolve().parent.parent

# 중복 제거가 완료된 메타데이터
METADATA_PATH = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "quality_check"
    / "metadata_deduplicated.csv"
)

df = pd.read_csv(METADATA_PATH)

size_counts = Counter()
mode_counts = Counter()
error_files = []

for relative_path in df["path"]:
    image_path = PROJECT_DIR / relative_path

    try:
        with Image.open(image_path) as img:
            size_counts[img.size] += 1
            mode_counts[img.mode] += 1

    except Exception as e:
        error_files.append({
            "path": relative_path,
            "error": str(e)
        })

print("===== 이미지 크기 분포 =====")
for size, count in size_counts.most_common():
    print(f"{size}: {count}개")

print("\n===== 색상 모드 분포 =====")
for mode, count in mode_counts.most_common():
    print(f"{mode}: {count}개")

print("\n===== 이미지 열기 오류 =====")
print(f"오류 파일 수: {len(error_files)}")

if error_files:
    print(pd.DataFrame(error_files).to_string(index=False))
