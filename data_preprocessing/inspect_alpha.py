
from pathlib import Path

import pandas as pd
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parent.parent

METADATA_PATH = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "quality_check"
    / "metadata_deduplicated.csv"
)

df = pd.read_csv(METADATA_PATH)

fully_opaque = 0
has_transparency = 0
alpha_errors = []

for relative_path in df["path"]:
    image_path = PROJECT_DIR / relative_path

    try:
        with Image.open(image_path) as img:
            rgba = img.convert("RGBA")
            alpha = rgba.getchannel("A")
            alpha_min, alpha_max = alpha.getextrema()

            if alpha_min == 255 and alpha_max == 255:
                fully_opaque += 1
            else:
                has_transparency += 1

    except Exception as e:
        alpha_errors.append({
            "path": relative_path,
            "error": str(e)
        })

print("===== 투명도 검사 결과 =====")
print(f"완전히 불투명한 이미지: {fully_opaque}개")
print(f"투명 픽셀이 있는 이미지: {has_transparency}개")
print(f"검사 오류: {len(alpha_errors)}개")

if alpha_errors:
    print(pd.DataFrame(alpha_errors).to_string(index=False))
