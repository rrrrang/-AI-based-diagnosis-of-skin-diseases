import pandas as pd
df = pd.read_csv(r"D:\skin_project\outputs\meta_split.csv", keep_default_na=False)

# 1) 그룹 추출에 실패한 ID의 형태
bad = df[~df["id"].str.match(r"^H\d+_\d+_P")]
print(bad.groupby("label")["id"].agg(["count", "first", "last"]))
print(bad["id"].sample(15, random_state=0).tolist())
print("해상도:", bad["real_w"].value_counts().to_dict())
print("성별:", bad["gender"].value_counts().to_dict())
print("split:", bad["split"].value_counts().to_dict())

# 2) 겹치는 케이스
g = df["id"].str.extract(r"^(H\d+_\d+)_P")[0].fillna(df["id"])
df["group"] = g
tr = set(df[df.split == "Training"]["group"]); te = set(df[df.split == "Validation"]["group"])
ov = tr & te
print(df[df["group"].isin(ov)][["id", "label", "split", "set"]])