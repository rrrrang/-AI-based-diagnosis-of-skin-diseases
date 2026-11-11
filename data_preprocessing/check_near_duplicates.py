
from pathlib import Path
from itertools import combinations

import pandas as pd
import imagehash
from PIL import Image


# 프로젝트 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 입력 파일
INPUT_CSV = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "encoded"
    / "side_only_clean.csv"
)

# 결과 폴더
RESULT_DIR = PROJECT_ROOT / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# 결과 파일
PHASH_OUTPUT = RESULT_DIR / "phash_metadata.csv"
CANDIDATE_OUTPUT = RESULT_DIR / "near_duplicate_candidates.csv"

# 유사 이미지 기준
THRESHOLD = 10


def calculate_phash(image_path):
    """이미지의 pHash 계산"""
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            return str(imagehash.phash(img, hash_size=8))
    except Exception as e:
        print(f"이미지 처리 오류: {image_path} / {e}")
        return None


def main():
    df = pd.read_csv(INPUT_CSV)

    print(f"전체 데이터: {len(df)}")

    # 이미지별 pHash 계산
    records = []

    for idx, row in df.iterrows():
        image_path = Path(row["path"])

        if not image_path.is_absolute():
            image_path = PROJECT_ROOT / image_path

        if not image_path.exists():
            print(f"파일 없음: {image_path}")
            continue

        phash = calculate_phash(image_path)

        if phash is None:
            continue

        records.append({
            "path": str(row["path"]),
            "disease": row["disease"],
            "phash": phash
        })

    phash_df = pd.DataFrame(records)

    phash_df.to_csv(
        PHASH_OUTPUT,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\n정상 처리 이미지: {len(phash_df)}")
    print(f"pHash 저장: {PHASH_OUTPUT}")

    # 유사 이미지 쌍 비교
    candidates = []

    for (idx1, row1), (idx2, row2) in combinations(
        phash_df.iterrows(), 2
    ):
        hash1 = imagehash.hex_to_hash(row1["phash"])
        hash2 = imagehash.hex_to_hash(row2["phash"])

        distance = hash1 - hash2

        if distance <= THRESHOLD:
            candidates.append({
                "path_1": row1["path"],
                "path_2": row2["path"],
                "disease_1": row1["disease"],
                "disease_2": row2["disease"],
                "hamming_distance": distance,
                "cross_disease": (
                    row1["disease"] != row2["disease"]
                )
            })

    candidate_df = pd.DataFrame(candidates)

    candidate_df.to_csv(
        CANDIDATE_OUTPUT,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n===== pHash 분석 결과 =====")
    print(f"비교 이미지 수: {len(phash_df)}")
    print(f"유사 이미지 후보: {len(candidate_df)}")

    if not candidate_df.empty:
        print(
            "\n해밍 거리 0~5:",
            len(candidate_df[
                candidate_df["hamming_distance"] <= 5
            ])
        )

        print(
            "해밍 거리 6~10:",
            len(candidate_df[
                candidate_df["hamming_distance"].between(6, 10)
            ])
        )

        print(
            "질환 간 후보:",
            candidate_df["cross_disease"].sum()
        )

    print(f"\npHash 결과 저장: {PHASH_OUTPUT}")
    print(f"유사 이미지 후보 저장: {CANDIDATE_OUTPUT}")


if __name__ == "__main__":
    main()
