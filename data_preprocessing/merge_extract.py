"""AI Hub 분할 zip(.zip.partN) 병합 후 압축 해제
사용 예: python src\merge_extract.py source   (원천데이터, 기본값)
        python src\merge_extract.py label    (라벨링데이터)
"""
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

BASE = Path(r"D:\skin-disease-ai\data")
RAW = BASE / "raw"
KINDS = {
    "source": ("01.원천데이터", BASE / "merged_zip", BASE / "processed" / "images"),
    "label": ("02.라벨링데이터", BASE / "merged_zip_label", BASE / "processed" / "labels"),
}
GIB = 1024 ** 3

kind = sys.argv[1] if len(sys.argv) > 1 else "source"
folder, MERGED, OUT = KINDS[kind]

pat = re.compile(r"^(?P<name>.+\.zip)\.part(?P<off>\d+)$")
groups = defaultdict(list)
for p in RAW.rglob("*"):
    m = pat.match(p.name)
    if m and folder in p.parts:
        groups[m["name"]].append((int(m["off"]), p))

print(f"[{kind}] zip {len(groups)}개 발견")
MERGED.mkdir(parents=True, exist_ok=True)
for name, parts in sorted(groups.items()):
    uniq, bad = {}, False
    for o, p in sorted(parts):
        if o in uniq and uniq[o].stat().st_size != p.stat().st_size:
            bad = True
        uniq.setdefault(o, p)
    if bad:
        print(f"[경고] {name}: 중복 파트 크기 불일치")
        continue
    parts = sorted(uniq.items())
    offsets = [o for o, _ in parts]
    if offsets != [i * GIB for i in range(len(parts))]:
        print(f"[경고] {name}: 파트 누락 의심 {offsets}")
        continue
    target = OUT / name[:-4]
    if target.exists():
        print(f"[skip] {name}")
        continue
    zpath = MERGED / name
    with open(zpath, "wb") as w:
        for _, p in parts:
            with open(p, "rb") as r:
                shutil.copyfileobj(r, w, 16 * 1024 * 1024)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(target)
    print(f"[완료] {name} ({len(parts)}개 파트)")
