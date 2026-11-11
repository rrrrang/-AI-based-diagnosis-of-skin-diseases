
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent.parent
ENCODED_DIR = PROJECT_DIR / "data" / "processed" / "encoded"

EXPECTED_TOTAL = 9571

LABEL_MAP = {
    "건선": 0,
    "아토피": 1,
    "여드름": 2,
    "정상": 3,
    "주사": 4,
    "지루": 5,
}


def main():
    split_names = ["train", "val", "test"]
    all_paths = {}
    all_hashes = {}
    errors = []

    total_rows = 0

    print("===== 최종 데이터 가공 검증 =====")

    for split_name in split_names:
        csv_path = ENCODED_DIR / f"{split_name}.csv"

        if not csv_path.exists():
            errors.append(f"CSV 파일이 없습니다: {csv_path}")
            continue

        df = pd.read_csv(csv_path)
        total_rows += len(df)

        required = {"path", "disease", "label", "sha256"}
        missing = required - set(df.columns)

        if missing:
            errors.append(
                f"{split_name}: 필수 열 누락 {sorted(missing)}"
            )
            continue

        # 필수 값 확인
        if df[list(required)].isna().any().any():
            errors.append(f"{split_name}: 필수 값에 결측치가 있습니다.")

        # 질환명과 숫자 라벨 일치 여부
        expected_labels = df["disease"].map(LABEL_MAP)

        if expected_labels.isna().any():
            errors.append(f"{split_name}: 알 수 없는 질환명이 있습니다.")
        elif not expected_labels.equals(df["label"].astype(int)):
            errors.append(f"{split_name}: 질환명과 숫자 라벨이 불일치합니다.")

        # 각 이미지 경로 확인
        missing_files = [
            path for path in df["path"]
            if not (PROJECT_DIR / path).is_file()
        ]

        if missing_files:
            errors.append(
                f"{split_name}: 존재하지 않는 이미지 {len(missing_files)}개"
            )

        # CSV 내부 경로 중복 확인
        if df["path"].duplicated().any():
            errors.append(f"{split_name}: 중복 경로가 있습니다.")

        # CSV 내부 SHA-256 중복 확인
        if df["sha256"].duplicated().any():
            errors.append(f"{split_name}: 중복 SHA-256이 있습니다.")

        all_paths[split_name] = set(df["path"])
        all_hashes[split_name] = set(df["sha256"])

        print(f"\n[{split_name}]")
        print(f"행 수: {len(df)}")
        print("질환별 이미지 수:")
        print(df["disease"].value_counts().sort_index().to_string())

    # 전체 행 수 확인
    print("\n===== 전체 검증 =====")
    print(f"전체 행 수: {total_rows}")
    print(f"기대 행 수: {EXPECTED_TOTAL}")

    if total_rows != EXPECTED_TOTAL:
        errors.append("전체 행 수가 기대값과 다릅니다.")

    # 데이터셋 간 경로 및 SHA-256 중복 확인
    for i, first in enumerate(split_names):
        for second in split_names[i + 1:]:
            if first not in all_paths or second not in all_paths:
                continue

            path_overlap = all_paths[first] & all_paths[second]
            hash_overlap = all_hashes[first] & all_hashes[second]

            print(f"{first}-{second} 경로 중복: {len(path_overlap)}")
            print(f"{first}-{second} SHA-256 중복: {len(hash_overlap)}")

            if path_overlap:
                errors.append(f"{first}-{second}: 경로 중복이 있습니다.")

            if hash_overlap:
                errors.append(f"{first}-{second}: SHA-256 중복이 있습니다.")

    print("\n===== 최종 판정 =====")

    if errors:
        print(f"검사 실패: {len(errors)}건")
        for error in errors:
            print("-", error)
    else:
        print("모든 검사를 통과했습니다.")
        print("데이터 정제 및 가공 결과를 사용할 수 있습니다.")
        print("단, 환자 단위 데이터 누수까지 검증한 것은 아닙니다.")


if __name__ == "__main__":
    main()
