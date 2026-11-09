import numpy as np, pandas as pd
from PIL import Image

df = pd.read_csv(r"D:\skin_project\outputs\meta.csv")

# 1) 해상도 × 클래스
print(pd.crosstab(df["label"], df["real_w"]))
print(pd.crosstab(df["split"], df["real_w"]))

# 2) 알파 채널 확인 (클래스별 20장 샘플)
res = []
for r in df.groupby("label").sample(20, random_state=0).itertuples():
    a = np.array(Image.open(r.img_path))[..., 3]
    res.append({"label": r.label, "res": r.real_w, "alpha_min": a.min(), "transparent_ratio": (a < 255).mean()})
print(pd.DataFrame(res).groupby(["label", "res"]).agg(["min", "max"]))

# 3) case_id 없는 id 형태와 case_id 유무 × 클래스
df["has_case"] = df["case_id"].notna()
print(pd.crosstab(df["label"], df["has_case"]))
print(df[~df["has_case"]].groupby("label")["id"].first())
print(df[df["gender"] == "N/A"].groupby("label").size())   # N/A가 어느 클래스에 몰려 있는지

# 4) 클래스별 샘플 눈으로 확인 (해상도별 구분)
import matplotlib.pyplot as plt
fig, axes = plt.subplots(6, 6, figsize=(14, 14))
for i, (lab, g) in enumerate(df.groupby("label")):
    for j, (_, r) in enumerate(g.sample(6, random_state=1).iterrows()):
        ax = axes[i, j]
        ax.imshow(Image.open(r.img_path).convert("RGB")); ax.axis("off")
        ax.set_title(f"{lab} {int(r.real_w)}", fontsize=8)
plt.tight_layout(); plt.savefig(r"D:\skin_project\outputs\sample_grid.png", dpi=80)