import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image

from inference_core import Predictor, OUT

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

P = Predictor(threshold=0.0)
te = pd.read_csv(OUT / "meta_split_block.csv", keep_default_na=False).query("set == 'test'")

fig, axes = plt.subplots(6, 8, figsize=(20, 15))      # 클래스당 4장 x (원본, Grad-CAM)
for i, (lab, g) in enumerate(te.groupby("label")):
    for j, (_, r) in enumerate(g.sample(4, random_state=1).iterrows()):
        img = Image.open(r["img_path"])
        res = P.predict(img, with_cam=True)
        axes[i, 2 * j].imshow(img.convert("RGB").resize((224, 224)))
        axes[i, 2 * j + 1].imshow(res["overlay"])
        axes[i, 2 * j].set_title(f"정답 {lab}", fontsize=9)
        axes[i, 2 * j + 1].set_title(f"예측 {res['pred']} {res['conf'] * 100:.0f}%", fontsize=9)
for ax in axes.ravel():
    ax.axis("off")
plt.tight_layout()
plt.savefig(OUT / "cam_grid.png", dpi=70)
print("저장:", OUT / "cam_grid.png")