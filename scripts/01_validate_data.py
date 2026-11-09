import json, hashlib
from pathlib import Path
import pandas as pd
from PIL import Image

ROOT = Path(r"D:\skin_project\data")
OUT = Path(r"D:\skin_project\outputs"); OUT.mkdir(exist_ok=True)
IMG_EXTS = {".png", ".jpg", ".jpeg"}

# 1. JSON 파싱 (Z4_ 측면만)
rows, problems = [], []
for split in ["Training", "Validation"]:
    for jf in (ROOT / split / "02.라벨링데이터").rglob("*.json"):
        if not jf.stem.startswith("Z4_"):
            continue
        try:
            with open(jf, encoding="utf-8") as f:
                a = json.load(f)["annotations"][0]
        except Exception as e:
            problems.append({"split": split, "file": jf.name, "issue": f"JSON 로드 실패: {e}"})
            continue
        d, p = a.get("diagnosis_info") or {}, a.get("photograph") or {}
        label, rel = d.get("diagnosis_name"), p.get("file_path", "")
        parts = rel.split("/")                       # 예: 건선/측면/Z4_xxx.png
        if not label:
            problems.append({"split": split, "file": jf.name, "issue": "diagnosis_name 없음"}); continue
        if len(parts) < 2 or parts[1] != "측면":
            problems.append({"split": split, "file": jf.name, "issue": f"측면 경로 아님: {rel}"})
        if parts[0] != label:
            problems.append({"split": split, "file": jf.name, "issue": f"라벨/폴더 불일치: {label} vs {parts[0]}"})
        rows.append({
            "split": split, "id": a.get("identifier", jf.stem), "label": label,
            "onset": d.get("onset"), "distribution": d.get("distribution"), "symptom": d.get("symptom"),
            "json_w": p.get("width"), "json_h": p.get("height"),
        })

df = pd.DataFrame(rows)
print(f"[1] 측면 JSON: {len(df)}개 / 문제 {len(problems)}건")
print(df.groupby(["label", "split"]).size().unstack())

# 2. 이미지 찾기 (파일명 기준)
img_index = {}
for split in ["Training", "Validation"]:
    for p in (ROOT / split / "01.원천데이터").rglob("*"):
        if p.suffix.lower() in IMG_EXTS and p.stem.startswith("Z4_"):
            img_index[(split, p.stem)] = p
df["img_path"] = df.apply(lambda r: img_index.get((r.split, r.id)), axis=1)
df["img_exists"] = df["img_path"].notna()
print(f"\n[2] 이미지 매칭: {df['img_exists'].sum()} / {len(df)}")

# 3. 이미지 검사 + 해시
info = []
for r in df.itertuples():
    if not r.img_exists:
        info.append((None, None, None, False, None)); continue
    try:
        with Image.open(r.img_path) as im:
            w, h, mode = im.width, im.height, im.mode
        with Image.open(r.img_path) as im:
            im.verify()
        md5 = hashlib.md5(Path(r.img_path).read_bytes()).hexdigest()
        info.append((w, h, mode, False, md5))
    except Exception:
        info.append((None, None, None, True, None))
df[["real_w", "real_h", "mode", "broken", "md5"]] = pd.DataFrame(info, index=df.index)
df["size_mismatch"] = df["img_exists"] & ((df["real_w"] != df["json_w"]) | (df["real_h"] != df["json_h"]))
print(f"\n[3] 손상 {df['broken'].sum()}건 / 크기 불일치 {df['size_mismatch'].sum()}건")
print("    해상도:", df.groupby(['real_w', 'real_h']).size().to_dict(), "/ 모드:", df['mode'].value_counts().to_dict())

# 4. 중복 점검 (동일 이미지)
dup = df[df.duplicated("md5", keep=False) & df["md5"].notna()]
print(f"\n[4] id 중복: {df.duplicated(['split','id']).sum()}건 / 동일 이미지(해시 중복): {len(dup)}장")
if len(dup):
    conflict = dup.groupby("md5")["label"].nunique()
    print("    같은 이미지인데 라벨이 다른 경우:", (conflict > 1).sum(), "건")
    print("    Training/Validation에 걸친 중복:", (dup.groupby("md5")["split"].nunique() > 1).sum(), "건")

# 5. ID 번호 분포 (split이 번호 구간으로 갈렸는지, 무작위로 섞였는지 참고)
df["num"] = df["id"].str.extract(r"Z4_(\d+)_")[0].astype("Int64")
print("\n[5] 클래스·split별 ID 번호 범위:")
print(df.groupby(["label", "split"])["num"].agg(["min", "max"]).unstack())

# 6. 저장
valid = df[df["img_exists"] & ~df["broken"]].copy()
classes = sorted(valid["label"].unique())
label2id = {c: i for i, c in enumerate(classes)}
valid["label_id"] = valid["label"].map(label2id)
valid["img_path"] = valid["img_path"].astype(str)
valid.to_csv(OUT / "meta.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(problems).to_csv(OUT / "json_problems.csv", index=False, encoding="utf-8-sig")
json.dump(label2id, open(OUT / "label2id.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n[6] 저장: 사용 가능 {len(valid)}개 / 클래스 {len(classes)}개 -> {OUT}")