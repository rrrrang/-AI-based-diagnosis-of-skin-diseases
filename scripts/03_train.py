import json, time, os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from pathlib import Path
from torchvision import models
from sklearn.metrics import f1_score, classification_report, confusion_matrix

from dataset import get_loaders

# ---------------- 설정 ----------------
OUT = Path(__file__).resolve().parent.parent / "outputs"
META = OUT / "meta_split_block.csv"                      
TAG = "block_gray" if os.environ.get("SKIN_GRAY") == "1" else ("block_robust" if os.environ.get("SKIN_AUG") == "robust" else "block")
MODEL = "mobilenet"
IMG_SIZE = 224
EPOCHS, LR, PATIENCE = 6, 3e-4, 3
BATCH_SIZE, NUM_WORKERS = 32, 2
# --------------------------------------

def build_model(name, n_classes):
    if name == "effb0":
        m = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
        m.classifier[1] = nn.Linear(m.classifier[1].in_features, n_classes)
    else:
        m = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
        m.classifier[3] = nn.Linear(m.classifier[3].in_features, n_classes)
    return m


def run_epoch(model, loader, device, criterion, optimizer=None):
    train = optimizer is not None
    model.train(train)
    total_loss, preds, labels = 0.0, [], []
    with torch.set_grad_enabled(train):
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = criterion(logits, y)
            if train:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
            total_loss += loss.item() * x.size(0)
            preds.append(logits.argmax(1).cpu()); labels.append(y.cpu())
    preds, labels = torch.cat(preds).numpy(), torch.cat(labels).numpy()
    return total_loss / len(loader.dataset), preds, labels


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("device:", device, "| model:", MODEL)
    print(f"TAG={TAG} | GRAY={os.environ.get('SKIN_GRAY')} | AUG={os.environ.get('SKIN_AUG')} | EPOCHS={EPOCHS} | META={META.name}")
    label2id = json.load(open(OUT / "label2id.json", encoding="utf-8"))
    names = [k for k, _ in sorted(label2id.items(), key=lambda kv: kv[1])]
    loaders = get_loaders(META, img_size=IMG_SIZE, batch_size=BATCH_SIZE, num_workers=NUM_WORKERS)

    model = build_model(MODEL, len(names)).to(device)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-2)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    ckpt = OUT / f"best_{MODEL}_{TAG}.pt"

    best_f1, bad, history = 0.0, 0, []
    for ep in range(1, EPOCHS + 1):
        t0 = time.time()
        tr_loss, tr_p, tr_y = run_epoch(model, loaders["train"], device, criterion, optimizer)
        va_loss, va_p, va_y = run_epoch(model, loaders["val"], device, criterion)
        scheduler.step()
        tr_f1 = f1_score(tr_y, tr_p, average="macro"); va_f1 = f1_score(va_y, va_p, average="macro")
        print(f"[{ep:02d}/{EPOCHS}] train loss {tr_loss:.3f} f1 {tr_f1:.3f} | "
              f"val loss {va_loss:.3f} f1 {va_f1:.3f} | {(time.time()-t0)/60:.1f}분")
        history.append({"epoch": ep, "tr_loss": tr_loss, "tr_f1": tr_f1, "va_loss": va_loss, "va_f1": va_f1})
        pd.DataFrame(history).to_csv(OUT / f"history_{MODEL}_{TAG}.csv", index=False)
        if va_f1 > best_f1:
            best_f1, bad = va_f1, 0
            torch.save(model.state_dict(), ckpt)
        else:
            bad += 1
            if bad >= PATIENCE:
                print("early stopping"); break

    # ---------- test (한 번만) ----------
    model.load_state_dict(torch.load(ckpt, map_location=device))
    _, te_p, te_y = run_epoch(model, loaders["test"], device, criterion)
    print("\n=== TEST ===")
    print(classification_report(te_y, te_p, target_names=names, digits=3))
    cm = pd.DataFrame(confusion_matrix(te_y, te_p), index=names, columns=names)
    print(cm)
    cm.to_csv(OUT / f"confusion_test_{MODEL}_{TAG}.csv", encoding="utf-8-sig")

    meta = pd.read_csv(META, keep_default_na=False)
    te = meta[meta["set"] == "test"].reset_index(drop=True)
    keep = (te["near_dup"].astype(str) == "False").to_numpy() if "near_dup" in te else np.ones(len(te), bool)
    print(f"\n전체 test 정확도: {(te_p == te_y).mean():.4f} ({len(te_y)}장)")
    print(f"유사 이미지 제외 정확도: {(te_p[keep] == te_y[keep]).mean():.4f} ({keep.sum()}장)")


if __name__ == "__main__":
    main()