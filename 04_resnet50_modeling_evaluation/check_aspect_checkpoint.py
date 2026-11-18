
import torch
from pathlib import Path

checkpoint_path = Path("models/resnet50_frontal_aspect_best.pth")

print("===== 종횡비 유지 모델 체크포인트 확인 =====")

if not checkpoint_path.exists():
    print("체크포인트 파일을 찾을 수 없습니다.")
    raise SystemExit

checkpoint = torch.load(
    checkpoint_path,
    map_location="cpu",
    weights_only=False
)

print(f"파일 경로: {checkpoint_path}")
print(f"파일 크기: {checkpoint_path.stat().st_size / (1024 * 1024):.2f} MB")

print("\n===== 학습 정보 =====")

for key in [
    "epoch",
    "val_loss",
    "val_accuracy",
    "class_names",
    "input_view"
]:
    print(f"{key}: {checkpoint.get(key, '정보 없음')}")

print("\n===== 모델 가중치 확인 =====")

if "model_state_dict" in checkpoint:
    print("모델 가중치: 정상적으로 존재")
    print(f"가중치 항목 수: {len(checkpoint['model_state_dict'])}")
else:
    print("모델 가중치를 찾을 수 없습니다.")
