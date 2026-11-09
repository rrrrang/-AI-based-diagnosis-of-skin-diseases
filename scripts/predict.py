import argparse
import csv
from pathlib import Path

from PIL import Image

from inference_core import Predictor, decision_text

EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def main():
    ap = argparse.ArgumentParser(description="피부 질환 분류 추론")
    ap.add_argument("--image", help="사진 1장 경로")
    ap.add_argument("--folder", help="폴더 안의 모든 사진을 일괄 추론")
    ap.add_argument("--cam", help="Grad-CAM 저장 경로 (단일: 파일명.png / 폴더 모드: 저장할 폴더)")
    ap.add_argument("--threshold", type=float, help="판단 불가 기준 (미지정 시 threshold.json)")
    ap.add_argument("--out", default="predictions.csv", help="폴더 모드 결과 CSV")
    args = ap.parse_args()
    if not args.image and not args.folder:
        ap.error("--image 또는 --folder 중 하나는 필요합니다")

    P = Predictor(threshold=args.threshold)
    print(f"판단 불가 기준: {P.threshold:.2f}\n")

    if args.image:
        r = P.predict(Image.open(args.image), with_cam=bool(args.cam))
        print("파일:", args.image)
        print("상위 3개:", " | ".join(f"{n} {p * 100:.1f}%" for n, p in r["top3"]))
        print("판정:", decision_text(r, md=False))
        for w in r["warnings"]:
            print("주의:", w)
        if args.cam and r["overlay"] is not None:
            r["overlay"].save(args.cam)
            print(f"Grad-CAM({r['cam_class']} 기준) 저장:", args.cam)
        return

    files = sorted(p for p in Path(args.folder).rglob("*") if p.suffix.lower() in EXTS)
    cam_dir = Path(args.cam) if args.cam else None
    if cam_dir:
        cam_dir.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["file", "pred", "conf", "accepted", "top3"])
        for p in files:
            try:
                r = P.predict(Image.open(p), with_cam=cam_dir is not None)
            except Exception as e:
                print("실패:", p.name, e)
                continue
            wr.writerow([str(p), r["pred"], f"{r['conf']:.4f}", int(r["accepted"]),
                         " | ".join(f"{n} {v * 100:.1f}%" for n, v in r["top3"])])
            if cam_dir and r["overlay"] is not None:
                r["overlay"].save(cam_dir / f"{p.stem}_cam.png")
    print(f"{len(files)}장 처리 -> {args.out}")


if __name__ == "__main__":
    main()