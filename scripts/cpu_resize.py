# scripts/resize_cache.py
import pandas as pd
from pathlib import Path
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

OUT = Path(r"D:\skin_project\outputs")
CACHE = Path(r"D:\skin_project\cache256")
CACHE.mkdir(exist_ok=True)

df = pd.read_csv(OUT / "meta_split.csv", keep_default_na=False)

def convert(row):
    dst = CACHE / f"{row['id']}.jpg"
    if not dst.exists():
        Image.open(row["img_path"]).convert("RGB").resize((256, 256), Image.BICUBIC).save(dst, quality=95)
    return str(dst)

with ThreadPoolExecutor(8) as ex:
    df["img_path"] = list(ex.map(convert, [r for _, r in df.iterrows()]))

df.to_csv(OUT / "meta_split_256.csv", index=False, encoding="utf-8-sig")
print("완료:", len(df))