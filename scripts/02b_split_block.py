import pandas as pd
from pathlib import Path
from sklearn.model_selection import StratifiedGroupKFold

OUT = Path(__file__).resolve().parent.parent / "outputs"
df = pd.read_csv(OUT / "meta_split.csv", keep_default_na=False)
df["num"] = df["id"].str.extract(r"Z4_(\d+)_")[0].astype(int)
df["blk"] = df["label"] + "_" + (df["num"] // 50).astype(str)   # ID가 가까운 이미지끼리 한 그룹

s1 = StratifiedGroupKFold(n_splits=9, shuffle=True, random_state=0)
rest_idx, test_idx = next(s1.split(df, df["label"], groups=df["blk"]))
rest = df.iloc[rest_idx]
s2 = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=0)
tr_i, va_i = next(s2.split(rest, rest["label"], groups=rest["blk"]))

df["set"] = "train"
df.loc[df.index[test_idx], "set"] = "test"
df.loc[rest.index[va_i], "set"] = "val"
for s in ["test", "val"]:
    ms = set(df[df["set"] == s]["md5"])
    df = df[~((df["set"] == "train") & df["md5"].isin(ms))]
dup = set(df[df["set"] == "val"]["md5"]) & set(df[df["set"] == "test"]["md5"])
df = df[~((df["set"] == "val") & df["md5"].isin(dup))]
print(pd.crosstab(df["label"], df["set"]))
df.to_csv(OUT / "meta_split_block.csv", index=False, encoding="utf-8-sig")