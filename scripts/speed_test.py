import time, torch
from torchvision import models
import torch.nn as nn

for name, ctor in [("effb0", models.efficientnet_b0), ("mobilenet_v3_small", models.mobilenet_v3_small)]:
    m = ctor(weights="DEFAULT"); m.train()
    opt = torch.optim.AdamW(m.parameters(), 1e-4)
    x, y = torch.randn(32, 3, 224, 224), torch.randint(0, 1000, (32,))
    t = time.time()
    for _ in range(3):
        opt.zero_grad(); nn.CrossEntropyLoss()(m(x), y).backward(); opt.step()
    per_batch = (time.time() - t) / 3
    print(f"{name}: 배치당 {per_batch:.1f}초 -> 에폭(240배치) 약 {per_batch*240/60:.1f}분")