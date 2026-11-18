
from pathlib import Path
import json

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent.parent

MISCLASSIFIED_CSV = (
    PROJECT_DIR / "results" / "frontal_aug_a_validation"
    / "frontal_aug_a_validation_misclassified.csv"
)

VALIDATION_CSV = (
    PROJECT_DIR / "data" / "processed" / "encoded"
    / "frontal_val_grouped.csv"
)

METADATA_CSV = (
    PROJECT_DIR / "data" / "processed" / "encoded"
    / "labeling_metadata.csv"
)

CROP_RESULTS_CSV = (
    PROJECT_DIR / "data" / "processed" / "frontal_cropped"
    / "frontal_crop_results.csv"
)

RESULT_DIR = (
    PROJECT_DIR / "results" / "frontal_aug_a_validation"
)

OUTPUT_CSV = RESULT_DIR / "frontal_aug_a_validation_data_audit.csv"


def normalize_path(value):
    if pd.isna(value):
        return ""

    return str(value).replace("/", "\\").strip().lower()


def collect_json_values(data, target_key):
    """JSON 내부에서 특정 키에 해당하는 모든 값을 재귀적으로 수집한다."""

    values = []

    if isinstance(data, dict):

        for key, value in data.items():

            if str(key).lower() == target_key.lower():
                values.append(value)

            values.extend(
                collect_json_values(value, target_key)
            )

    elif isinstance(data, list):

        for item in data:
            values.extend(
                collect_json_values(item, target_key)
            )

    return values


def first_nonempty(values):
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()

    return ""


def main():

    print("=" * 60)
    print("실험 A 검증 오분류 데이터 연결 검사")
    print("=" * 60)

    for path in [
        MISCLASSIFIED_CSV,
        VALIDATION_CSV,
        METADATA_CSV,
        CROP_RESULTS_CSV,
    ]:
        if not path.is_file():
            raise FileNotFoundError(
                f"필요한 파일이 없습니다: {path}"
            )

    errors = pd.read_csv(MISCLASSIFIED_CSV)
    validation = pd.read_csv(VALIDATION_CSV)
    metadata = pd.read_csv(METADATA_CSV)
    crop_results = pd.read_csv(CROP_RESULTS_CSV)

    required_metadata = {
        "identifier",
        "disease",
        "json_path",
        "diagnosis_name",
        "photograph_file_path",
    }

    missing = required_metadata - set(metadata.columns)

    if missing:
        raise ValueError(
            f"메타데이터 필수 컬럼 누락: {sorted(missing)}"
        )

    if "group_id" not in validation.columns:
        raise ValueError("검증 CSV에 group_id가 없습니다.")

    # 식별자 기준 메타데이터 조회
    metadata["identifier"] = (
        metadata["identifier"].astype(str).str.strip()
    )

    if metadata["identifier"].duplicated().any():
        raise ValueError(
            "메타데이터에 중복 identifier가 있습니다. "
            "임의로 하나를 선택하지 않고 검사를 중단합니다."
        )

    metadata_lookup = metadata.set_index("identifier")

    # 경로 기준 그룹 ID 조회
    validation_lookup = {}

    for _, row in validation.iterrows():
        validation_lookup[
            normalize_path(row["path"])
        ] = row["group_id"]

    # Crop 결과 경로 조회
    crop_lookup = {}

    for _, row in crop_results.iterrows():
        crop_lookup[
            normalize_path(row["crop_path"])
        ] = row

    results = []

    for _, row in errors.iterrows():

        image_path = Path(row["image_path"])
        identifier = image_path.stem

        actual_disease = str(row["actual_disease"])

        result = {
            "identifier": identifier,
            "image_path": str(image_path),
            "actual_disease": actual_disease,
            "predicted_disease": row["predicted_disease"],
            "predicted_probability": row["predicted_probability"],
            "image_exists": image_path.is_file(),
            "metadata_exists": False,
            "json_exists": False,
            "json_valid": False,
            "json_identifier_match": False,
            "metadata_disease_match": False,
            "diagnosis_name_match": False,
            "photograph_filename_match": False,
            "original_image_exists": False,
            "crop_result_match": False,
            "group_id": "",
            "json_error": "",
        }

        # 검증 CSV의 group_id 연결
        result["group_id"] = validation_lookup.get(
            normalize_path(image_path), ""
        )

        # 메타데이터 연결
        if identifier not in metadata_lookup.index:
            results.append(result)
            continue

        meta = metadata_lookup.loc[identifier]

        result["metadata_exists"] = True

        result["metadata_disease_match"] = (
            str(meta["disease"]) == actual_disease
        )

        result["diagnosis_name_match"] = (
            str(meta["diagnosis_name"]) == actual_disease
        )

        # JSON 경로 확인
        json_path = Path(str(meta["json_path"]))

        result["json_exists"] = json_path.is_file()

        if result["json_exists"]:

            try:
                with open(
                    json_path,
                    "r",
                    encoding="utf-8-sig",
                ) as f:
                    json_data = json.load(f)

                result["json_valid"] = True

                identifiers = collect_json_values(
                    json_data, "identifier"
                )

                diagnosis_names = collect_json_values(
                    json_data, "diagnosis_name"
                )

                photograph_paths = collect_json_values(
                    json_data, "file_path"
                )

                result["json_identifier_match"] = (
                    identifier in [str(v) for v in identifiers]
                )

                json_diagnosis = first_nonempty(
                    diagnosis_names
                )

                if json_diagnosis:
                    result["diagnosis_name_match"] = (
                        json_diagnosis == actual_disease
                    )

                metadata_photo = Path(
                    str(meta["photograph_file_path"])
                ).name.lower()

                json_photo_names = [
                    Path(str(v)).name.lower()
                    for v in photograph_paths
                    if v is not None
                ]

                result["photograph_filename_match"] = (
                    metadata_photo in json_photo_names
                    if json_photo_names else False
                )

            except Exception as e:
                result["json_error"] = str(e)

        # Crop 결과 연결
        crop_row = crop_lookup.get(
            normalize_path(image_path)
        )

        if crop_row is not None:

            result["crop_result_match"] = True

            original_path = Path(
                str(crop_row["original_path"])
            )

            result["original_image_exists"] = (
                original_path.is_file()
            )

        results.append(result)

    audit_df = pd.DataFrame(results)

    audit_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # ======================================
    # 결과 출력
    # ======================================

    check_columns = [
        "image_exists",
        "metadata_exists",
        "json_exists",
        "json_valid",
        "json_identifier_match",
        "metadata_disease_match",
        "diagnosis_name_match",
        "photograph_filename_match",
        "original_image_exists",
        "crop_result_match",
    ]

    print("\n===== 검사 결과 =====")
    print(f"검사 이미지: {len(audit_df)}개")

    for column in check_columns:
        count = int(audit_df[column].sum())

        print(
            f"{column}: {count}/{len(audit_df)}"
        )

    print("\n===== 확인이 필요한 항목 =====")

    for column in check_columns:

        failed = audit_df[~audit_df[column]]

        if len(failed) > 0:

            print(f"\n[{column}] {len(failed)}개")

            print(
                failed[
                    ["identifier", "actual_disease",
                     "predicted_disease"]
                ].to_string(index=False)
            )

    print("\n===== 동일 대상자별 오분류 =====")

    grouped = (
        audit_df.groupby("group_id")
        .agg(
            image_count=("identifier", "count"),
            actual_diseases=("actual_disease",
                             lambda x: ", ".join(sorted(set(x)))),
            predicted_diseases=("predicted_disease",
                                lambda x: ", ".join(sorted(set(x)))),
        )
        .sort_values("image_count", ascending=False)
    )

    print(grouped.head(20).to_string())

    print("\n===== 저장 완료 =====")
    print(OUTPUT_CSV)


if __name__ == "__main__":
    main()
