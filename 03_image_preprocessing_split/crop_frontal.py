
from pathlib import Path
import csv

import cv2
import mediapipe as mp
import numpy as np


# ==========================================
# 1. 경로 및 설정
# ==========================================

PROJECT_DIR = Path(__file__).resolve().parent.parent

IMAGE_DIR = PROJECT_DIR / "data" / "processed" / "images"

OUTPUT_DIR = PROJECT_DIR / "data" / "processed" / "frontal_cropped"

RESULT_CSV = OUTPUT_DIR / "frontal_crop_results.csv"

DISEASES = [
    "건선",
    "아토피",
    "여드름",
    "정상",
    "주사",
    "지루"
]

PADDING_RATIO = 0.20
MIN_DETECTION_CONFIDENCE = 0.5

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


# ==========================================
# 2. 한글 경로 이미지 읽기
# ==========================================

def read_image(path):

    image_array = np.fromfile(
        str(path),
        dtype=np.uint8
    )

    if image_array.size == 0:
        return None

    return cv2.imdecode(
        image_array,
        cv2.IMREAD_COLOR
    )


# ==========================================
# 3. 한글 경로 이미지 저장
# ==========================================

def save_image(path, image):

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    success, encoded_image = cv2.imencode(
        path.suffix,
        image
    )

    if success:
        encoded_image.tofile(str(path))

    return success


# ==========================================
# 4. 얼굴 Crop
# ==========================================

def crop_face(image, detection):

    height, width = image.shape[:2]

    bbox = detection.location_data.relative_bounding_box

    x = int(bbox.xmin * width)
    y = int(bbox.ymin * height)

    w = int(bbox.width * width)
    h = int(bbox.height * height)

    if w <= 0 or h <= 0:
        return None, None

    # 얼굴 주변 여백
    padding_x = int(w * PADDING_RATIO)
    padding_y = int(h * PADDING_RATIO)

    x1 = max(0, x - padding_x)
    y1 = max(0, y - padding_y)

    x2 = min(width, x + w + padding_x)
    y2 = min(height, y + h + padding_y)

    if x2 <= x1 or y2 <= y1:
        return None, None

    cropped = image[y1:y2, x1:x2]

    if cropped.size == 0:
        return None, None

    return cropped, {
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2
    }


# ==========================================
# 5. CSV 저장
# ==========================================

def save_results(results):

    fieldnames = [
        "disease",
        "filename",
        "original_path",
        "crop_path",
        "status",
        "confidence",
        "original_width",
        "original_height",
        "crop_width",
        "crop_height",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "error"
    ]

    with open(
        RESULT_CSV,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(results)


# ==========================================
# 6. 전체 정면 이미지 Crop
# ==========================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    results = []

    total_count = 0
    success_count = 0
    fail_count = 0

    mp_face = mp.solutions.face_detection

    with mp_face.FaceDetection(
        model_selection=0,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE
    ) as detector:

        for disease in DISEASES:

            print(f"\n[{disease}] 정면 이미지 처리 시작")

            image_folder = IMAGE_DIR / f"TS_{disease}_정면"

            if not image_folder.exists():
                print(f"폴더 없음: {image_folder}")
                continue

            # 질환별 별도 결과 폴더
            crop_folder = (
                OUTPUT_DIR / f"TS_{disease}_정면"
            )

            crop_folder.mkdir(
                parents=True,
                exist_ok=True
            )

            image_files = sorted([
                file for file in image_folder.iterdir()
                if file.is_file()
                and file.suffix.lower() in IMAGE_EXTENSIONS
            ])

            print(f"대상 이미지: {len(image_files)}장")

            disease_success = 0
            disease_fail = 0

            for index, image_path in enumerate(image_files, start=1):

                total_count += 1

                result = {
                    "disease": disease,
                    "filename": image_path.name,
                    "original_path": str(image_path),
                    "crop_path": "",
                    "status": "FAIL",
                    "confidence": "",
                    "original_width": "",
                    "original_height": "",
                    "crop_width": "",
                    "crop_height": "",
                    "bbox_x1": "",
                    "bbox_y1": "",
                    "bbox_x2": "",
                    "bbox_y2": "",
                    "error": ""
                }

                try:

                    image = read_image(image_path)

                    if image is None:

                        result["status"] = "READ_FAIL"

                        disease_fail += 1
                        fail_count += 1
                        results.append(result)

                        continue

                    height, width = image.shape[:2]

                    result["original_width"] = width
                    result["original_height"] = height

                    rgb_image = cv2.cvtColor(
                        image,
                        cv2.COLOR_BGR2RGB
                    )

                    detection_result = detector.process(
                        rgb_image
                    )

                    if not detection_result.detections:

                        result["status"] = "NO_FACE"

                        disease_fail += 1
                        fail_count += 1
                        results.append(result)

                        continue

                    # 가장 신뢰도가 높은 얼굴 선택
                    best_detection = max(
                        detection_result.detections,
                        key=lambda d: d.score[0]
                    )

                    confidence = float(
                        best_detection.score[0]
                    )

                    cropped, bbox_info = crop_face(
                        image,
                        best_detection
                    )

                    if cropped is None:

                        result["status"] = "CROP_FAIL"

                        disease_fail += 1
                        fail_count += 1
                        results.append(result)

                        continue

                    crop_path = crop_folder / image_path.name

                    saved = save_image(
                        crop_path,
                        cropped
                    )

                    if not saved:

                        result["status"] = "SAVE_FAIL"

                        disease_fail += 1
                        fail_count += 1
                        results.append(result)

                        continue

                    crop_height, crop_width = cropped.shape[:2]

                    result.update({
                        "crop_path": str(crop_path),
                        "status": "SUCCESS",
                        "confidence": confidence,
                        "crop_width": crop_width,
                        "crop_height": crop_height,
                        "bbox_x1": bbox_info["x1"],
                        "bbox_y1": bbox_info["y1"],
                        "bbox_x2": bbox_info["x2"],
                        "bbox_y2": bbox_info["y2"]
                    })

                    disease_success += 1
                    success_count += 1

                    results.append(result)

                except Exception as e:

                    result["status"] = "ERROR"
                    result["error"] = str(e)

                    disease_fail += 1
                    fail_count += 1

                    results.append(result)

                # 100장마다 진행 상황 출력
                if index % 100 == 0:

                    print(
                        f"진행: {index}/{len(image_files)} "
                        f"| 성공: {disease_success} "
                        f"| 실패: {disease_fail}"
                    )

            print(
                f"[{disease}] 완료 "
                f"| 성공: {disease_success} "
                f"| 실패: {disease_fail}"
            )

    # 전체 결과 CSV 저장
    save_results(results)

    # 최종 결과 출력
    print("\n========== 전체 Crop 결과 ==========")

    print(f"전체 이미지: {total_count}")
    print(f"Crop 성공: {success_count}")
    print(f"실패: {fail_count}")

    if total_count > 0:

        success_rate = (
            success_count / total_count
        ) * 100

        print(f"성공률: {success_rate:.2f}%")

    print(f"결과 폴더: {OUTPUT_DIR}")
    print(f"결과 CSV: {RESULT_CSV}")

    print("====================================")


if __name__ == "__main__":
    main()
