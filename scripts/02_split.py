import pandas as pd
from pathlib import Path
from sklearn.model_selection import StratifiedGroupKFold

OUT = Path(__file__).resolve().parent.parent / "outputs"
df = pd.read_csv(OUT / "meta.csv", keep_default_na=False)

trainval = df[df["split"] == "Training"].copy()
test = df[df["split"] == "Validation"].copy()

# test와 동일한 이미지가 Training에 있으면 Training에서 제거
overlap = set(trainval["md5"]) & set(test["md5"])
print(f"test와 동일 이미지: {len(overlap)}개 -> Training에서 {trainval['md5'].isin(overlap).sum()}행 제거")
trainval = trainval[~trainval["md5"].isin(overlap)].reset_index(drop=True)

# 같은 이미지(md5)는 같은 쪽으로
sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
tr_idx, va_idx = next(sgkf.split(trainval, trainval["label"], groups=trainval["md5"]))
trainval["set"] = "train"
trainval.loc[va_idx, "set"] = "val"
test["set"] = "test"

final = pd.concat([trainval, test], ignore_index=True)
m = {s: set(final[final.set == s]["md5"]) for s in ["train", "val", "test"]}
assert not (m["train"] & m["val"]) and not (m["train"] & m["test"]) and not (m["val"] & m["test"])

print("\n세트별 개수:\n", final["set"].value_counts())
print("\n세트 × 클래스:\n", pd.crosstab(final["label"], final["set"]))
final.to_csv(OUT / "meta_split.csv", index=False, encoding="utf-8-sig")