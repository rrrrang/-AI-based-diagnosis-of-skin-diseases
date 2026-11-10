
/* 환자 AI 이미지 분석 진행 상태 및 결과 확인
 *
 * 주요 기능
 * 1. 이전 단계에서 전달한 환자 정보 확인
 * 2. AI 이미지 분석 진행 상태 표시
 * 3. 가상 의사 검토 진행 상태 표시
 * 4. 분석 모델 및 백엔드 미연결 안내
 * 5. 환자 시작 화면으로 이동
 *
 * 주의:
 * 현재 AI 모델과 백엔드는 연결되지 않았으므로
 * 실제 분석 완료나 진단 결과를 표시하지 않음
*/
import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

// 의사 최종 검토 결과 조회
import type { DoctorCase } from "../../types/doctorCase";
import {
  listDoctorCases,
  listPatientCaseIds,
  rememberPatientCaseId,
  subscribeDoctorCases,
} from "../../services/doctorCases";

// 화면 아이콘
import {
  ArrowLeft,       // 이전 화면으로 이동
  ClipboardList,   // 분석 요청 진행 상태
  CheckCircle2,    // 완료된 단계 표시
  Circle,          // 대기 중인 단계 표시
  Info,            // 분석 관련 안내
  Home,            // 환자 홈으로 이동
  Image as ImageIcon, // 등록한 이미지 표시
} from "lucide-react";

// 기존 환자 모바일 UI CSS
import "../../css/Patient.css";

/* ==========================================
   분석 진행 상태 타입
========================================== */

// 추후 FastAPI에서 전달받을 분석 상태
type AnalysisStatus =
  | "pending"      // 요청 준비 / 서버 처리 대기
  | "analyzing"    // AI 이미지 분석 중
  | "review"       // 가상 의사 검토 대기
  | "complete"     // 모의 검토 결과 완료
  | "failed";      // 분석 실패

// 환자 성별 데이터 타입
type Gender = "female" | "male" | "none";

// 이전 화면에서 전달한 환자 정보
interface PatientData {
  name: string;
  age: number;
  gender: Gender;
  description: string;
}

// 환자 정보 및 피부 이미지 입력 데이터
interface AnalysisRequestData {
  imageFile: File;
  imageFiles?: (File | null)[];
  symptoms: string[];
  duration: string;
  patient: PatientData;
}

// React Router로 전달받는 페이지 상태
interface ResultPageState {
  requestData: AnalysisRequestData;
  caseId?: string;
}

/* ==========================================
   진행 단계 정의
========================================== */

// 분석 요청 이후 표시할 진행 단계
const progressSteps = [
  {
    id: "input",
    title: "피부 사진 및 증상 입력",
  },
  {
    id: "analysis",
    title: "AI 피부 이미지 분석",
  },
  {
    id: "review",
    title: "가상 의사 검토",
  },
  {
    id: "result",
    title: "모의 결과 확인",
  },
] as const;

/* ==========================================
   3. 환자 분석 결과 화면
========================================== */

function PatientResult() {
  const navigate = useNavigate();              // 페이지 이동 기능
  const location = useLocation();              // 이전 화면에서 전달한 데이터 조회
  const pageState = location.state as ResultPageState | null;
  const routeCaseId = pageState?.caseId;

  // 페이지 이동 state가 있으면 해당 접수 건의 임시 정보에만 사용
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(
    routeCaseId ?? null
  );

  // IndexedDB에 보관된 환자의 이전 접수 건들
  const [history, setHistory] = useState<DoctorCase[]>([]);
  const [loadError, setLoadError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [loaded, setLoaded] = useState(false);

  /* ==========================================
     저장된 접수 목록과 의사 검토 결과 조회

     - 홈의 '결과 확인' 버튼은 state 없이 진입
     - 이 브라우저의 접수 ID 목록을 사용해 이전 기록 복원
     - 담당 의사가 결과를 저장해도 동일 접수번호로 갱신
  ========================================== */

  const refreshResult = useCallback(async () => {
    setRefreshing(true);

    try {
      const savedCases = await listDoctorCases();
      const ownIds = new Set(listPatientCaseIds());

      // 직전에 접수한 결과 화면의 caseId도 함께 확인
      if (routeCaseId) {
        ownIds.add(routeCaseId);
      }

      const ownCases = savedCases
        .filter((item) => ownIds.has(item.id))
        .sort((a, b) => b.submittedAt.localeCompare(a.submittedAt));

      // 이전 버전에서 결과 페이지로 전달된 접수번호도 복원 목록에 등록
      if (routeCaseId && ownCases.some((item) => item.id === routeCaseId)) {
        rememberPatientCaseId(routeCaseId);
      }

      setHistory(ownCases);
      setSelectedCaseId((previous) => {
        if (previous && ownCases.some((item) => item.id === previous)) {
          return previous;
        }

        if (routeCaseId && ownCases.some((item) => item.id === routeCaseId)) {
          return routeCaseId;
        }

        return ownCases[0]?.id ?? null;
      });

      setLoadError("");
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : "접수 및 검토 기록을 불러오지 못했습니다."
      );
    } finally {
      setRefreshing(false);
      setLoaded(true);
    }
  }, [routeCaseId]);

  useEffect(() => {
    void refreshResult();

    return subscribeDoctorCases(() => {
      void refreshResult();
    });
  }, [refreshResult]);

  // 현재 선택한 접수 기록 (화면을 다시 열어도 IndexedDB에서 복원됨)
  const doctorResult = history.find(
    (item) => item.id === selectedCaseId
  ) ?? null;

  // 방금 접수한 건에 한해서만 Router state의 임시 데이터를 사용
  const requestData =
    routeCaseId === selectedCaseId ? pageState?.requestData : undefined;

  // 저장된 진료 기록이 있다면 화면 상태는 그 기록을 기준으로 결정
  const status: AnalysisStatus = doctorResult?.aiState === "실패"
    ? "failed"
    : doctorResult?.reviewState === "결과 전달 완료"
      ? "complete"
      : doctorResult?.aiState === "완료" ||
          doctorResult?.aiState === "시연 결과"
        ? "review"
        : doctorResult?.aiState === "분석 중"
          ? "analyzing"
          : doctorResult || requestData
            ? "pending"
            : "failed";

  /* ==========================================
    상태별 제목 및 설명
  ========================================== */

  // 현재 상태에 맞게 화면 문구 반환
  const getStatusInfo = (currentStatus: AnalysisStatus) => {
    switch (currentStatus) {
      case "analyzing":
        return {
          title: "AI 이미지 분석 중",
          description:
            "업로드된 피부 이미지를 분석하고 있습니다.",
        };

      case "review":
        return {
          title: "가상 의사 검토 대기",
          description:
            "이미지 분석이 완료되어 모의 검토를 기다리고 있습니다.",
        };

      case "complete":
        return {
          title: "모의 검토 완료",
          description:
            "모의 검토 결과가 등록되었습니다.",
        };

      case "failed":
        return {
          title: "분석 처리 실패",
          description:
            "분석 요청을 처리하지 못했습니다.",
        };

      case "pending":
      default:
        return {
          title: "분석 요청 준비 완료",
          description:
            "입력 정보 확인이 완료되었습니다. AI 서버 연결 후 분석을 요청할 수 있습니다.",
        };
    }
  };

  // 현재 상태 안내 내용
  const statusInfo = getStatusInfo(status);

  /* ==========================================
    진행 단계별 표시 상태
  ========================================== */

  const getStepStatus = (index: number) => {
    // 사진 및 증상 입력은 완료 상태
    if (index === 0 && (doctorResult || requestData)) {
      return "done";
    }

    // 분석 실패 또는 요청 데이터 없음
    if (status === "failed" || (!doctorResult && !requestData)) {
      return "waiting";
    }

    // 요청 준비 단계에서는 후속 처리가 없음
    if (status === "pending") {
      return "waiting";
    }

    // AI 분석 진행 상태
    if (status === "analyzing") {
      return index === 1 ? "current" : "waiting";
    }

    // 가상 의사 검토 단계
    if (status === "review") {
      if (index === 1) return "done";
      if (index === 2) return "current";
      return "waiting";
    }

    // 모든 단계 완료
    if (status === "complete") {
      return "done";
    }

    return "waiting";
  };

  /* ==========================================
    화면 이동 함수
  ========================================== */

  // 환자 홈 화면으로 이동
  const handleHome = () => {
    navigate("/patient");
  };

  // 환자 정보 입력 화면으로 이동
  const handleBack = () => {
    // 이전 제출 데이터를 잃은 재방문 기록은 홈으로 이동
    if (!requestData) {
      navigate("/patient");
      return;
    }

    navigate("/patient/info", {
      state: requestData
        ? {
            imageFile: requestData.imageFile,
            imageFiles: requestData.imageFiles,
            symptoms: requestData.symptoms,
            duration: requestData.duration,
          }
        : null,
    });
  };

  /* ==========================================
    결과 화면 렌더링
  ========================================== */

  return (
    <main className="patient-result-page">
      <section className="patient-result-card">

        {/* 상단 뒤로 가기 및 화면 제목 */}
        <header className="result-header">
          <button
            type="button"
            className="result-back-button"
            onClick={handleBack}
            aria-label="환자 정보 화면으로 이동"
          >
            <ArrowLeft size={23} />
          </button>

          <h1>AI 피부 분석 결과</h1>
        </header>

        {/* ==================================
            이전 접수 / 진료 기록 목록
            새로운 접수는 기존 기록을 덮어쓰지 않음
        ================================== */}
        <div className="result-history-section">
          <div className="result-history-heading">
            <h3>내 진료 기록</h3>
            <button
              type="button"
              className="result-history-refresh"
              onClick={() => void refreshResult()}
              disabled={refreshing}
            >
              {refreshing ? "조회 중..." : "기록 새로고침"}
            </button>
          </div>

          {history.length > 0 ? (
            <div className="result-history-list">
              {history.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`result-history-item ${
                    item.id === selectedCaseId ? "is-selected" : ""
                  }`}
                  onClick={() => setSelectedCaseId(item.id)}
                >
                  <span className="result-history-date">
                    {item.date} · {item.time}
                  </span>
                  <strong>{item.doctorName} 의사</strong>
                  <span className="result-history-state">
                    {item.reviewState}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="result-history-empty">
              {!loaded
                ? "진료 기록을 불러오는 중입니다."
                : "이 브라우저에 저장된 접수 기록이 없습니다."}
            </p>
          )}

          {loadError && (
            <p className="result-error" role="alert">{loadError}</p>
          )}
        </div>

        {/* ==================================
            현재 분석 진행 상태
        ================================== */}

        <div className="result-status-section">
          <div className="result-status-icon">
            <ClipboardList size={32} strokeWidth={1.8} />
          </div>

          {/* 현재 상태 제목 */}
          <h2>{!doctorResult && !requestData ? "접수 기록 없음" : statusInfo.title}</h2>

          {/* 현재 상태 설명 */}
          <p>{!doctorResult && !requestData ? "먼저 사진 등록과 문진 제출을 완료해 주세요." : statusInfo.description}</p>
        </div>

        {/* ==================================
            분석 진행 단계
        ================================== */}

        <div className="result-progress-section">
          <h3>진행 상태</h3>

          <div className="result-progress-list">
            {progressSteps.map((step, index) => {
              // 각 단계의 완료 / 진행 / 대기 상태
              const stepState = getStepStatus(index);

              return (
                <div
                  key={step.id}
                  className={`result-progress-item ${stepState}`}
                >
                  {/* 완료된 단계는 체크 아이콘 */}
                  {stepState === "done" ? (
                    <CheckCircle2 size={20} />
                  ) : (
                    <Circle size={20} />
                  )}

                  {/* 진행 단계 정보 */}
                  <div className="result-progress-text">
                    <strong>{step.title}</strong>

                    <span>
                      {stepState === "done"
                        ? "완료"
                        : stepState === "current"
                          ? "진행 중"
                          : "대기"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ==================================
            환자가 등록한 정보 요약
        ================================== */}

        {(doctorResult || requestData) && (
          <div className="result-patient-summary">
            <h3>등록 정보</h3>

            <div className="result-summary-row">
              <span>환자</span>
              <strong>
                {doctorResult?.patientName ?? requestData?.patient.name}
                {" · "}
                {doctorResult?.age ?? requestData?.patient.age}세
              </strong>
            </div>

            <div className="result-summary-row">
              <span>피부 이미지</span>
              <strong className="result-image-count">
                <ImageIcon size={17} />
                {doctorResult
                  ? doctorResult.photos.filter(Boolean).length
                  : requestData?.imageFiles?.filter(Boolean).length ?? 1}
                장
              </strong>
            </div>

            <div className="result-summary-row">
              <span>선택 증상</span>
              <strong>
                {(doctorResult?.symptoms ?? requestData?.symptoms ?? []).join(", ")}
              </strong>
            </div>

            <div className="result-summary-row">
              <span>발생 시점</span>
              <strong>{doctorResult?.duration ?? requestData?.duration}</strong>
            </div>
          </div>
        )}

        {/* ==================================
            저장된 의사 검토 결과 확인
            - 같은 브라우저에서 상태 새로고침 가능
            - 의사 최종 확정 전에는 소견 숨김
        ================================== */}

        {doctorResult && (
          <div className="result-patient-summary">
            <h3>의사 검토 현황</h3>

            <div className="result-summary-row">
              <span>담당 의사</span>
              <strong>{doctorResult?.doctorName ?? "조회 중"}</strong>
            </div>

            <div className="result-summary-row">
              <span>검토 상태</span>
              <strong>{doctorResult?.reviewState ?? "접수 확인 중"}</strong>
            </div>

            <button
              type="button"
              className="result-home-button"
              disabled={refreshing}
              onClick={() => void refreshResult()}
            >
              {refreshing ? "조회 중..." : "검토 상태 새로고침"}
            </button>

            {loadError && (
              <p className="result-error" role="alert">
                {loadError}
              </p>
            )}

            {doctorResult?.reviewState === "결과 전달 완료" && (
              <div className="patient-doctor-result">
                <h3>최종 모의 검토 결과</h3>
                <p>검토 내용: {doctorResult.diagnosis}</p>
                <p>의사 소견: {doctorResult.opinion}</p>

                {doctorResult.visitRequired && (
                  <p>대면 진료 권고: {doctorResult.visitMessage}</p>
                )}
              </div>
            )}
          </div>
        )}

        {/* ==================================
            AI 모델 및 서버 연결 안내
        ================================== */}

        <div className="result-information-box">
          <div className="result-information-box-top">
            <Info size={18} />
            <strong>분석 서버 연결 준비 중</strong>
          </div>
        
          <p>
            현재는 프론트엔드 시연 단계입니다. 실제 AI 이미지 분석이나 의료 진단은 수행되지 않았습니다.
          </p>
          
        </div>

        {/* 요청 정보가 전달되지 않은 경우 */}
        {!doctorResult && !requestData && loaded && (
          <p className="result-error" role="alert">
            조회 가능한 기록이 없습니다. 같은 브라우저에서 접수를 완료했는지 확인해 주세요.
          </p>
        )}

        {/* ==================================
            홈으로 돌아가기
        ================================== */}

        <button
          type="button"
          className="result-home-button"
          onClick={handleHome}
        >
          <Home size={20} />
          홈으로 돌아가기
        </button>

      </section>
    </main>
  );
}

// 다른 파일에서 사용할 수 있도록 내보내기
export default PatientResult;
