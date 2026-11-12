"""Single YOLO11n disease-region detector: readiness audit and A/B inference.

No classification checkpoint, face model or automatic disease label approval.
Training is explicit and gated by reviewed labels and a matching loader proof.
Run --audit first. --predict requires a locally trained five-class detector.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import math
import os
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps

PROJECT = Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_CONFIG_DIR',str(PROJECT/'outputs/tmp/ultralytics'))
os.environ.setdefault('YOLO_AUTOINSTALL','false')
os.environ.setdefault('YOLO_OFFLINE','true')
os.environ.setdefault('MPLCONFIGDIR',str(PROJECT/'outputs/tmp/matplotlib'))
DATA = PROJECT / 'data/processed/detection/disease_regions'
OUT = PROJECT / 'outputs/disease_detection_preparation'
NAMES = {0: 'psoriasis', 1: 'atopic_dermatitis', 2: 'acne', 3: 'rosacea', 4: 'seborrheic_dermatitis'}
LABELS = {0: '건선', 1: '아토피', 2: '여드름', 3: '주사', 4: '지루'}
CLASSIFICATION_TO_DETECTION = {0: 0, 1: 1, 2: 2, 3: None, 4: 3, 5: 4}
# This maps the six source-data IDs to five detector IDs; it does not use a classifier.
CLASSIFICATION_EXPERIMENT_POLICY = {
    'status':'retired','compare_with_detection':False,'use_metrics_for_decisions':False,
    'reason':'User retired the original classification approach; current scope is YOLO11n detection.'}
TRAINING_OUT = PROJECT/'outputs/training/disease_detection'


def active_label_source():
    path=DATA/'config.json'
    if not path.is_file():return 'reviewed_disease_regions'
    return json.loads(path.read_text(encoding='utf-8')).get('active_label_source','reviewed_disease_regions')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, list(rows[0])); w.writeheader(); w.writerows(rows)


def box_valid(box, width, height):
    return (isinstance(box, list) and len(box) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in box)
            and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)


def xywh_box(box):
    if not isinstance(box, dict): return None
    v = [box.get(k) for k in ('xpos', 'ypos', 'width', 'height')]
    if not all(type(x) in (int, float) and math.isfinite(x) for x in v): return None
    x, y, w, h = v
    return [x, y, x + w, y + h]


def windows(width, height, tile_size=512, overlap=.25):
    """Overlapping pixel windows, including image edges; no semantic face parser."""
    if min(width, height, tile_size) < 1 or not 0 <= overlap < 1:
        raise ValueError('Invalid tile dimensions/overlap')
    def starts(length):
        if length <= tile_size: return [0]
        step = max(1, round(tile_size * (1 - overlap)))
        return sorted(set(list(range(0, length - tile_size + 1, step)) + [length - tile_size]))
    return [[x, y, min(x + tile_size, width), min(y + tile_size, height)]
            for y in starts(height) for x in starts(width)]


def iou(a, b):
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / union if union > 0 else 0.


def merge_detections(detections, threshold=.5):
    """Class-aware NMS AFTER translating tile results to original coordinates."""
    if not 0 < threshold <= 1: raise ValueError('Invalid merge IoU')
    kept = []
    for d in sorted(detections, key=lambda x: -x['confidence']):
        if not any(d['class_id'] == k['class_id'] and iou(d['box_xyxy'], k['box_xyxy']) > threshold for k in kept):
            kept.append(d)
    return kept


def inspect_source(row, features):
    image_path = PROJECT / row['image_path']; label_path = PROJECT / row['label_path']
    image_sha = sha(image_path)
    if image_sha != features[row['image_path']]['sha256']: raise ValueError('Image changed: '+row['sample_id'])
    document = json.loads(label_path.read_text(encoding='utf-8'))
    annotations = document.get('annotations', [])
    if len(annotations) != 1: raise ValueError('Expected one annotation: '+row['sample_id'])
    a = annotations[0]; w = int(row['width']); h = int(row['height'])
    if a['diagnosis_info']['diagnosis_name'] != row['label']: raise ValueError('Diagnosis mismatch')
    if (int(a['photograph']['width']), int(a['photograph']['height'])) != (w, h): raise ValueError('Size mismatch')
    bbox = a.get('bbox', {}); outer = xywh_box(bbox); lesions = bbox.get('lesions', [])
    lesion_boxes = [xywh_box(x) for x in lesions]
    return {**{k: row[k] for k in ('sample_id','image_path','label_path','split','view','class_id','label','group_id','source_group_id','width','height')},
            'source_image_sha256': image_sha, 'source_label_sha256': sha(label_path),
            'outer_box_xyxy': json.dumps(outer), 'outer_box_valid': str(box_valid(outer,w,h)),
            'outer_box_area_fraction': ((outer[2]-outer[0])*(outer[3]-outer[1])/(w*h)) if box_valid(outer,w,h) else '',
            'lesion_point_box_count': len(lesions),
            'invalid_lesion_point_boxes': sum(not box_valid(b,w,h) for b in lesion_boxes),
            'mask_reference': bbox.get('lesion_area',''),
            'approved_disease_region_label': False}


def validate_task(task, source):
    """Only explicitly reviewed, complete disease-region labels can be exported.

    Normal = explicitly reviewed negative. Blank/pending is NEVER negative.
    Old generic ROI and acne point boxes are not imported as disease labels.
    """
    for key in ('sample_id','image_path','split','source_image_sha256','source_label_sha256'):
        if task.get(key) != source.get(key): raise ValueError('Task/source mismatch: '+key)
    if task.get('review_status') != 'reviewed': raise ValueError('Unreviewed disease-region label')
    if task.get('annotation_scope') != 'disease_region': raise ValueError('Not disease-region annotations')
    if task.get('completeness_reviewed') != 'True' or not task.get('reviewer','').strip():
        raise ValueError('Reviewer/completeness confirmation required')
    boxes = json.loads(task.get('objects_json',''))
    if not isinstance(boxes,list): raise ValueError('objects_json must be a list')
    if source['class_id']=='3':
        if boxes or task.get('normal_negative_confirmed') != 'True': raise ValueError('Normal requires explicit empty negative confirmation')
    elif not boxes: raise ValueError('Diseased image without reviewed disease regions')
    lines=[]
    for obj in boxes:
        cid=obj.get('class_id'); box=obj.get('box_xyxy')
        if type(cid) is not int or cid not in NAMES: raise ValueError('Invalid detector class ID')
        w=int(source['width']); h=int(source['height'])
        if not box_valid(box,w,h): raise ValueError('Invalid original-pixel box')
        x1,y1,x2,y2=box
        lines.append(f'{cid} {(x1+x2)/(2*w):.10f} {(y1+y2)/(2*h):.10f} {(x2-x1)/w:.10f} {(y2-y1)/h:.10f}')
    return lines


def annotation_readiness(inventory,tasks):
    """All development images must be examined; reasoned deferrals are excluded.

    Exclusion must not silently remove a disease or all normal negatives.
    """
    by_id={r['sample_id']:r for r in inventory};valid=Counter();normal=Counter()
    coverage={role:set() for role in ('train','validation')};errors=[];pending=Counter();deferred=Counter()
    for task in tasks:
        source=by_id[task['sample_id']];role=source['split']
        if task['review_status']=='pending': pending[role]+=1;continue
        try:
            if task['review_status']=='deferred':
                if not task['notes'].strip() or not task['reviewer'].strip() or task['objects_json']!='':
                    raise ValueError('Deferral requires reviewer, reason and no training boxes')
                for k in ('image_path','split','source_image_sha256','source_label_sha256'):
                    if task[k]!=source[k]: raise ValueError('Deferred task/source mismatch')
                deferred[role]+=1;continue
            validate_task(task,source);valid[role]+=1
            if role in coverage:
                if source['class_id']=='3':normal[role]+=1
                coverage[role].update(o['class_id'] for o in json.loads(task['objects_json']))
        except (ValueError,TypeError,KeyError) as e:errors.append({'sample_id':task['sample_id'],'error':str(e)})
    ready=not errors and all(pending[role]==0 and coverage[role]==set(NAMES) and normal[role]>0 for role in coverage)
    return {'training_ready':ready,'valid':dict(valid),'errors':errors,'deferred':dict(deferred),
            'pending':dict(pending),'disease_class_coverage':{k:sorted(v) for k,v in coverage.items()},'normal_negatives':dict(normal)}


def annotation_review_progress():
    """Report side-only label work without counting pending pictures as negatives."""
    inventory={r['sample_id']:r for r in read_csv(OUT/'source_inventory.csv')}
    tasks=read_csv(DATA/'annotation_tasks.csv')
    selected=[t for t in tasks if inventory[t['sample_id']]['split'] in ('train','validation')]
    counts=Counter(t['review_status'] for t in selected)
    classes=[]
    for cid in range(6):
        subset=[t for t in selected if inventory[t['sample_id']]['class_id']==str(cid)]
        classes.append({'classification_class_id':cid,'label':next((r['label'] for r in inventory.values() if r['class_id']==str(cid)),'unknown'),
                        'total':len(subset),'status_counts':dict(Counter(t['review_status'] for t in subset))})
    return {'total':len(selected),'status_counts':dict(counts),'visually_examined':counts['reviewed']+counts['deferred'],
            'eligible_labels':counts['reviewed'],'deferred':counts['deferred'],'not_yet_viewed':counts['pending'],
            'classes':classes,'expert_clinical_review':False,'automatic_visual_approvals':0}


def record_annotation_decisions(records):
    """Persist explicit native-image/crop observations; never infer visual review.

    An existing task must be pending. Deferred cases have NO training label.
    This is an AI visual dataset annotation, not an independent clinical diagnosis.
    """
    tasks=read_csv(DATA/'annotation_tasks.csv'); by_id={t['sample_id']:t for t in tasks}
    inventory={r['sample_id']:r for r in read_csv(OUT/'source_inventory.csv')}
    ledger_path=OUT/'annotation_review.json'
    ledger=json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {
        'scope':'side_train_validation_disease_regions','policy':'defer_ambiguous_boundaries',
        'source_inventory_sha256':sha(OUT/'source_inventory.csv'),'decisions':{},'training_executed':False,
        'expert_clinical_review':False}
    if ledger['source_inventory_sha256']!=sha(OUT/'source_inventory.csv'): raise ValueError('Review source inventory changed')
    updates=[]
    if len({r['sample_id'] for r in records})!=len(records): raise ValueError('Duplicate decision in batch')
    for record in records:
        sid=record['sample_id']; row=inventory[sid]; old=by_id[sid]
        if row['split'] not in ('train','validation') or row['view']!='측면': raise ValueError('Only side train/validation may be annotated here')
        if old['review_status']!='pending' or sid in ledger['decisions']: raise ValueError('Existing review is protected')
        if record.get('source_individually_viewed') is not True or not record.get('notes','').strip():
            raise ValueError('Actual native source inspection and observations required')
        for field,path in [('source_image_sha256',row['image_path']),('source_label_sha256',row['label_path'])]:
            if sha(PROJECT/path)!=row[field] or old[field]!=row[field]: raise ValueError('Changed source')
        page=(PROJECT/record['source_page']).resolve()
        if not page.is_relative_to((PROJECT/'outputs/tmp/disease_region_review').resolve()) or not page.is_file():
            raise ValueError('Missing local native-size source evidence')
        decision=record['decision']; task=dict(old)
        task.update(reviewer='Codex visual annotation; not clinical confirmation',notes=record['notes'])
        crops=[]
        if decision=='deferred':
            if record.get('boxes'): raise ValueError('Deferred case must not have an approved box')
            task.update(review_status='deferred',objects_json='',completeness_reviewed='False',normal_negative_confirmed='False')
        elif decision=='reviewed':
            boxes=record['boxes']
            if record.get('final_crops_checked') is not True or record.get('visible_regions_completeness_checked') is not True:
                raise ValueError('Final crop and visible-region completeness checks required')
            detector_id=CLASSIFICATION_TO_DETECTION[int(row['class_id'])]
            if detector_id is None and boxes: raise ValueError('Normal cannot contain disease boxes')
            if detector_id is not None and not boxes: raise ValueError('Disease needs visible region boxes')
            objects=[{'class_id':detector_id,'box_xyxy':b} for b in boxes]
            task.update(review_status='reviewed',objects_json=json.dumps(objects),completeness_reviewed='True',
                        normal_negative_confirmed=str(detector_id is None))
            validate_task(task,row)
            with Image.open(PROJECT/row['image_path']) as image:
                for i,box in enumerate(boxes):
                    path=PROJECT/'outputs/tmp/disease_region_review'/f'{hashlib.sha256(sid.encode()).hexdigest()[:20]}_{i}.png'
                    image.crop(tuple(box)).save(path)
                    crops.append({'path':path.relative_to(PROJECT).as_posix(),'sha256':sha(path)})
        else: raise ValueError('Unknown review decision')
        decision_record={**record,'source_page_sha256':sha(page),'source_image_sha256':row['source_image_sha256'],
                         'source_label_sha256':row['source_label_sha256'],'crop_evidence':crops,
                         'timestamp_kst':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
                         'clinical_localization_verified':False}
        updates.append((sid,task,decision_record))
    if len({sid for sid,_,_ in updates})!=len(updates): raise ValueError('Duplicate decision in batch')
    for sid,task,record in updates: by_id[sid].update(task);ledger['decisions'][sid]=record
    # Save the evidence ledger first. A failed CSV write remains recoverable.
    dump(ledger_path,ledger)
    import tempfile
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8-sig',newline='',suffix='.csv',
                                         dir=PROJECT/'outputs/tmp',delete=False) as f:
            temporary=Path(f.name);writer=csv.DictWriter(f,list(tasks[0]));writer.writeheader();writer.writerows(tasks)
        os.replace(temporary,DATA/'annotation_tasks.csv')
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()
    progress=annotation_review_progress();ledger['progress']=progress;dump(ledger_path,ledger)
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    summary.update(annotation_tasks_sha256=sha(DATA/'annotation_tasks.csv'),annotation_review_progress=progress)
    if active_label_source()!='provider_bbox_experiment':
        summary.update(status='side_disease_region_visual_review_in_progress',training_ready=False)
    else:summary['reviewed_region_training_ready']=False
    summary['validated_annotations_by_split']=dict(Counter(t['split'] for t in tasks if t['review_status']=='reviewed'))
    summary['training_executed']=False;dump(OUT/'summary.json',summary)
    return progress


def publish_annotation_review():
    """Read-only local gallery; only explicitly stored decisions count as viewed."""
    progress=annotation_review_progress()
    tasks={r['sample_id']:r for r in read_csv(DATA/'annotation_tasks.csv')}
    inventory=read_csv(OUT/'source_inventory.csv')
    payload=[]
    for row in inventory:
        if row['split'] not in ('train','validation'): continue
        task=tasks[row['sample_id']]
        payload.append({**{k:row[k] for k in ('sample_id','image_path','label','class_id','split','width','height')},
                        'status':task['review_status'],'notes':task['notes'],
                        'objects':json.loads(task['objects_json']) if task['review_status']=='reviewed' else []})
    raw=json.dumps({'progress':progress,'cases':payload},ensure_ascii=False).replace('<','\\u003c')
    html='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>측면 질환 영역 라벨 검토</title>
<style>body{font:16px system-ui;margin:24px;background:#f5f7fa}h1{font-size:24px}.warning{background:#fff0c9;padding:14px}select,button{font:inherit;padding:8px;max-width:95%}.row{display:flex;gap:20px;flex-wrap:wrap}.panel{background:white;padding:12px;overflow:auto;max-width:100%}canvas{display:block;max-width:none}pre{white-space:pre-wrap}#crops{display:flex;gap:14px;flex-wrap:wrap}#crops figure{margin:0}a{color:#185a80}</style>
<h1>측면 질환 영역 · 원본 좌표 검토</h1><p id="progress"></p>
<p class="warning">AI가 원본·크롭을 확인해 작성한 영역입니다. 독립적인 의학적 진단·전문가 경계 정답이 아닙니다. 질환명은 제공된 사진 라벨을 상속합니다. 애매한 사진은 보류하고 음성 표본에 넣지 않습니다. 미검토 사진을 표시하는 것만으로 검수 기록이 바뀌지 않습니다.</p>
<p><a href="report.md">진행 보고서</a> · <a href="../../data/processed/detection/disease_regions/annotation_tasks.csv">라벨 CSV</a> · <a href="annotation_review.json">검수 근거</a></p>
<p><select id="status"><option value="reviewed">라벨 작성·음성 확인</option><option value="deferred">판단 보류</option><option value="pending">아직 미검토</option><option value="all">전체</option></select>
<select id="class"><option value="all">모든 질환</option><option value="0">건선</option><option value="1">아토피</option><option value="2">여드름</option><option value="3">정상</option><option value="4">주사</option><option value="5">지루</option></select></p>
<p><button id="prev">이전</button> <select id="case"></select> <button id="next">다음</button></p>
<pre id="info"></pre><div class="row"><section class="panel"><h2>원본 512px · 사각형 표시</h2><canvas id="source"></canvas></section><section class="panel"><h2>각 영역의 크롭 · 원본 픽셀</h2><div id="crops"></div></section></div>
<script>'use strict';const data=__DATA__,$=id=>document.getElementById(id);let filtered=[],ticket=0;
const p=data.progress;$('progress').textContent=`대상 ${p.total}장 · 직접 확인 ${p.visually_examined}장 · 라벨/정상 확인 ${p.eligible_labels}장 · 보류 ${p.deferred}장 · 미검토 ${p.not_yet_viewed}장`;
function filter(){filtered=data.cases.filter(c=>($('status').value==='all'||c.status===$('status').value)&&($('class').value==='all'||c.class_id===$('class').value));$('case').replaceChildren();filtered.forEach((c,i)=>$('case').add(new Option(`${c.label} · ${c.split} · ${c.sample_id}`,i)));show()}
function show(){const mine=++ticket,c=filtered[+$('case').value];$('crops').replaceChildren();const cv=$('source');cv.width=512;cv.height=512;if(!c){$('info').textContent='해당 상태의 사진이 없습니다.';return}$('info').textContent=c.sample_id+'\\n'+c.label+' / '+c.split+' / '+c.status+'\\n'+c.notes+'\\n원본 xyxy: '+JSON.stringify(c.objects);const im=new Image();im.onload=()=>{if(mine!==ticket)return;cv.width=im.naturalWidth;cv.height=im.naturalHeight;const ctx=cv.getContext('2d');ctx.drawImage(im,0,0);ctx.lineWidth=2;ctx.strokeStyle='#00ff50';ctx.font='16px sans-serif';c.objects.forEach((o,i)=>{const [x1,y1,x2,y2]=o.box_xyxy;ctx.strokeRect(x1,y1,x2-x1,y2-y1);ctx.fillStyle='#002300';ctx.fillText(String(i+1),x1+3,y1+18);const fig=document.createElement('figure'),label=document.createElement('figcaption'),crop=document.createElement('canvas');crop.width=x2-x1;crop.height=y2-y1;crop.getContext('2d').drawImage(im,x1,y1,x2-x1,y2-y1,0,0,x2-x1,y2-y1);label.textContent=`상자 ${i+1}: ${o.box_xyxy.join(', ')}`;fig.append(label,crop);$('crops').append(fig)});if(!c.objects.length)$('crops').textContent=c.status==='reviewed'?'정상 음성: 질환 상자 없음':'좌표 미확정: 학습 라벨이 아닙니다.'};im.onerror=()=>{if(mine===ticket)$('info').textContent+='\\n원본을 불러오지 못했습니다. 프로젝트 폴더에서 열어주세요.'};im.src='../../'+c.image_path.split('/').map(encodeURIComponent).join('/')}
$('status').onchange=filter;$('class').onchange=filter;$('case').onchange=show;$('prev').onclick=()=>{if(+$('case').value>0){$('case').value=+$('case').value-1;show()}};$('next').onclick=()=>{if(+$('case').value<filtered.length-1){$('case').value=+$('case').value+1;show()}};filter();</script></html>'''
    (OUT/'annotation_review.html').write_text(html.replace('__DATA__',raw),encoding='utf-8')
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'));summary['annotation_review_progress']=progress
    summary['annotation_tasks_sha256']=sha(DATA/'annotation_tasks.csv')
    if active_label_source()!='provider_bbox_experiment':summary['training_ready']=False
    summary['validated_annotations_by_split']=dict(Counter(t['split'] for t in tasks.values() if t['review_status']=='reviewed'))
    dump(OUT/'summary.json',summary)
    return progress


def audit():
    if active_label_source()=='provider_bbox_experiment':
        from audit_detection_labels import audit as reuse_audit
        return reuse_audit()
    manifest=PROJECT/'data/processed/manifest.csv'; rows=read_csv(manifest)
    features={r['image_path']:r for r in read_csv(PROJECT/'outputs/dataset_audit/image_checks.csv')}
    DATA.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
    config={'active_task':'disease_detection','model':'YOLO11n','task':'detect','weights':'yolo11n.pt','number_of_image_models':1,
            'names':NAMES,'labels_ko':LABELS,'classification_to_detection':CLASSIFICATION_TO_DETECTION,
            'classification_experiment_policy':CLASSIFICATION_EXPERIMENT_POLICY,
            'normal_policy':'reviewed_background_negative_not_a_box_class',
            'empty_detection_policy':'not_detected_needs_review_never_automatic_normal',
            'training_view':'측면','train_split':'train','validation_split':'validation',
            'side_test_split':'test_side','front_evaluation_split':'test_front',
            'front_exposure':'previously_inspected_development_evaluation_not_blind_holdout',
            'source_manifest_sha256':sha(manifest),'external_augmentation_enabled':False,
            'external_augmentation_requirement':'verified transformed boxes and train-source lineage before inclusion',
            'annotation_scope':'disease_region','legacy_skin_roi_workflow':'paused_not_disease_ground_truth',
            'inference_experiments':[{'name':'A640','mode':'full','imgsz':640},{'name':'A1024','mode':'full','imgsz':1024},
                {'name':'B512_640','mode':'tiles','tile_size':512,'overlap':.25,'imgsz':640}],
            'threshold_selection':'side_validation; front exploration must be separately disclosed',
            'selection_status':'unselected_no_disease_detector_trained'}
    config_path=DATA/'config.json'
    if config_path.exists():
        old=json.loads(config_path.read_text(encoding='utf-8'))
        if old != json.loads(json.dumps(config,ensure_ascii=False)): raise ValueError('Existing detection configuration differs; no overwrite')
    else: dump(config_path,config)
    print(f'Auditing {len(rows)} image/JSON pairs without creating training labels...',flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        inventory=[]
        for i,r in enumerate(pool.map(lambda r:inspect_source(r,features),rows),1):
            inventory.append(r)
            if i%1000==0: print(f'Checked {i}/{len(rows)}',flush=True)
    write_csv(OUT/'source_inventory.csv',inventory)
    tasks_path=DATA/'annotation_tasks.csv'
    if not tasks_path.exists():
        tasks=[{**{k:r[k] for k in ('sample_id','image_path','split','source_image_sha256','source_label_sha256')},
                'review_status':'pending','annotation_scope':'disease_region','objects_json':'',
                'completeness_reviewed':'False','normal_negative_confirmed':'False','reviewer':'','notes':''} for r in inventory]
        write_csv(tasks_path,tasks)
    tasks=read_csv(tasks_path)
    if len({t['sample_id'] for t in tasks})!=len(tasks) or {t['sample_id'] for t in tasks}!={r['sample_id'] for r in inventory}:
        raise ValueError('Annotation task IDs do not match original manifest')
    readiness=annotation_readiness(inventory,tasks);valid=Counter(readiness['valid']);errors=readiness['errors']
    strata=[]
    for view in ('측면','정면'):
        for cid in range(6):
            subset=[r for r in inventory if r['view']==view and r['class_id']==str(cid)]
            strata.append({'view':view,'class_id':cid,'label':subset[0]['label'],'images':len(subset),
                'outer_boxes_cover_90_percent_or_more':sum(float(r['outer_box_area_fraction'] or 0)>=.9 for r in subset),
                'lesion_point_boxes':sum(r['lesion_point_box_count'] for r in subset),
                'invalid_lesion_point_boxes':sum(r['invalid_lesion_point_boxes'] for r in subset),
                'mask_references':sum(bool(r['mask_reference']) for r in subset)})
    overlap_checks={}
    for name,field in [('group','group_id'),('source_id','source_group_id'),
                       ('exact_file','source_image_sha256'),('exact_pixels',None)]:
        buckets=defaultdict(set)
        for r in inventory:
            key=r[field] if field else features[r['image_path']]['pixel_sha256']
            buckets[key].add(r['split'])
        overlap_checks[name]=sum(len(roles)>1 for roles in buckets.values())
    summary={'updated_at_kst':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
        'status':'disease_region_annotations_required','model':'YOLO11n','task':'detect',
        'source_pairs_checked':len(inventory),'split_counts':dict(Counter(r['split'] for r in inventory)),
        'group_split_overlap':overlap_checks['group'],'source_split_overlap_checks':overlap_checks,
        'source_manifest_sha256':sha(manifest),'inventory_sha256':sha(OUT/'source_inventory.csv'),
        'annotation_tasks_sha256':sha(tasks_path),'strata':strata,'validated_annotations_by_split':dict(valid),
        'annotation_errors':errors,'training_executed':False,'front_training_enabled':False,
        'legacy_roi_relabelled_as_disease':False,'automatic_approved_labels':0,
        'training_ready':readiness['training_ready'] and not any(overlap_checks.values()),
        'annotation_readiness':readiness,
        'front_localization_ground_truth_required_for_map':True,
        'limitation':'Crop-scale change, synthetic/real domain shift and label semantics remain unproven; higher imgsz/tiling does not guarantee generalization.'}
    if summary['training_ready']: summary['status']='reviewed_train_validation_labels_ready_for_export'
    previous_summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8')) if (OUT/'summary.json').is_file() else {}
    if (OUT/'annotation_review.json').is_file():
        summary['annotation_review_progress']=annotation_review_progress()
        if not summary['training_ready']: summary['status']='side_disease_region_visual_review_in_progress'
        if 'annotation_review_verification' in previous_summary: summary['annotation_review_verification']=previous_summary['annotation_review_verification']
    dump(OUT/'summary.json',summary)
    report=['# YOLO11n 단일 질환 탐지로 전환','',
        '사용자 정면 사진 → 전체 입력(A) 또는 겹치는 타일 입력(B) → 같은 YOLO11n → 원본 좌표 복원·클래스별 NMS → 질환 후보·상자. YOLO11n-cls 및 별도 얼굴 탐지 모델은 사용하지 않습니다.','',
        f'원본 목록 {len(inventory):,}장 이미지 SHA와 JSON 연결·진단명·해상도·좌표 구조를 재점검했습니다. 원본과 과거 실험은 보존했습니다. 아직 새 탐지 모델은 학습하지 않았습니다.','',
        '| 방향 | 질환 | 이미지 | 일반 bbox 면적 ≥90% | 개별 좌표 | 범위 오류 | 마스크 경로 참조 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for r in strata: report.append(f'| {r["view"]} | {r["label"]} | {r["images"]} | {r["outer_boxes_cover_90_percent_or_more"]} | {r["lesion_point_boxes"]} | {r["invalid_lesion_point_boxes"]} | {r["mask_references"]} |')
    report += ['', '일반 bbox는 영상/피부 범위 메타데이터이며 질환 경계 정답으로 승인하지 않습니다. 여드름 지점 상자와 다른 질환의 넓은 영역은 표시 단위가 달라 바로 혼합하지 않습니다. 마스크 경로 참조만으로 실제 마스크 확보를 뜻하지 않습니다.', '',
        '## 다음 작업과 라벨 기준','',
        '1. 측면 train/validation에 질환 특징이 보이는 영역을 원본 좌표 xyxy로 작성합니다. 작은 개별 구진 개수 대신 질환 특징과 주변 피부가 포함된 영역 단위로 통일하고, 같은 사진의 유효 영역 누락도 검토합니다. 기존 전체 사진 bbox는 자동 승인하지 않습니다.',
        '2. annotation_tasks.csv에서 review_status=reviewed, annotation_scope=disease_region, objects_json=[{"class_id":0,"box_xyxy":[x1,y1,x2,y2]}], completeness_reviewed=True, reviewer를 기록합니다. 정상은 objects_json=[] 및 normal_negative_confirmed=True로 명시합니다. pending/빈 칸은 음성 라벨이 아닙니다.',
        '3. 탐지 클래스는 건선0/아토피1/여드름2/주사3/지루4입니다. 이전 분류 class_id=3은 정상이므로 새 탐지 ID와 섞지 않습니다. 원래 클래스표를 수정하지 않습니다.',
        '4. train/validation 라벨 전수 확인 후 --prepare로 YOLO 입력을 생성합니다. 증강본은 좌표의 회전·이동 등 변환 이력과 원본 train 계보를 검증하기 전까지 제외합니다.',
        '5. YOLO11n을 측면 train으로 학습하고 측면 validation으로 선택한 뒤 A640/A1024/B512_640을 비교합니다. 비교에서는 같은 가중치를 고정합니다. B의 512px 타일·25% 겹침은 실험 시작값이지 최적값이 아닙니다.',
        '6. 정면에는 위치 정답을 별도로 검수해야 mAP/위치 recall을 계산할 수 있습니다. 기존 피부 ROI 108장 검수는 재사용 참고자료이며 질환 정답으로 전환하지 않습니다. 정면은 학습에 넣지 않습니다. 이미 사용한 정면은 탐색 평가이며 최종 실사진 검증 자료는 별도로 필요합니다.','',
        '## A/B 실험과 픽셀 크기','',
        '1024×1024 원본의 16px 특징은 A640에서 약10px, A1024에서16px, B512→640에서20px로 모델에 표시됩니다. 512px 측면을640에 넣을 때도20px입니다. 이는 표본 예시이며 실제 병변 크기나 성능 향상의 증명이 아닙니다. 512px 원본을1024로 키워도 없던 세부 정보가 복원되지는 않습니다. 더 큰 휴대폰 사진은 전체1024에서도 축소됩니다.',
        'B는 원본 전체를 겹치는 격자로 덮는 방식입니다. 볼·이마·코·턱의 의미를 식별하는 방식이 아닙니다. 경계 병변의 잘림과 중복은 겹침·원본 좌표 복원·NMS로 완화하지만 완전히 해결하지 못합니다. 타일별 최대 점수는 보정된 사진 단위 질환 확률이 아닙니다. 미검출은 정상 확정이 아닌 보류입니다.','',
        '## 실행','',
        '```powershell', '.venv/Scripts/python.exe src/prepare_roi_detection.py',
        '.venv/Scripts/python.exe src/disease_detection.py --prepare',
        '# 위치 라벨 검수 및 수출 후에만 아래 로더 검증과 학습을 실행합니다.',
        '.venv/Scripts/python.exe src/disease_detection.py --verify-loader --imgsz 640',
        '.venv/Scripts/python.exe src/disease_detection.py --train --weights models/pretrained/yolo11n.pt --imgsz 640',
        '# 아래는 질환 탐지 학습이 끝난 가중치가 생긴 뒤에 실행합니다.',
        '.venv/Scripts/python.exe src/disease_detection.py --predict --weights models/yolo11_detect/disease_regions/weights/best.pt --source <사진경로> --mode full --imgsz 640 --output outputs/disease_detection_preparation/A640.json',
        '.venv/Scripts/python.exe src/disease_detection.py --predict --weights models/yolo11_detect/disease_regions/weights/best.pt --source <사진경로> --mode tiles --imgsz 640 --tile-size 512 --overlap 0.25 --output outputs/disease_detection_preparation/B512_640.json', '```', '',
        '검증: src/test_skin_dataset.py의 disease_detection 관련 회귀 테스트 및 summary.json을 참조합니다. 현재 실제 성능 비교 결과는 없습니다.','',
        '신규: src/disease_detection.py(라벨 게이트·A/B 입력), data/processed/detection/disease_regions/config.json·annotation_tasks.csv(새 목적·위치 라벨 목록), 이 폴더의 source_inventory.csv·summary.json·report.md(원본 감사). 수정: 기획서, 기존 탐지 준비 진입점, 과거 분류 실행 안내 및 ROI 검수 안내, 기존 테스트. 원본·가중치 삭제 없음. 기존 skin_roi 데이터는 과거 실험용으로 남기며 현재 학습에 사용하지 않습니다.','',
        '근거: [YOLO11 모델 작업 구분](https://docs.ultralytics.com/models/yolo11/) · [탐지 라벨 형식](https://docs.ultralytics.com/datasets/detect/) · [추론 API](https://docs.ultralytics.com/modes/predict/).','']
    report_path=OUT/'report.md';review_prefix=''
    if report_path.exists():
        previous=report_path.read_text(encoding='utf-8')
        if '<!-- side-annotation-progress:start -->' in previous:
            review_prefix=previous.split('<!-- side-annotation-progress:start -->',1)[1].split('<!-- side-annotation-progress:end -->',1)[0]
            review_prefix='<!-- side-annotation-progress:start -->'+review_prefix+'<!-- side-annotation-progress:end -->\n\n'
    report_path.write_text(review_prefix+'\n'.join(report),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('status','source_pairs_checked','validated_annotations_by_split','training_ready')},ensure_ascii=False),flush=True)
    return inventory,tasks,summary


def prepare():
    if active_label_source()=='provider_bbox_experiment':
        from audit_detection_labels import export
        return export()
    inventory,tasks,summary=audit()
    if not summary['training_ready']:
        raise ValueError('No training export: every side train/validation image needs review or a reasoned deferral; all five diseases and normal negatives must remain in both splits. See annotation_tasks.csv.')
    by_id={t['sample_id']:t for t in tasks}
    destination=DATA/'yolo'
    if destination.exists(): raise FileExistsError('Existing detector export is protected')
    # Validation precedes ALL export writes; never include front/test in training.
    selected=[r for r in inventory if r['split'] in ('train','validation') and by_id[r['sample_id']]['review_status']=='reviewed']
    lines={r['sample_id']:validate_task(by_id[r['sample_id']],r) for r in selected}
    import os
    for r in selected:
        role='train' if r['split']=='train' else 'val'
        name=hashlib.sha256(r['sample_id'].encode()).hexdigest()
        image=destination/f'images/{role}/{name}.png'; label=destination/f'labels/{role}/{name}.txt'
        image.parent.mkdir(parents=True,exist_ok=True); label.parent.mkdir(parents=True,exist_ok=True)
        os.link(PROJECT/r['image_path'],image)
        label.write_text('\n'.join(lines[r['sample_id']])+ ('\n' if lines[r['sample_id']] else ''),encoding='utf-8')
    yaml='path: '+json.dumps(destination.resolve().as_posix())+'\ntrain: images/train\nval: images/val\nnames:\n'
    yaml+=''.join(f'  {k}: {v}\n' for k,v in NAMES.items())
    (destination/'data.yaml').write_text(yaml,encoding='utf-8')
    hashes={p.relative_to(destination).as_posix():sha(p) for p in destination.rglob('*') if p.is_file()}
    dump(destination/'provenance.json',{'manifest_sha256':summary['source_manifest_sha256'],
        'annotation_tasks_sha256':sha(DATA/'annotation_tasks.csv'),'sources':selected,'training_executed':False,
        'deferred_exclusions':[{'sample_id':r['sample_id'],'split':r['split'],'reason':by_id[r['sample_id']]['notes']}
                               for r in inventory if r['split'] in ('train','validation') and by_id[r['sample_id']]['review_status']=='deferred'],
        'export_file_sha256':hashes,'image_links_read_only_by_policy':True,'note':'Do not edit hardlinked images; edits affect raw source.'})


def verify_export_files(destination, provenance):
    hashes=provenance.get('export_file_sha256',{})
    if not hashes: raise ValueError('Export file hashes are required')
    for relative,expected in hashes.items():
        path=(destination/relative).resolve()
        if not path.is_relative_to(destination.resolve()) or sha(path)!=expected:
            raise ValueError('Exported image, label or data.yaml changed')


def validate_model(model):
    if model.task!='detect': raise ValueError('A detection model is required; -cls is not supported')
    names={int(k):v for k,v in model.names.items()}
    if names!=NAMES: raise ValueError('Requires trained five-class disease-region weights; COCO or skin_roi weights are not valid')
    architecture=model.model.yaml
    if architecture.get('scale')!='n' or architecture.get('yaml_file','').replace('\\','/').split('/')[-1] not in ('yolo11n.yaml','yolo11.yaml'):
        raise ValueError('Only YOLO11n architecture is allowed')


def train(weights, imgsz=640, epochs=30, batch=8):
    """Explicit future training entry; no automatic training during audit/prepare."""
    if active_label_source()=='provider_bbox_experiment':
        from audit_detection_labels import train as reuse_train
        return reuse_train(weights,imgsz,epochs,batch)
    destination=DATA/'yolo'; provenance_path=destination/'provenance.json'
    if not provenance_path.is_file() or not (destination/'data.yaml').is_file():
        raise ValueError('Training blocked: reviewed disease-region export and detection DataLoader check are required')
    provenance=json.loads(provenance_path.read_text(encoding='utf-8'))
    verify_export_files(destination,provenance)
    if (provenance['manifest_sha256']!=sha(PROJECT/'data/processed/manifest.csv')
            or provenance['annotation_tasks_sha256']!=sha(DATA/'annotation_tasks.csv')):
        raise ValueError('Training blocked: manifest or annotations changed after export')
    proof_path=destination/'loader_verification.json'
    if not proof_path.is_file(): raise ValueError('Training blocked: detection DataLoader has not been verified')
    proof=json.loads(proof_path.read_text(encoding='utf-8'))
    if proof.get('status')!='passed' or proof.get('annotation_tasks_sha256')!=provenance['annotation_tasks_sha256'] or proof.get('imgsz')!=imgsz:
        raise ValueError('Training blocked: DataLoader verification does not match annotations/input size')
    if not Path(weights).is_file(): raise ValueError('Local YOLO11n detection pretrained weights are required')
    run=PROJECT/'models/yolo11_detect/disease_regions'
    if run.exists(): raise FileExistsError('Existing detector training run is protected')
    for row in provenance['sources']:
        if row['split'] not in ('train','validation') or row['view']!='측면': raise ValueError('Non-side development data in training')
        if sha(PROJECT/row['image_path'])!=row['source_image_sha256']: raise ValueError('Training source image changed')
    return run_detection_training(weights,destination/'data.yaml',run,imgsz,epochs,batch)


def run_detection_training(weights,data_yaml,run,imgsz,epochs,batch):
    """One shared YOLO11n trainer for explicitly selected annotation experiments."""
    config_path=DATA/'config.json'
    if config_path.is_file():
        alignment=json.loads(config_path.read_text(encoding='utf-8')).get('annotation_alignment')
        if alignment and alignment.get('next_training_ready') is not True:
            raise ValueError('Common disease-region labels must be reviewed with recorded provenance and exported before new training; provider-box baseline is preserved')
    if not Path(weights).is_file():raise ValueError('Local YOLO11n detection pretrained weights are required')
    if run.exists():raise FileExistsError('Existing detector training run is protected')
    from ultralytics import YOLO
    model=YOLO(str(weights))
    if model.task!='detect': raise ValueError('Classification weights cannot initialize this detector')
    architecture=model.model.yaml
    if architecture.get('scale')!='n' or Path(architecture.get('yaml_file','')).name not in ('yolo11n.yaml','yolo11.yaml'):
        raise ValueError('Only YOLO11n detection weights are allowed')
    model.add_callback('on_train_start',lambda trainer:record_training_state(status='running',
        run_dir=run.relative_to(PROJECT).as_posix(),training_started_at_kst=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()))
    def first_batch(trainer):
        if not getattr(trainer,'_disease_first_batch_recorded',False):
            trainer._disease_first_batch_recorded=True
            record_training_state(training_executed=True,first_batch_completed=True)
    model.add_callback('on_train_batch_end',first_batch)
    model.add_callback('on_train_epoch_start',lambda trainer:record_training_state(current_epoch=trainer.epoch+1))
    def epoch_completed(trainer):
        metrics={str(k):float(v) if math.isfinite(float(v)) else None for k,v in trainer.metrics.items()}
        record_training_state(epochs_completed=trainer.epoch+1,metrics=metrics,
            best_weights=(run/'weights/best.pt').relative_to(PROJECT).as_posix() if (run/'weights/best.pt').is_file() else None,
            last_weights=(run/'weights/last.pt').relative_to(PROJECT).as_posix() if (run/'weights/last.pt').is_file() else None)
    model.add_callback('on_fit_epoch_end',epoch_completed)
    return model.train(data=str(data_yaml),imgsz=imgsz,epochs=epochs,batch=batch,
                project=str(run.parent),name=run.name,exist_ok=False,device='cpu',workers=0,
                seed=20261110,deterministic=True,patience=7,optimizer='AdamW',lr0=.001,
                mosaic=0.,mixup=0.,copy_paste=0.,degrees=0.,translate=0.,scale=0.,shear=0.,
                perspective=0.,flipud=0.,fliplr=0.,hsv_h=0.,hsv_s=0.,hsv_v=0.,
                close_mosaic=0,multi_scale=False)


def record_training_state(**updates):
    """Persist progress for the explicitly launched detector; never start a job."""
    path=TRAINING_OUT/'summary.json'
    if not path.is_file():return
    state=json.loads(path.read_text(encoding='utf-8'));state.update(updates)
    state['updated_at_kst']=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()
    state['elapsed_seconds']=round(time.time()-state['started_unix'],1)
    dump(path,state)
    for target in (OUT/'summary.json',OUT/'reuse_summary.json'):
        if not target.is_file():continue
        summary=json.loads(target.read_text(encoding='utf-8'))
        summary.update(training_executed=state['training_executed'],training_state=state['status'],
                       training_summary=path.relative_to(PROJECT).as_posix())
        if target.name=='summary.json':summary['status']='provider_bbox_detector_training_'+state['status']
        dump(target,summary)
    report=OUT/'report.md'
    if report.is_file():
        text=report.read_text(encoding='utf-8');start='<!-- detection-training-status:start -->';end='<!-- detection-training-status:end -->'
        if start in text and end in text:text=text.split(end,1)[1].lstrip('\n')
        banner=(f'{start}\n## 현재 탐지 학습 상태\n\n상태: {state["status"]} · 완료 epoch: {state.get("epochs_completed",0)}/{state["epochs"]} · '
                f'첫 배치 완료: {state.get("first_batch_completed",False)}. '
                f'[실행 상태](../training/disease_detection/summary.json) · [로그](../training/disease_detection/training.log). '
                f'갱신: {state["updated_at_kst"]}. 아래 준비·미실행 기록은 학습 시작 전 이력입니다.\n{end}\n\n')
        report.write_text(banner+text,encoding='utf-8')


def managed_train(weights,imgsz=640,epochs=30,batch=8):
    """Run once with durable logs and progress so the background job is observable."""
    TRAINING_OUT.mkdir(parents=True,exist_ok=True)
    path=TRAINING_OUT/'summary.json';log_path=TRAINING_OUT/'training.log'
    if path.exists() or log_path.exists():raise FileExistsError('Existing detection training logs are protected')
    state={'status':'preflight','pid':os.getpid(),'started_unix':time.time(),
        'started_at_kst':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
        'weights':Path(weights).resolve().relative_to(PROJECT).as_posix(),'weights_sha256':sha(weights),
        'imgsz':imgsz,'epochs':epochs,'batch':batch,'device':'cpu','workers':0,'seed':20261110,
        'optimizer':'AdamW','lr0':.001,'patience':7,'extra_augmentation':False,
        'epochs_completed':0,'training_executed':False,'first_batch_completed':False,
        'reuse_manifest_sha256':sha(DATA/'reuse_manifest.csv'),
        'loader_verification_sha256':sha(DATA/'provider_bbox_yolo/loader_verification.json'),
        'implementation_sha256':{p.name:sha(p) for p in (Path(__file__),PROJECT/'src/audit_detection_labels.py')}}
    dump(path,state)
    with log_path.open('x',encoding='utf-8',buffering=1) as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        try:
            print('Starting detector preflight: frozen inputs, exported bytes, lineage and raw JSON hashes.',flush=True)
            record_training_state()
            result=train(weights,imgsz,epochs,batch)
            record_training_state(status='completed',finished_at_kst=datetime.now(ZoneInfo('Asia/Seoul')).isoformat())
            return result
        except BaseException as error:
            traceback.print_exc()
            record_training_state(status='interrupted' if isinstance(error,KeyboardInterrupt) else 'failed',
                                  error=f'{type(error).__name__}: {error}')
            raise


def verify_loader(imgsz=640):
    """Read exported labels and decode every image, then exercise train/val batches."""
    if active_label_source()=='provider_bbox_experiment':
        from audit_detection_labels import verify_loader as reuse_verify
        return reuse_verify(imgsz)
    destination=DATA/'yolo'
    if not (destination/'provenance.json').is_file(): raise ValueError('No reviewed disease-region export to verify')
    provenance=json.loads((destination/'provenance.json').read_text(encoding='utf-8'))
    verify_export_files(destination,provenance)
    if provenance['annotation_tasks_sha256']!=sha(DATA/'annotation_tasks.csv'): raise ValueError('Annotations changed after export')
    from ultralytics.data.dataset import YOLODataset
    from ultralytics.cfg import get_cfg
    from torch.utils.data import DataLoader
    from ultralytics.data.utils import check_det_dataset
    data=check_det_dataset(str(destination/'data.yaml'),autodownload=False)
    counts={}
    for role in ('train','val'):
        dataset=YOLODataset(img_path=data[role],imgsz=imgsz,batch_size=2,augment=False,
                            hyp=get_cfg(),rect=False,cache=False,data=data,task='detect')
        expected=sum(r['split']==('train' if role=='train' else 'validation') for r in provenance['sources'])
        if len(dataset)!=expected: raise ValueError('Detection dataset count mismatch')
        for i in range(len(dataset)): dataset[i]
        batch=next(iter(DataLoader(dataset,batch_size=2,num_workers=0,collate_fn=dataset.collate_fn)))
        if tuple(batch['img'].shape[1:])!=(3,imgsz,imgsz): raise ValueError('Detection batch dimensions mismatch')
        counts[role]=len(dataset)
    proof={'status':'passed','imgsz':imgsz,'counts':counts,'annotation_tasks_sha256':provenance['annotation_tasks_sha256']}
    dump(destination/'loader_verification.json',proof)


def predict(model, image, mode='full', imgsz=640, tile_size=512, overlap=.25, conf=.25, merge_iou=.5, device='cpu',max_det=None):
    validate_model(model)
    if mode not in ('full','tiles') or imgsz not in (640,1024): raise ValueError('Invalid experiment')
    if not 0 < conf < 1: raise ValueError('Invalid confidence threshold')
    if max_det is not None and (type(max_det) is not int or max_det<1):raise ValueError('Invalid detection cap')
    image=ImageOps.exif_transpose(image).convert('RGB'); w,h=image.size
    regions=[[0,0,w,h]] if mode=='full' else windows(w,h,tile_size,overlap)
    detections=[]
    for index,region in enumerate(regions):
        crop=image.crop(region)
        options={'max_det':max_det} if max_det is not None else {}
        results=model.predict(source=crop,imgsz=imgsz,conf=conf,iou=merge_iou,augment=False,
                              rect=False,verbose=False,save=False,device=device,quantize=32,**options)
        for result in results:
            if result.boxes is None: continue
            for b,c,s in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.cls.cpu().tolist(), result.boxes.conf.cpu().tolist()):
                cid=int(c)
                if c!=cid or cid not in NAMES: raise ValueError('Invalid predicted class')
                if not box_valid(b,crop.width,crop.height) or not math.isfinite(s) or not 0 <= s <= 1: raise ValueError('Invalid prediction')
                box=[b[0]+region[0],b[1]+region[1],b[2]+region[0],b[3]+region[1]]
                detections.append({'class_id':cid,'label':LABELS[cid],'confidence':s,'box_xyxy':box,'tile_index':index})
    merged=merge_detections(detections,merge_iou)
    if max_det is not None:merged=merged[:max_det]
    scores={}
    for d in merged: scores[d['label']]=max(scores.get(d['label'],0),d['confidence'])
    return {'status':'candidates_for_review' if merged else 'not_detected_needs_review','normal_confirmed':False,
        'task':'detect','mode':mode,'imgsz':imgsz,'tile_size':tile_size if mode=='tiles' else None,
        'overlap':overlap if mode=='tiles' else None,'confidence_threshold':conf,'merge_iou':merge_iou,
        'coordinate_space':'exif_oriented_original_pixels','image_size':[w,h],'model_instances':1,
        'regions':regions,'detections':merged,'candidate_max_detection_scores':scores,
        'score_is_calibrated_image_probability':False}


def train_front_localizer(imgsz=640,epochs=30,batch=4):
    """Explicitly authorized front-only trial; separate state, weights and post-fit audit."""
    import torch
    import cv2
    from ultralytics import YOLO
    dataset=DATA/'front_localization_yolo'
    output=PROJECT/'outputs/training/front_lesion_localizer'
    run=PROJECT/'models/yolo11_detect/front_lesion_localizer'
    weight=PROJECT/'models/pretrained/yolo11n.pt'
    side=PROJECT/'models/yolo11_detect/provider_bbox_augmented/weights/best.pt'
    state_path=output/'summary.json'
    if run.exists() or state_path.exists():raise FileExistsError('Existing front training run is protected')
    proof=json.loads((dataset/'loader_verification.json').read_text(encoding='utf-8'))
    provenance=json.loads((dataset/'provenance.json').read_text(encoding='utf-8'))
    if proof['status']!='passed' or proof['imgsz']!=imgsz or proof['provenance_sha256']!=sha(dataset/'provenance.json'):
        raise ValueError('A matching front loader proof is required')
    verify_export_files(dataset,provenance)
    if provenance['counts']!={'train':82,'val':11} or provenance['group_overlap'] or provenance['source_image_hash_overlap']:
        raise ValueError('Unexpected front data or leakage')
    from ultralytics.utils import YAML
    if YAML.load(dataset/'data.yaml')['names']!={0:'lesion_region'}:
        raise ValueError('Front training requires exactly one lesion_region class')
    if not weight.is_file():raise FileNotFoundError('Local YOLO11n initialization missing')
    torch.set_num_threads(4);cv2.setNumThreads(1)
    settings=dict(data=str(dataset/'data.yaml'),imgsz=imgsz,epochs=epochs,batch=batch,nbs=batch,
        project=str(output.parent),name=output.name,exist_ok=True,device='cpu',workers=0,
        seed=20261111,deterministic=True,patience=7,optimizer='AdamW',lr0=.001,
        warmup_epochs=1.,amp=False,cache=False,save=True,plots=True,
        mosaic=0.,mixup=0.,cutmix=0.,copy_paste=0.,degrees=0.,translate=0.,scale=0.,shear=0.,
        perspective=0.,flipud=0.,fliplr=0.,hsv_h=0.,hsv_s=0.,hsv_v=0.,
        close_mosaic=0,multi_scale=False,freeze=None)
    output.mkdir(parents=True,exist_ok=True)
    state={'status':'starting','pid':os.getpid(),'started_unix':time.time(),
        'authorization':'current user explicitly requested front localizer training',
        'training_authorized':True,'training_executed':False,'epochs_completed':0,
        'epochs':epochs,'imgsz':imgsz,'batch':batch,'device':'cpu','additional_augmentation':False,
        'dataset_provenance_sha256':sha(dataset/'provenance.json'),
        'initial_weights_sha256':sha(weight),'side_model_sha256':sha(side),
        'trained_weights_dir':run.relative_to(PROJECT).as_posix(),
        'independent_final_test':False,'patient_identity_verified':False,
        'settings':settings,'train_counts':provenance['counts']}
    def progress(**updates):
        state.update(updates);state['updated_at_kst']=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()
        state['elapsed_seconds']=round(time.time()-state['started_unix'],1)
        dump(state_path,state)
    progress()
    try:
        model=YOLO(str(weight))
        architecture=model.model.yaml
        if model.task!='detect' or architecture.get('scale')!='n' or Path(architecture.get('yaml_file','')).name not in ('yolo11n.yaml','yolo11.yaml'):
            raise ValueError('Only local YOLO11n detect initialization is allowed')
        def started(trainer):
            # Keep plots/logs under outputs and all trained checkpoints under models.
            trainer.wdir=run/'weights';trainer.wdir.mkdir(parents=True,exist_ok=False)
            trainer.last=trainer.wdir/'last.pt';trainer.best=trainer.wdir/'best.pt'
            progress(status='running',training_started_at_kst=datetime.now(ZoneInfo('Asia/Seoul')).isoformat())
        model.add_callback('on_train_start',started)
        def first_batch(trainer):
            if not state['training_executed']:progress(training_executed=True,first_batch_completed=True)
        model.add_callback('on_train_batch_end',first_batch)
        model.add_callback('on_train_epoch_start',lambda t:progress(current_epoch=t.epoch+1))
        def completed_epoch(trainer):
            metrics={str(k):float(v) if math.isfinite(float(v)) else None for k,v in trainer.metrics.items()}
            progress(epochs_completed=trainer.epoch+1,metrics=metrics,
                best_weights=(trainer.best.relative_to(PROJECT).as_posix() if trainer.best.exists() else None),
                last_weights=(trainer.last.relative_to(PROJECT).as_posix() if trainer.last.exists() else None))
        model.add_callback('on_fit_epoch_end',completed_epoch)
        fit_metrics=model.train(**settings)
        best=run/'weights/best.pt'
        if not best.is_file():raise ValueError('Training ended without best weights')
        progress(status='evaluating',best_weights=best.relative_to(PROJECT).as_posix(),best_weights_sha256=sha(best))
        trained=YOLO(str(best))
        if trained.names!={0:'lesion_region'}:raise ValueError('Unexpected front model names')
        rows=[r for r in provenance['sources'] if r['split']=='val']
        predictions=[];total={'tp':0,'fp':0,'fn':0};normal_images=0;normal_fp=0
        from audit_detection_labels import localization_proposal_metrics
        from PIL import ImageDraw
        sheet=Image.new('RGB',(1536,1260),'white');pen=ImageDraw.Draw(sheet)
        for index,row in enumerate(rows):
            image_path=dataset/row['image_path']
            pred=trained.predict(source=str(image_path),imgsz=imgsz,conf=.25,iou=.7,
                device='cpu',augment=False,rect=False,verbose=False)[0]
            boxes=[b for b in pred.boxes.xyxy.cpu().tolist()]
            scores=pred.boxes.conf.cpu().tolist()
            counts=localization_proposal_metrics(row['boxes_xyxy'],boxes,.5)
            for key in total:total[key]+=counts[key]
            if row['source_class_id']==3:normal_images+=1;normal_fp+=bool(boxes)
            predictions.append({'reference_id':row['reference_id'],'sample_id':row['sample_id'],
                'boxes':boxes,'scores':scores,'reference_boxes':row['boxes_xyxy'],'matches_iou050':counts})
            with Image.open(image_path) as im:tile=im.convert('RGB')
            draw=ImageDraw.Draw(tile)
            for b in row['boxes_xyxy']:draw.rectangle(b,outline='#00ff60',width=4)
            for b in boxes:draw.rectangle(b,outline='#ff9500',width=4)
            x=index%4*384;y=index//4*420;sheet.paste(tile.resize((384,384)),(x,y))
            pen.text((x+5,y+386),row['reference_id']+' reference green / prediction orange',fill='black')
        sheet.save(output/'validation_boxes.jpg',quality=94)
        dump(output/'validation_predictions.json',predictions)
        audit={'confidence':.25,'nms_iou':.7,'matching_iou':.5,'counts':total,
            'region_recall':total['tp']/(total['tp']+total['fn']) if total['tp']+total['fn'] else None,
            'precision':total['tp']/(total['tp']+total['fp']) if total['tp']+total['fp'] else None,
            'normal_images':normal_images,'normal_false_positive_images':normal_fp,
            'normal_false_positive_rate':normal_fp/normal_images if normal_images else None,
            'development_only':True,'normal_sample_too_small_for_generalization':True}
        dump(output/'validation_audit.json',audit)
        if sha(side)!=state['side_model_sha256']:raise ValueError('Existing side model changed')
        verify_export_files(dataset,provenance)
        with (output/'results.csv').open(encoding='utf-8-sig',newline='') as stream:
            epoch_rows=list(csv.DictReader(stream))
        final_metrics={str(k):float(v) for k,v in fit_metrics.results_dict.items()}
        progress(status='completed',validation_audit=audit,side_model_unchanged=True,
            epochs_completed=len(epoch_rows),best_epoch=int(max(epoch_rows,key=lambda r:float(r['metrics/mAP50-95(B)']))['epoch']),
            metrics=final_metrics,best_checkpoint_training_metrics=trained.ckpt.get('train_metrics',{}),
            metrics_source='final best-weight validation; actual completed epoch count from results.csv (final-validation callbacks do not add a training epoch)')
    except BaseException as exc:
        progress(status='failed',error=str(exc),traceback=traceback.format_exc());raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--audit',action='store_true'); group.add_argument('--prepare',action='store_true'); group.add_argument('--predict',action='store_true')
    group.add_argument('--verify-loader',action='store_true'); group.add_argument('--train',action='store_true')
    group.add_argument('--train-front-localizer',action='store_true')
    group.add_argument('--review-progress',action='store_true',help='Refresh the read-only side annotation gallery')
    parser.add_argument('--weights',type=Path); parser.add_argument('--source',type=Path); parser.add_argument('--output',type=Path)
    parser.add_argument('--mode',choices=('full','tiles'),default='full'); parser.add_argument('--imgsz',type=int,choices=(640,1024),default=640)
    parser.add_argument('--tile-size',type=int,default=512); parser.add_argument('--overlap',type=float,default=.25)
    parser.add_argument('--conf',type=float,default=.25); parser.add_argument('--merge-iou',type=float,default=.5)
    parser.add_argument('--epochs',type=int,default=30); parser.add_argument('--batch',type=int,default=8)
    args=parser.parse_args()
    if args.train_front_localizer:
        if min(args.epochs,args.batch)<1:parser.error('Positive epochs and batch required')
        train_front_localizer(args.imgsz,args.epochs,args.batch)
    elif args.audit: audit()
    elif args.prepare: prepare()
    elif args.review_progress: print(json.dumps(publish_annotation_review(),ensure_ascii=False))
    elif args.verify_loader: verify_loader(args.imgsz)
    elif args.train:
        if not args.weights or min(args.epochs,args.batch)<1: parser.error('Local detection weights and positive epochs/batch required')
        managed_train(args.weights,args.imgsz,args.epochs,args.batch)
    else:
        if not args.weights or not args.weights.is_file() or not args.source or not args.source.is_file() or not args.output:
            parser.error('Local trained weights, source image and new output JSON are required')
        output=args.output.resolve()
        if not output.is_relative_to((PROJECT/'outputs').resolve()): parser.error('Output must be under outputs/')
        if output.exists(): raise FileExistsError('Existing predictions are protected')
        from ultralytics import YOLO
        model=YOLO(str(args.weights))
        with Image.open(args.source) as image:
            result=predict(model,image,args.mode,args.imgsz,args.tile_size,args.overlap,args.conf,args.merge_iou)
        result.update(weights_sha256=sha(args.weights),source_sha256=sha(args.source))
        dump(output,result)


if __name__=='__main__': main()
