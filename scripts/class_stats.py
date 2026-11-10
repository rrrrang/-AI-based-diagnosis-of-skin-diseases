import numpy as np, pandas as pd
from pathlib import Path
from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "outputs"
df = pd.read_csv(OUT / "meta_split.csv", keep_default_na=False)

rows = []
for r in df.itertuples():
    im = Image.open(r.img_path).convert("RGB")
    a = np.asarray(im, dtype=np.float32)
    hsv = np.asarray(im.convert("HSV"), dtype=np.float32)
    gray = a.mean(2)
    center = gray[64:-64, 64:-64].mean()
    edges = [gray[:6].mean(), gray[-6:].mean(), gray[:, :6].mean(), gray[:, -6:].mean()]
    rows.append({"label": r.label, "R": a[..., 0].mean(), "G": a[..., 1].mean(), "B": a[..., 2].mean(),
                 "밝기V": hsv[..., 2].mean(), "채도S": hsv[..., 1].mean(), "대비": gray.std(),
                 "가장자리_이상": max(abs(e - center) for e in edges) > 60})

g = pd.DataFrame(rows)
print(g.groupby("label")[["R", "G", "B", "밝기V", "채도S", "대비"]].mean().round(1))
print("\n가장자리 이상(중앙과 밝기 차 60 초과) 비율:")
print(g.groupby("label")["가장자리_이상"].mean().round(3))