"""Side/close-up disease candidate API. No frontal localization or training."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image
import disease_detection as detection

ROOT=Path(__file__).resolve().parents[1]
WEIGHTS=ROOT/'models/yolo11_detect/side_hard_negative/weights/best.pt'
EXPECTED_SHA='5578f2729fd6e76001febff9109c81ae2482527ebddd3bc83bda783ef38f60a7'
MODEL_VERSION='yolo11n-side-hard-negative-20261112'
SETTINGS={'imgsz':640,'confidence':.25,'nms_iou':.7,'device':'cpu'}


def response_from_scores(scores,image_id,role='side_closeup'):
    supported=role=='side_closeup'
    rows=[{'class_id':cid,'name':name,'label':detection.LABELS[cid],
           'score':scores.get(detection.LABELS[cid]) if supported else None,
           'detected':supported and detection.LABELS[cid] in scores}
          for cid,name in detection.NAMES.items()]
    present=sorted((r for r in rows if r['detected']),key=lambda r:(-r['score'],r['class_id']))
    return {'schema_version':'1.0','image_id':image_id,'input_role':role,
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
            raise ValueError('Unexpected side model checksum')
        from ultralytics import YOLO
        self.model=YOLO(str(weights))
        detection.validate_model(self.model)

    def predict(self,image,image_id,role='side_closeup'):
        if role!='side_closeup':return response_from_scores({},image_id,role)
        # API accepts PIL images or local paths; invalid images raise to the caller.
        if isinstance(image,Image.Image):source=image.copy()
        else:
            try:
                with Image.open(image) as opened:opened.load();source=opened.copy()
            except (OSError, ImportError) as exc:
                raise ValueError('Unsupported or invalid image; provide a readable PNG or JPEG') from exc
        result=detection.predict(self.model,source,mode='full',imgsz=640,conf=.25,
                                 merge_iou=.7,device='cpu',max_det=300)
        return response_from_scores(result['candidate_max_detection_scores'],image_id,role)


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
