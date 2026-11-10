import warnings; warnings.filterwarnings("ignore")
import pandas as pd, torch, torch.nn as nn
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms as T
from sklearn.metrics import accuracy_score

OUT = Path(__file__).resolve().parent.parent / "outputs"
te = pd.read_csv(OUT / "meta_split_block.csv", keep_default_na=False).query("set == 'test'").reset_index(drop=True)
N = 6
NORM = T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
TF = {"컬러": T.Compose([T.Resize((224, 224)), T.ToTensor(), NORM]),
      "회색조": T.Compose([T.Resize((224, 224)), T.Grayscale(3), T.ToTensor(), NORM])}

def build(name):
    if "effb0" in name:
        m = models.efficientnet_b0(); m.classifier[1] = nn.Linear(m.classifier[1].in_features, N)
    elif "resnet50" in name:
        m = models.resnet50(); m.fc = nn.Linear(m.fc.in_features, N)
    else:
        m = models.mobilenet_v3_small(); m.classifier[3] = nn.Linear(m.classifier[3].in_features, N)
    return m

class DS(Dataset):
    def __init__(self, tf): self.tf = tf
    def __len__(self): return len(te)
    def __getitem__(self, i):
        return self.tf(Image.open(te.loc[i, "img_path"]).convert("RGB")), int(te.loc[i, "label_id"])

for pt in sorted(OUT.glob("*.pt")):
    try:
        m = build(pt.stem); m.load_state_dict(torch.load(pt, map_location="cpu")); m.eval()
    except Exception as e:
        print(f"{pt.name}: 불러오기 실패 ({str(e)[:60]})"); continue
    res = {}
    for k, tf in TF.items():
        preds, ys = [], []
        with torch.no_grad():
            for x, y in DataLoader(DS(tf), batch_size=32, num_workers=0):
                preds += m(x).argmax(1).tolist(); ys += y.tolist()
        res[k] = accuracy_score(ys, preds)
    mtime = pd.Timestamp(pt.stat().st_mtime, unit="s", tz="UTC").tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")
    print(f"{pt.name} ({mtime}): 컬러 입력 {res['컬러']:.4f} | 회색조 입력 {res['회색조']:.4f}")