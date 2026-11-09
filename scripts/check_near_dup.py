import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from PIL import Image

OUT = Path(r"D:\skin_project\outputs")
res = pd.read_csv(OUT / "near_dup_test.csv")
meta = pd.read_csv(OUT / "meta_split.csv", keep_default_na=False)
idx = meta.set_index("id")

close = res[res["dist"] <= 4]
fig, axes = plt.subplots(len(close), 2, figsize=(6, 3 * len(close)))
for i, (_, r) in enumerate(close.iterrows()):
    for j, k in enumerate(["test_id", "closest_id"]):
        axes[i, j].imshow(Image.open(idx.loc[r[k], "img_path"]).convert("RGB"))
        axes[i, j].axis("off")
        axes[i, j].set_title(f"{r[k]} ({idx.loc[r[k], 'label']})", fontsize=7)
plt.tight_layout(); plt.savefig(OUT / "near_dup_pairs.png", dpi=100)

meta["near_dup"] = meta["id"].isin(close["test_id"])
meta.to_csv(OUT / "meta_split.csv", index=False, encoding="utf-8-sig")
print("near_dup 표시:", meta["near_dup"].sum(), "장")