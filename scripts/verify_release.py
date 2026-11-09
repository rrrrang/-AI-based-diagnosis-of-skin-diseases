import json
import sys

from skin_lib import PROJECT_ROOT, sha256_file

man = json.load(open(PROJECT_ROOT / "model" / "manifest.json", encoding="utf-8"))
bad = [k for k, v in man["files"].items()
       if not (PROJECT_ROOT / k).exists() or sha256_file(PROJECT_ROOT / k) != v["sha256"]]
print("OK: 모든 파일 해시 일치" if not bad else f"불일치 또는 누락: {bad}")
sys.exit(1 if bad else 0)