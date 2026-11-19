import {
  apiEnabled,
  requestDoctorAnalysis
} from "../../services/api";

/**
 * PatientReview.tsx
 *
 * 왼쪽: 환자가 제출한 자료
 * 오른쪽: AI 분석 이미지 및 질환별 예측 점수
 * 하단: 의사 최종 소견 작성
 */

import { useEffect, useRef, useState } from "react";

import {
  Camera,
  CheckCircle2,
  ClipboardList,
  Info,
  ScanFace,
  Stethoscope,
} from "lucide-react";

import type {
  DoctorCase,
  Prediction,
} from "../../types/doctorCase";

import {
  saveDoctorCase,
} from "../../services/doctorCases";

/* ==========================================
   1. 전달받는 데이터
========================================== */

interface Props {
  patient: DoctorCase | null;
  onSaved: () => Promise<void>;
}

// 성별 표시
const GENDER = {
  female: "여성",
  male: "남성",
  none: "미선택",
};

// 환자 사진 이름
const PHOTO_LABELS = [
  "전체 부위",
  "상세 부위 1",
  "상세 부위 2",
];

// 실제 AI 결과가 아닌 시연용 점수
const DEMO_PREDICTIONS: Prediction[] = [
  { label: "질환 후보 A", score: 68 },
  { label: "질환 후보 B", score: 23 },
  { label: "기타 후보", score: 9 },
];

// 실제 AI 모델 분석 대상 6개 클래스
const CLASS_LABELS = {
  psoriasis: "건선",
  atopic_dermatitis: "아토피",
  acne: "여드름",
  normal: "정상",
  rosacea: "주사",
  seborrheic_dermatitis: "지루성 피부염",
};

/* ==========================================
   2. 사진 표시 컴포넌트
========================================== */

function PreviewPhoto({
  photo,
  label,
}: {
  photo: File | Blob | null | undefined;
  label: string;
}) {
  const [url, setUrl] = useState("");

  useEffect(() => {
    if (!photo) {
      setUrl("");
      return;
    }

    // 업로드한 사진을 미리보기 URL로 변환
    const objectUrl = URL.createObjectURL(photo);

    setUrl(objectUrl);

    // 컴포넌트 해제 시 메모리 정리
    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [photo]);

  return (
    <div className="doctor-photo-item">
      <div className="doctor-photo-box">
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            title={`${label} 크게 보기`}
          >
            <img src={url} alt={label} />
          </a>
        ) : (
          <div className="doctor-photo-empty">
            <Camera size={24} />
            <span>미등록</span>
          </div>
        )}
      </div>

      <span>{label}</span>
    </div>
  );
}

/* ==========================================
   3. 세로 막대그래프 컴포넌트
========================================== */

function VerticalPredictionChart({
  data,
  isDemo,
}: {
  data: Prediction[];
  isDemo: boolean;
}) {
  // 최대 6개 후보 표시
  // 높은 점수 순서대로 정렬
  const entries = [...data]
    .sort((a, b) => b.score - a.score)
    .slice(0, 6);

  return (
    <div className="doctor-chart-section">
      <div className="doctor-chart-header">
      <h3>
        {isDemo
          ? "질환별 AI 예측 점수"
          : "질환별 AI 예측 점수 (ResNet50)"}
      </h3>

        {isDemo && (
          <span className="doctor-status is-demo">
            시연용 수치
          </span>
        )}
      </div>

      <div className="doctor-chart">

        {/* Y축: 0~100 */}
        <div className="doctor-chart-axis">
          <span>100</span>
          <span>75</span>
          <span>50</span>
          <span>25</span>
          <span>0</span>
        </div>

        {/* 그래프 영역 */}
        <div className="doctor-chart-plot">

          {/* 가로 기준선 */}
          <div className="doctor-chart-gridlines">
            <i />
            <i />
            <i />
            <i />
            <i />
          </div>

          {/* 질환별 세로 막대 */}
          <div className="doctor-chart-columns">
            {entries.map((item, index) => {
              const score = Math.max(
                0,
                Math.min(100, item.score)
              );

              return (
                <div
                  key={`${item.label}-${index}`}
                  className="doctor-chart-column"
                >
                  <div className="doctor-chart-bar-area">
                    <div
                      className={`doctor-chart-bar ${
                        index === 0
                          ? "is-primary"
                          : ""
                      }`}
                      style={{
                        height: `${score}%`,
                        minHeight: 0,
                      }}
                      >
                        <span>{item.score.toFixed(1)}%</span>
                      </div>
                  </div>

                  <div
                    className="doctor-chart-name"
                    title={item.label}
                  >
                    {item.label}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <p className="doctor-hint">
        AI 예측 점수는 확정 진단이나
        실제 진단 정확도를 의미하지 않습니다.
      </p>
    </div>
  );
}

/* ==========================================
   4. 환자 상세 검토 화면
========================================== */

export default function PatientReview({
  patient,
  onSaved,
}: Props) {
  // 의사의 최종 판단
  const [diagnosis, setDiagnosis] = useState("");

  // 의사 검토 의견
  const [opinion, setOpinion] = useState("");

  // 대면 진료 권고 여부
  const [visitRequired, setVisitRequired] =
    useState(false);

  // 환자에게 전달할 내원 안내
  const [visitMessage, setVisitMessage] =
    useState("");

  
  // AI 분석 요청 상태
  const [requestingAnalysis, setRequestingAnalysis] =
    useState(false);

  const [analysisRequestError, setAnalysisRequestError] =
    useState("");

  const [queuedLocally, setQueuedLocally] =
    useState(false);

  // 중복 분석 요청 방지
  const analysisRequestLock = useRef(false);

  // 결과 저장 상태
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  // 최종 결과 확정 확인창
  const [showConfirm, setShowConfirm] =
    useState(false);

  /* ========================================
     5. 선택 환자 변경 시 소견 불러오기
  ======================================== */

  useEffect(() => {
    setDiagnosis(patient?.diagnosis ?? "");

    setOpinion(patient?.opinion ?? "");

    setVisitRequired(
      patient?.visitRequired ?? false
    );

    setVisitMessage(
      patient?.visitMessage ?? ""
    );

    setSaveError("");
    setShowConfirm(false);
  }, [
    patient?.id,
    patient?.diagnosis,
    patient?.opinion,
    patient?.visitRequired,
    patient?.visitMessage,
  ]);

  /* ========================================
     6. AI 분석 및 검토 상태
  ======================================== */

  const resultAvailable =
    patient?.aiState === "완료" ||
    patient?.aiState === "시연 결과";

    // 실제 AI 모델에서 반환한 전체 예측 점수
  const scores = patient?.analysis?.resnetClassScores;

  // 질환별 세로 막대그래프 데이터
  const classPredictions: Prediction[] =
    scores &&
    Object.keys(CLASS_LABELS).every(
      (code) =>
        Number.isFinite(scores[code]) &&
        scores[code] >= 0 &&
        scores[code] <= 1
    )
      ? Object.entries(CLASS_LABELS).map(
          ([code, label]) => ({
            label,
            score: scores[code] * 100,
          })
        )
      : [];

  const isFinal =
    patient?.reviewState === "결과 전달 완료";
  
    
    // AI 분석 작업 진행 여부
    const jobActive =
      patient?.analysisJobState === "pending" ||
      patient?.analysisJobState === "processing" ||
      patient?.aiState === "분석 중" ||
      (
        queuedLocally &&
        patient?.analysisJobState == null &&
        patient?.aiState === "대기"
      );
  
    // AI 분석 요청 가능 여부
    const canRequestAnalysis =
      !!patient &&
      !isFinal &&
      !jobActive &&
      !requestingAnalysis &&
      (
        patient.aiState === "대기" ||
        patient.aiState === "실패"
      );
  
    // 실제 AI 모델 분석 요청
    const startAnalysis = async () => {
      if (
        !patient ||
        !canRequestAnalysis ||
        analysisRequestLock.current
      ) return;
  
      analysisRequestLock.current = true;
  
      setRequestingAnalysis(true);
      setAnalysisRequestError("");
  
      try {
        const result = await requestDoctorAnalysis(
          patient.id,
          patient.aiState === "실패"
        );
  
        setQueuedLocally(
          result.state === "pending" ||
          result.state === "processing"
        );
  
        await onSaved();
  
      } catch (error) {
        setAnalysisRequestError(
          error instanceof Error
            ? error.message
            : "AI 분석 요청에 실패했습니다."
        );
  
      } finally {
        analysisRequestLock.current = false;
        setRequestingAnalysis(false);
      }
    };
  

  // 실제 AI 분석 결과 또는 명시된 시연 결과가
  // 있을 때만 소견 작성 가능
  const editable =
    !!patient &&
    resultAvailable &&
    !isFinal;

  // 필수 입력 확인
  const valid =
    diagnosis.trim().length > 0 &&
    opinion.trim().length > 0 &&
    (
      !visitRequired ||
      visitMessage.trim().length > 0
    );

  /* ========================================
     7. 의사 소견 저장
  ======================================== */

  const save = async (final: boolean) => {
    if (
      !patient ||
      !editable ||
      (final && !valid)
    ) {
      return;
    }

    setSaving(true);
    setSaveError("");

    try {
      await saveDoctorCase({
        ...patient,

        diagnosis: diagnosis.trim(),
        opinion: opinion.trim(),

        visitRequired,
        visitMessage: visitMessage.trim(),

        reviewState: final
          ? "결과 전달 완료"
          : "임시 저장",

        updatedAt: new Date().toISOString(),
      });

      // 예약 관리표의 상태 갱신
      await onSaved();

      setShowConfirm(false);
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error.message
          : "저장에 실패했습니다."
      );
    } finally {
      setSaving(false);
    }
  };

  /* ========================================
     8. AI 예측 그래프 시연
  ======================================== */

  const applyDemo = async () => {
    if (!patient || patient.aiState !== "대기") {
      return;
    }

    setSaving(true);
    setSaveError("");

    try {
      await saveDoctorCase({
        ...patient,

        // 실제 모델 결과가 아닌 시연 결과
        aiState: "시연 결과",
        predictions: DEMO_PREDICTIONS,

        // 상세 부위 사진을 시연용 분석 원본으로 사용
        analysisPhoto: patient.photos[1] ?? patient.photos[2] ?? null,

        // 실제 마스킹 이미지가 없어 비워 둠
        maskPhoto: null,

        updatedAt: new Date().toISOString(),
      });

      await onSaved();
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error.message
          : "시연 결과 표시 실패"
      );
    } finally {
      setSaving(false);
    }
  };

  /* ========================================
     9. 화면 표시
  ======================================== */

  return (
    <>
      {/* 중단: 환자 자료 / AI 분석 */}
      <div className="doctor-review-split">

        {/* ================================
            왼쪽: 환자 자료 확인
        ================================ */}
        <section className="doctor-panel doctor-patient-panel">
          <h2>
            <ClipboardList size={20} />
            환자 자료 확인
          </h2>

          {!patient ? (
            <div className="doctor-empty-review">
              상단 예약 목록에서
              검토할 환자를 선택해 주세요.
            </div>
          ) : (
            <>
              {/* 환자 기본 정보 */}
              <div className="doctor-info-card">
                <strong>
                  {patient.patientName}
                  {" · "}
                  {patient.age}세
                  {patient.patientPhone && ` · ${patient.patientPhone}`} 
                  {" · "}
                  {GENDER[patient.gender]}
                </strong>

                <span>
                  예약 {patient.date} {patient.time}
                  {" · "}
                  접수번호 {patient.id.slice(0, 16)}
                </span>
              </div>

              {/* 등록 사진 */}
              <h3>환자가 등록한 사진</h3>

              <div className="doctor-photo-grid">
                {PHOTO_LABELS.map((label, index) => (
                  <PreviewPhoto
                    key={`${patient.id}-${index}`}
                    photo={patient.photos[index]}
                    label={label}
                  />
                ))}
              </div>

              {/* 선택 증상 */}
              <h3>환자 증상 및 발생 시점</h3>

              <div className="doctor-symptoms">
                <div>
                  {patient.symptoms.map((symptom) => (
                    <span key={symptom}>
                      {symptom}
                    </span>
                  ))}
                </div>

                <p>
                  증상 시작: {patient.duration}
                </p>
              </div>

              {/* 상세 문진 */}
              <h3>환자 상세 증상·원문</h3>

              <div className="doctor-patient-words">
                {patient.description ||
                  "작성된 상세 증상이 없습니다."}
              </div>
            </>
          )}
        </section>

        {/* ================================
            오른쪽: AI 분석 결과
        ================================ */}
        <section className="doctor-panel doctor-ai-panel">
          <h2>
            <ScanFace size={20} />
            AI 분석 결과
          </h2>

          {!patient ? (
            <div className="doctor-empty-review">
              환자를 선택하면
              AI 분석 결과가 표시됩니다.
            </div>
          ) : (
            <>
              {/* AI 진행 상태 */}
              <div className="doctor-ai-state">
                분석 상태

                <span
                  className={`doctor-status ${
                    patient.aiState === "완료"
                      ? "is-done"
                      : patient.aiState === "시연 결과"
                        ? "is-demo"
                        : "is-wait"
                  }`}
                >
                  {patient.aiState}
                </span>
              </div>

              {/* 실제 AI 분석 요청 버튼 */}
              {apiEnabled && (
                <div className="doctor-demo-action">
                  <button
                    type="button"
                    disabled={!canRequestAnalysis}
                    onClick={() => void startAnalysis()}
                  >
                    {requestingAnalysis
                      ? "분석 요청 중..."
                      : patient.aiState === "완료"
                        ? "AI 분석 완료"
                        : jobActive
                          ? "AI 분석 진행 중..."
                          : patient.aiState === "실패"
                            ? "AI 분석 재요청"
                            : "AI 분석 요청"}
                  </button>
              
                  {jobActive && (
                    <p role="status">
                      AI 분석 중입니다.
                      결과가 자동으로 갱신됩니다.
                    </p>
                  )}
              
                  {analysisRequestError && (
                    <p
                      className="doctor-error"
                      role="alert"
                    >
                      {analysisRequestError}
                    </p>
                  )}
                </div>
              )}


              {/* AI 원본 / 마스킹 이미지 */}
              <h3>분석 이미지 비교</h3>

              <div className="doctor-ai-photo-grid">
                <PreviewPhoto
                  photo={patient.analysisPhoto}
                  label="AI 분석 원본"
                />

                <PreviewPhoto
                  photo={patient.maskPhoto}
                  label="마스킹 이미지 (Grad-CAM)"
                />
              </div>

              {apiEnabled && patient.aiState === "완료" && !patient.maskPhoto && (
                <p>{patient.analysis?.overlayAvailable
                  ? "Grad-CAM 이미지를 불러오는 중이거나 조회하지 못했습니다."
                  : "이번 분석에는 Grad-CAM 이미지가 생성되지 않았습니다."}</p>
              )}



              {/* 질환별 세로 막대그래프 */}
              {apiEnabled ? (
                patient.aiState === "완료" &&
                classPredictions.length === 6 ? (
                  <VerticalPredictionChart
                    data={classPredictions}
                    isDemo={false}
                  />
                ) : (
                  <div className="doctor-analysis-pending">
                    <Info size={20} />

                    <div>
                      <strong>
                        {patient.aiState === "실패"
                          ? "AI 분석 실패"
                          : patient.aiState === "완료"
                            ? "질환별 예측 점수가 없습니다."
                            : "AI 분석 결과 대기 중"}
                      </strong>

                      <p>
                        {patient.aiState === "실패"
                          ? "AI 분석을 다시 요청해 주세요."
                          : patient.aiState === "완료"
                            ? "업데이트된 AI 워커로 새 분석을 진행해 주세요."
                            : "분석 완료 후 질환별 예측 점수가 표시됩니다."}
                      </p>
                    </div>
                  </div>
                )
              ) : resultAvailable &&
                patient.predictions.length > 0 ? (
                <VerticalPredictionChart
                  data={patient.predictions}
                  isDemo={
                    patient.aiState === "시연 결과"
                  }
                />
              ) : (
                <div className="doctor-analysis-pending">
                  <Info size={20} />

                  <div>
                    <strong>
                      AI 분석 결과가 아직 없습니다.
                    </strong>

                    <p>
                      실제 모델 연결 후
                      AI 분석 이미지, 마스킹 이미지,
                      질환별 세로 그래프가 표시됩니다.
                    </p>
                  </div>
                </div>
              )}



              {/* AI 미연결 시 테스트 버튼 */}
              {!apiEnabled && patient.aiState === "대기" && (
                <div className="doctor-demo-action">
                  <button
                    type="button"
                    disabled={saving}
                    onClick={() => void applyDemo()}
                  >
                    시연용 예측 그래프 표시
                  </button>

                  <p>
                    가상 점수를 사용한 UI 테스트이며
                    실제 AI 분석 결과가 아닙니다.
                  </p>
                </div>
              )}

              {patient.aiState === "시연 결과" && (
                <p className="doctor-hint">
                  마스킹 이미지는 실제 모델이
                  연결된 후에 표시됩니다.
                </p>
              )}
            </>
          )}
        </section>
      </div>

      {/* ================================
          하단: 의사 최종 진단 및 소견
      ================================ */}
      <section className="doctor-panel doctor-final-panel">
        <h2>
          <Stethoscope size={21} />
          의사 최종 진단 및 소견 작성
        </h2>

        {!patient ? (
          <div className="doctor-empty-review">
            환자를 선택하면
            최종 소견 작성 영역이 표시됩니다.
          </div>
        ) : (
          <>
            {!resultAvailable && (
              <p className="doctor-alert">
                AI 분석 결과가 준비되지 않아
                최종 소견을 확정할 수 없습니다.
              </p>
            )}

            {isFinal && (
              <p className="doctor-success">
                <CheckCircle2 size={18} />
                {apiEnabled ? "의사 검토 결과가 확정되어 서버에 저장되었습니다." : "최종 모의 결과가 확정되었습니다. 현재는 로컬 시연 저장 상태입니다."}
              </p>
            )}

            <div className="doctor-final-fields">

              {/* 의심 질환 */}
              <label className="doctor-field">
                <span>
                  의심 질환·모의 결과 <b>*</b>
                </span>

                <input
                  type="text"
                  value={diagnosis}
                  disabled={!editable}
                  placeholder="질환 후보 또는 판단 보류"
                  onChange={(event) =>
                    setDiagnosis(event.target.value)
                  }
                />
              </label>

              {/* 의사 검토 의견 */}
              <label className="doctor-field doctor-opinion-field">
                <span>
                  의사 검토 소견 <b>*</b>
                </span>

                <textarea
                  rows={4}
                  value={opinion}
                  disabled={!editable}
                  placeholder="환자 사진과 증상, AI 결과를 종합해 소견을 작성하세요."
                  onChange={(event) =>
                    setOpinion(event.target.value)
                  }
                />
              </label>

              {/* 내원 안내 */}
              <div className="doctor-field">
                <span>
                  대면 진료 및 내원 안내
                </span>

                <label className="doctor-visit-check">
                  <input
                    type="checkbox"
                    checked={visitRequired}
                    disabled={!editable}
                    onChange={(event) =>
                      setVisitRequired(
                        event.target.checked
                      )
                    }
                  />
                  대면 진료 권장
                </label>

                <textarea
                  rows={2}
                  value={visitMessage}
                  disabled={!editable}
                  placeholder="환자에게 안내할 내원 관련 내용을 입력하세요."
                  onChange={(event) =>
                    setVisitMessage(event.target.value)
                  }
                />
              </div>
            </div>

            {/* 저장 오류 */}
            {saveError && (
              <p className="doctor-error" role="alert">
                {saveError}
              </p>
            )}

            {/* 저장 버튼 */}
            <div className="doctor-final-footer">
              <p>
                현재는 같은 브라우저에 저장하는
                교육용 시연 기능입니다.
              </p>

              <div>
                <button
                  type="button"
                  className="doctor-save-button"
                  disabled={!editable || saving}
                  onClick={() => void save(false)}
                >
                  임시 저장
                </button>

                <button
                  type="button"
                  className="doctor-confirm-button"
                  disabled={
                    !editable ||
                    !valid ||
                    saving
                  }
                  onClick={() =>
                    setShowConfirm(true)
                  }
                >
                  최종 결과 확정
                </button>
              </div>
            </div>
          </>
        )}
      </section>

      {/* 최종 결과 확정 확인창 */}
      {showConfirm && patient && (
        <div className="doctor-modal-overlay">
          <div
            className="doctor-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="doctor-confirm-title"
          >
            <h2 id="doctor-confirm-title">
              모의 결과 확정
            </h2>

            <p>
              {patient.patientName} 환자의
              최종 결과를 확정하시겠습니까?
              확정 후에는 수정할 수 없습니다.
            </p>

            <div>
              <button
                type="button"
                onClick={() =>
                  setShowConfirm(false)
                }
              >
                취소
              </button>

              <button
                type="button"
                className="doctor-confirm-button"
                disabled={saving}
                onClick={() => void save(true)}
              >
                확정
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
