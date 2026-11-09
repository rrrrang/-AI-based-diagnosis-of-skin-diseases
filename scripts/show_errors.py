import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image

from skin_lib import resolve

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

run_dir = resolve("outputs/runs/final_v0_1")
meta = pd.read_csv(resolve("outputs/meta_split_block.csv"), keep_default_na=False).set_index("id")
test = meta[meta["set"] == "test"]

errs = {}
for sd in sorted(run_dir.glob("seed_*")):
    p = pd.read_csv(sd / "test_predictions.csv", encoding="utf-8-sig")
    for _, r in p[p["label"] != p["pred"]].iterrows():
        errs.setdefault(r["id"], []).append(f"{sd.name[5:]}:{r['pred']}({r['conf']:.2f})")

blk_err = test.loc[test.index.isin(errs), "blk"].value_counts()
print(f"test 블록 {test['blk'].nunique()}개 중 오답 이미지가 있는 블록 {len(blk_err)}개")
for b in blk_err.index:
    print(f"  {b}: test 이미지 {int((test['blk'] == b).sum())}장, 오답 이미지 {int(blk_err[b])}장")
print("오답 이미지 목록:", {k: v for k, v in errs.items()})

ids = list(errs)
fig, axes = plt.subplots(2, len(ids), figsize=(4 * len(ids), 8), squeeze=False)
for j, i in enumerate(ids):
    r = meta.loc[i]
    axes[0, j].imshow(Image.open(r["img_path"]).convert("RGB"))
    axes[0, j].set_title(f"{i}\n정답 {r['label']} -> {', '.join(errs[i])}", fontsize=8)
    same = test[(test["blk"] == r["blk"]) & (test.index != i) & (test["label"] == r["label"])]
    if len(same):
        axes[1, j].imshow(Image.open(same.iloc[0]["img_path"]).convert("RGB"))
        axes[1, j].set_title(f"같은 블록의 다른 {r['label']} 사진\n{same.index[0]}", fontsize=8)
    for ax in axes[:, j]:
        ax.axis("off")
plt.tight_layout()
out = resolve("outputs/error_images.png")
plt.savefig(out, dpi=70)
print("저장:", out)