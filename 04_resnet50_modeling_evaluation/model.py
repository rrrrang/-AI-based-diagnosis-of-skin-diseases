
import torch.nn as nn
from torchvision.models import resnet50, ResNet50_Weights


NUM_CLASSES = 6


def create_model():
    # ImageNet 사전 학습 가중치를 사용한 ResNet50
    weights = ResNet50_Weights.DEFAULT
    model = resnet50(weights=weights)

    # 기존 특징 추출층 고정
    for param in model.parameters():
        param.requires_grad = False

    # 마지막 분류층 변경
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, NUM_CLASSES)

    return model
