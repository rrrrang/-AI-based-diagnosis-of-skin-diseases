# 측면·근접 피부 사진 병명 후보 모델 전달

전달 모델은 정상 보강 재학습한 YOLO11n이다. 모델 버전은 `yolo11n-side-hard-negative-20261112`, 가중치는 `models/yolo11_detect/side_hard_negative/weights/best.pt`, SHA256은 `5578f2729fd6e76001febff9109c81ae2482527ebddd3bc83bda783ef38f60a7`이다. 사진별 5질환 병명 후보와 질환별 최대 탐지 점수만 반환한다. 정면 위치 모델과 이전 측면 모델은 이 ZIP에 포함하지 않는다.

Python3.12 Windows CPU 환경에서 6장 실제 validation 사진의 추론 결과를 저장된 새 모델 예측과 대조했다. ZIP을 별도 임시 폴더에 추출한 CLI 실행도 확인했다. 자세한 실행 결과와 의존성 버전은 validation.json에 있다. 다른 OS/백엔드 환경 설치·성능은 아직 검증하지 않았다. requirements.txt는 프로젝트의 검증 환경 버전을 그대로 포함한다.

설치: `python -m pip install -r requirements.txt`

CLI: `python src/backend_inference.py --source photo.png --image-id case-image-1 --role side_closeup --output result.json`

Python API: src를 import 경로에 추가한 뒤 `from backend_inference import DiseasePredictor`; 워커 시작 시 `predictor = DiseasePredictor()` 한 번 생성하고 `predictor.predict(image, image_id="case-image-1", role="side_closeup")`를 호출한다. image는 PIL 이미지 또는 로컬 경로다. 워커별 인스턴스를 두고 같은 인스턴스의 동시 호출은 직렬화한다. 잘못된 이미지·가중치 오류는 예외로 반환하므로 HTTP 계층에서 입력 오류/서버 오류를 매핑한다. 현재 HTTP 서버·엔드포인트는 구현하지 않았다.

입력은 모델 평가와 유사한 측면/근접 피부 사진이다. 정면 이미지를 side_closeup으로 잘못 지정했는지 자동 판별하는 기능은 없다. 사진 역할은 업로드 메타데이터에서 확인해야 한다. front는 unsupported_input이며 병명을 부여하지 않는다. 얼굴 전체 또는 잘못된 촬영은 지원 성능 범위가 아니다.

imgsz640, confidence0.25, NMS IoU0.7, full 입력, rect=False, RGB/EXIF 방향 정리, 추가 증강 없음, CPU 고정이다. 기존 실험 CLI의 IoU0.5 기본값은 그대로이며 백엔드는 이 진입점을 사용한다.

응답 예시는 example_response.json, 규격은 contract.json이다. 5질환을 고정 순서로 반환하고 score는0~1 또는null이다. score×100을 '질환별 AI 탐지 점수'로 표시할 수 있으나 합계100%로 정규화하거나 발병/진단 확률로 표시하면 안 된다. 미검출은 null/미검출이며 전체 미검출은 undetermined다. 정상·기타 확률을 만들거나 미검출을 정상으로 판정하지 않는다. top_candidate는 참고 후보이며 확정 진단이 아니다. 위치 좌표·크롭·정면 위치 연결은 반환하지 않는다.

같은 측면 test535장 기준 병명 정답은 기존429/446(96.19%)에서 새 모델442/446(99.10%)로, 정상 사진의 질환 후보 발생은12/89에서0/89로 바뀌었다. 질환 미검출은0→1장이다. 질환별 정답은 건선87/89·아토피87/89·여드름89/89·주사90/90·지루89/89다. 이전 정답에서 새로 틀린 아토피2장(건선 오분류1·미검출1)이 있어 모든 사례에서 개선된 것은 아니다. 기존에 관찰한 test이며 환자 독립성을 보장하지 않는다. 정상0/89를 일반화 오탐0%나 정상 확정 능력으로 해석하지 않는다. 이번6장 smoke는 호출 검증이며 성능 재평가가 아니다. 의사 검토/판단 유보를 유지한다.

정상 클래스·정상 확률은 제공하지 않는다. 기존 모델용 6범주 보정계수는 새 모델에 적용하지 않으며 패키지에도 포함하지 않는다. 점수 보정이 필요하면 새 모델의 validation 예측으로 별도 개발·검증해야 한다.

전달 파일은 `side_disease_backend.zip` 하나다. 새 best.pt, 추론 코드와 adapter, requirements.txt, 규격·응답 예시·검증 기록·새 측면 평가 근거·파일별 SHA manifest.json을 포함한다. 환자 사진·원천 데이터·학습 ZIP·보정계수는 포함하지 않는다. ZIP은 디렉터리 구조를 유지해 추출하고 추출 루트에서 실행한다. `src/prepare_backend_handoff.py`는 프로젝트 관리자가 패키지를 재생성하는 로컬 도구이며 전달 ZIP의 추론 실행에는 필요 없다.

Git에는 코드·의존성·규격·검증 문서를 올리고 모델 가중치는 비공개 저장소의 Git LFS 또는 접근이 제한된 별도 아티팩트로 관리할 수 있다. 현재 `.gitignore`는 `models/**/*.pt`를 제외하므로 일반 git add만으로 가중치가 포함되지 않는다. ZIP에는 가중치가 있으므로 Git 일반 파일에 ZIP을 중복 등록하기보다 별도 전달 아티팩트로 사용한다. 어떤 방식이든 contract.json의 경로와 SHA를 유지한다. 이 작업에서는 원격 저장소 업로드·외부 전송·배포를 실행하지 않았다.

대상 백엔드에서 패키지 설치, HTTP 입력 오류 매핑, 파일 접근 권한, 요청 제한, 동시 호출·지연을 검증한 뒤 적용한다. 기본값은 CPU이며 GPU/ONNX 전환은 별도 동등성 검증이 필요하다.
