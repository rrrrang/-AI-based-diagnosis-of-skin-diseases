import numpy as np, pandas as pd
from pathlib import Path
from PIL import Image
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix

OUT = Path(__file__).resolve().parent.parent / "outputs"
base = pd.read_csv(OUT / "meta_split.csv", keep_default_na=False)
blk = pd.read_csv(OUT / "meta_split_block.csv", keep_default_na=False)[["id", "set"]].rename(columns={"set": "set_block"})
df = base.merge(blk, on="id")

def feats(p):
    im = Image.open(p).convert("RGB")
    a = np.asarray(im, dtype=np.float32) / 255
    color = np.concatenate([a.mean((0, 1)), a.std((0, 1)),
                            *[np.histogram(a[..., c], bins=8, range=(0, 1))[0] / a[..., c].size for c in range(3)]])
    meta = np.array([Path(p).stat().st_size, im.width, im.height], dtype=np.float32)
    tiny = np.asarray(im.resize((16, 16)), dtype=np.float32).ravel() / 255
    return color, meta, tiny

F = [feats(p) for p in df["img_path"]]
sets = {"색 통계만": np.stack([f[0] for f in F]),
        "파일 크기+해상도만": np.stack([f[1] for f in F]),
        "16x16 축소 이미지": np.stack([f[2] for f in F])}
y = df["label_id"].to_numpy()
names = [k for k, _ in sorted(pd.read_json(OUT / "label2id.json", typ="series").items(), key=lambda kv: kv[1])]

for split_col, title in [("set", "기존 분할(무작위)"), ("set_block", "블록 분할(ID 인접 묶음)")]:
    tr, te = (df[split_col] == "train").to_numpy(), (df[split_col] == "test").to_numpy()
    print(f"\n=== {title} ===")
    for name, X in sets.items():
        clf = RandomForestClassifier(300, n_jobs=-1, random_state=0).fit(X[tr], y[tr])
        pred = clf.predict(X[te])
        print(f"{name}: test 정확도 {(pred == y[te]).mean():.3f}")
        if name == "16x16 축소 이미지":
            cm = confusion_matrix(y[te], pred)
            print("  클래스별 recall:", {n: round(cm[i, i] / cm[i].sum(), 2) for i, n in enumerate(names)})
