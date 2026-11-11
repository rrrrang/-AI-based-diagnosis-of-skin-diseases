
from pathlib import Path

import torch
import torch.nn as nn

from src.dataloader import get_dataloaders
from src.model import create_model


PROJECT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# 정면 Crop 전용 모델 저장 경로
BEST_MODEL_PATH = MODEL_DIR / "resnet50_frontal_crop_best.pth"


# 학습 설정
NUM_EPOCHS = 15
PATIENCE = 5

LAYER4_LEARNING_RATE = 1e-5
FC_LEARNING_RATE = 1e-4

CLASS_NAMES = [
    "건선",
    "아토피",
    "여드름",
    "정상",
    "주사",
    "지루",
]


DEVICE = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)


def set_training_mode(model):
    model.eval()

    # 마지막 특징 추출 블록 학습
    model.layer4.train()

    # 분류층 학습
    model.fc.train()


def run_validation(model, val_loader, criterion):
    model.eval()

    loss_sum = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for images, labels in val_loader:
            images = images.to(DEVICE)
            labels = labels.to(DEVICE)

            outputs = model(images)
            loss = criterion(outputs, labels)

            batch_size = labels.size(0)

            loss_sum += loss.item() * batch_size

            correct += (
                outputs.argmax(dim=1) == labels
            ).sum().item()

            total += batch_size

    return loss_sum / total, correct / total


def main():

    print("===== ResNet50 정면 Crop 모델 학습 =====")
    print(f"실행 장치: {DEVICE}")

    # 1. DataLoader 생성
    train_loader, val_loader, test_loader = get_dataloaders()

    print(f"학습 이미지: {len(train_loader.dataset)}개")
    print(f"검증 이미지: {len(val_loader.dataset)}개")
    print(f"테스트 이미지: {len(test_loader.dataset)}개")

    print("촬영 방향: 정면 Crop")
    print("테스트 데이터는 학습 및 검증에 사용하지 않습니다.")

    # 2. 모델 생성
    model = create_model()
    model = model.to(DEVICE)

    # 3. 마지막 특징 추출 블록과 분류층 학습
    for param in model.layer4.parameters():
        param.requires_grad = True

    for param in model.fc.parameters():
        param.requires_grad = True

    # 4. 손실 함수
    criterion = nn.CrossEntropyLoss()

    # 5. Optimizer
    optimizer = torch.optim.Adam(
        [
            {
                "params": model.layer4.parameters(),
                "lr": LAYER4_LEARNING_RATE,
            },
            {
                "params": model.fc.parameters(),
                "lr": FC_LEARNING_RATE,
            },
        ]
    )

    best_val_loss = float("inf")
    epochs_without_improvement = 0

    # 6. 학습
    for epoch in range(NUM_EPOCHS):

        set_training_mode(model)

        train_loss_sum = 0.0
        train_correct = 0
        train_total = 0

        for images, labels in train_loader:

            images = images.to(DEVICE)
            labels = labels.to(DEVICE)

            optimizer.zero_grad()

            outputs = model(images)
            loss = criterion(outputs, labels)

            loss.backward()
            optimizer.step()

            batch_size = labels.size(0)

            train_loss_sum += loss.item() * batch_size

            train_correct += (
                outputs.argmax(dim=1) == labels
            ).sum().item()

            train_total += batch_size

        train_loss = train_loss_sum / train_total
        train_accuracy = train_correct / train_total

        # 7. 검증
        val_loss, val_accuracy = run_validation(
            model,
            val_loader,
            criterion,
        )

        print(
            f"Epoch [{epoch + 1}/{NUM_EPOCHS}] "
            f"Train Loss: {train_loss:.4f} "
            f"Train Acc: {train_accuracy:.4f} "
            f"Val Loss: {val_loss:.4f} "
            f"Val Acc: {val_accuracy:.4f}"
        )

        # 8. 최적 모델 저장
        if val_loss < best_val_loss:

            best_val_loss = val_loss
            epochs_without_improvement = 0

            torch.save(
                {
                    "epoch": epoch + 1,
                    "model_state_dict": model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "val_loss": val_loss,
                    "val_accuracy": val_accuracy,
                    "class_names": CLASS_NAMES,
                    "input_view": "frontal_crop",
                },
                BEST_MODEL_PATH,
            )

            print("  -> 현재 최적 정면 Crop 모델 저장")

        else:

            epochs_without_improvement += 1

            print(
                f"  -> 검증 손실 개선 없음 "
                f"({epochs_without_improvement}/{PATIENCE})"
            )

        # 9. 조기 종료
        if epochs_without_improvement >= PATIENCE:

            print("조기 종료: 검증 손실이 개선되지 않았습니다.")
            break

    print("\n===== 정면 Crop 모델 학습 완료 =====")
    print(f"최적 검증 손실: {best_val_loss:.4f}")
    print(f"모델 저장 경로: {BEST_MODEL_PATH}")
    print("최종 테스트 평가는 별도 평가 코드로 진행하세요.")


if __name__ == "__main__":
    main()
