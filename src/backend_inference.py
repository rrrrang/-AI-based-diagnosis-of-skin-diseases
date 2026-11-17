"""Six-class side/close-up candidate API. No clinical diagnosis or localization."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/tmp/ultralytics'))
os.environ.setdefault('YOLO_AUTOINSTALL','false')
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'outputs/tmp/matplotlib'))
WEIGHTS=ROOT/'models/yolo11_detect/side_six_class_augmented/weights/best.pt'
EXPECTED_SHA='e792fb2374a6024f49249a40a9f2807282ef8d1bad9c3ec5c2f48055d03ed800'
MODEL_VERSION='yolo11n-side-six-class-20261117'
NAMES={0:'psoriasis',1:'atopic_dermatitis',2:'acne',3:'normal',4:'rosacea',5:'seborrheic_dermatitis'}
LABELS={0:'건선',1:'아토피',2:'여드름',3:'정상',4:'주사',5:'지루'}
SETTINGS={'imgsz':640,'confidence':.25,'nms_iou':.7,'device':'cpu'}


def response_from_scores(scores,image_id,role='side_closeup'):
    supported=role=='side_closeup'
    if supported:
        if set(scores)-set(LABELS.values()):raise ValueError('Unknown six-class score label')
        for value in scores.values():
            if type(value) not in (int,float) or not math.isfinite(value) or not .25<=value<=1:
                raise ValueError('Expected retained detection confidence in [0.25, 1]')
    rows=[{'class_id':cid,'name':name,'label':LABELS[cid],
           'score':scores.get(LABELS[cid]) if supported else None,
           'detected':supported and LABELS[cid] in scores}
          for cid,name in NAMES.items()]
    present=sorted((r for r in rows if r['detected']),key=lambda r:(-r['score'],r['class_id']))
    return {'schema_version':'2.0','image_id':image_id,'input_role':role,
        'status':('candidates_for_review' if present else 'undetermined') if supported else 'unsupported_input',
        'disease_scores':rows,'top_candidate':present[0] if present else None,
        'score_type':'uncalibrated_detection_confidence','scores_sum_to_100':False,
        'normal_confirmed':False,'model_sha256':EXPECTED_SHA,'model_version':MODEL_VERSION,'inference_settings':SETTINGS.copy(),
        'localization_available':False}


class DiseasePredictor:
    """Construct once per worker; backend must serialize calls per instance."""
    def __init__(self,weights=WEIGHTS):
        weights=Path(weights)
        if hashlib.sha256(weights.read_bytes()).hexdigest()!=EXPECTED_SHA:
            raise ValueError('Unexpected six-class side model checksum; the previous five-class checkpoint is not compatible')
        from ultralytics import YOLO
        self.model=YOLO(str(weights))
        if self.model.task!='detect' or self.model.names!=NAMES:
            raise ValueError('Requires the six-class detector in the agreed class order')
        architecture=self.model.model.yaml
        if architecture.get('scale')!='n' or Path(architecture.get('yaml_file','').replace('\\','/')).name not in ('yolo11n.yaml','yolo11.yaml'):
            raise ValueError('Requires YOLO11n architecture')

    def predict(self,image,image_id,role='side_closeup'):
        if role!='side_closeup':return response_from_scores({},image_id,role)
        # API accepts PIL images or local paths; invalid images raise to the caller.
        if isinstance(image,Image.Image):source=ImageOps.exif_transpose(image).convert('RGB')
        else:
            try:
                with Image.open(image) as opened:
                    opened.load();source=ImageOps.exif_transpose(opened).convert('RGB')
            except (OSError, ImportError) as exc:
                raise ValueError('Unsupported or invalid image; provide a readable PNG or JPEG') from exc
        result=self.model.predict(source=source,imgsz=640,conf=.25,iou=.7,rect=False,
                                  augment=False,quantize=32,max_det=300,device='cpu',verbose=False)[0]
        scores={}
        if result.boxes is not None:
            for cid,confidence in zip(result.boxes.cls.cpu().tolist(),result.boxes.conf.cpu().tolist()):
                if cid!=int(cid) or int(cid) not in NAMES:raise ValueError('Invalid model class ID')
                label=LABELS[int(cid)];scores[label]=max(scores.get(label,0.),float(confidence))
        return response_from_scores(scores,image_id,role)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image-id',default='example')
    parser.add_argument('--role',choices=['side_closeup','front'],default='side_closeup')
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('Existing response is protected')
    result=(response_from_scores({},args.image_id,args.role) if args.role=='front'
            else DiseasePredictor().predict(args.source,args.image_id,args.role))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
