import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image
from pathlib import Path

plt.rcParams["font.family"] = "Malgun Gothic"   # 윈도우 한글 폰트 (없으면 제목이 네모로 깨짐)
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(r"D:\skin_project\outputs")
df = pd.read_csv(OUT / "meta_split.csv", keep_default_na=False)

fig, axes = plt.subplots(6, 8, figsize=(16, 12))
for i, (lab, g) in enumerate(df.groupby("label")):
    for j, (_, r) in enumerate(g.sample(8, random_state=3).iterrows()):
        ax = axes[i, j]
        ax.imshow(Image.open(r["img_path"]).convert("RGB"))
        ax.axis("off")
    axes[i, 0].set_title(lab, fontsize=12, loc="left")

plt.tight_layout()
plt.savefig(OUT / "class_grid.png", dpi=70)
print("저장 완료:", OUT / "class_grid.png")