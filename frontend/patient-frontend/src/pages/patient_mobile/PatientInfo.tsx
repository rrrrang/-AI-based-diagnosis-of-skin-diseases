
/* 환자 기본 정보 및 상세 증상 입력
 *
 * 주요 기능
 * 1. 이전 단계에서 등록한 사진과 증상 정보 확인
 * 2. 환자 이름, 나이, 성별 입력
 * 3. 상세 증상 작성 (최대 500자)
 * 4. 모의 서비스 안내 및 정보 이용 동의
 * 5. 입력값 검증 및 모의 분석 요청
*/

import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

// 기존 예약 정보 확인 및 의사 접수 저장소 연결
import { apiEnabled, requestAnalysis, submitCase } from "../../services/api";
import { demoFlow } from "../../services/demoFlow";
import {
  createPatientCase,
  saveDoctorCase,
  rememberPatientCaseId,
} from "../../services/doctorCases";

// 화면에서 사용할 아이콘
import {
  ArrowLeft,          // 이전 화면 이동
  Image as ImageIcon, // 등록 이미지 정보 표시
} from "lucide-react";

// 기존 환자 UI 전용 CSS
import "../../css/Patient.css";

/* ==========================================
   데이터 타입 정의
========================================== */

// 성별 선택에 사용할 타입
type Gender = "female" | "male" | "none";

// 이전 이미지 업로드 페이지에서 전달받는 데이터
interface UploadData {
  imageFile: File;
  imageFiles?: (File | null)[];
  symptoms: string[];
  duration: string;
}

/* ==========================================
   환자 정보 입력 컴포넌트
========================================== */

function PatientInfo() {
  const navigate = useNavigate();                             // 페이지 이동 기능
  const location = useLocation();                             // 이전 페이지에서 전달한 데이터 확인
  const uploadData = location.state as UploadData | null;     // 전달받은 사진 및 증상 정보
  const [name, setName] = useState("");                       // 환자 이름
  const [age, setAge] = useState("");                         // 환자 나이
  const [gender, setGender] = useState<Gender | null>(null);  // 선택한 성별
  const [description, setDescription] = useState("");         // 환자가 직접 작성한 상세 증상
  const [agreed, setAgreed] = useState(false);                // 모의 서비스 정보 이용 동의 여부
  const [errorMessage, setErrorMessage] = useState("");       // 입력 오류 메시지
  const [submitting, setSubmitting] = useState(false);        // 중복 접수 방지

  /* ==========================================
    이전 화면으로 돌아가기
  ========================================== */

  const handlePrevious = () => {
    // 이미지 업로드 화면으로 이동
    // 이전 입력 데이터도 함께 전달
    navigate("/patient/upload", {
      state: uploadData,
    });
  };

  /* ==========================================
    성별 선택
  ========================================== */

  const handleGenderSelect = (value: Gender) => {
    setGender(value);      // 선택한 성별 저장
    setErrorMessage("");   // 이전 오류 안내 초기화
  };

  /* ==========================================
    AI 분석 요청 입력값 검증
  ========================================== */

  const handleSubmit = async () => {
    // 저장 중에는 같은 환자의 접수 버튼을 다시 처리하지 않음
    if (submitting) return;
    // 이미지 업로드 데이터가 없는 경우
    if (!uploadData?.imageFile) {
      setErrorMessage("피부 사진을 먼저 등록해 주세요.");
      return;
    }
    // 이름 미입력 확인
    if (!name.trim()) {
      setErrorMessage("이름을 입력해 주세요.");
      return;
    }
    // 나이 입력 범위 확인
    const parsedAge = Number(age);
    if (
      !/^\d+$/.test(age) ||
      parsedAge < 1 ||
      parsedAge > 120
    ) {
      setErrorMessage("나이를 1~120 사이의 숫자로 입력해 주세요.");
      return;
    }
    // 성별 선택 여부 확인
    if (gender === null) {
      setErrorMessage("성별을 선택해 주세요.");
      return;
    }
    // 상세 증상 입력 여부 확인
    if (!description.trim()) {
      setErrorMessage("상세 증상을 작성해 주세요.");
      return;
    }
    // 모의 서비스 안내 동의 확인
    if (!agreed) {
      setErrorMessage("모의 서비스 안내 및 정보 이용에 동의해 주세요.");
      return;
    }
    // 최종 입력 데이터 구성
    const requestData = {
      imageFile: uploadData.imageFile,
      imageFiles: uploadData.imageFiles ?? [uploadData.imageFile],
      symptoms: uploadData.symptoms,
      duration: uploadData.duration,
      patient: {
        name: name.trim(),
        age: parsedAge,
        gender,
        description: description.trim(),
      },
    };

    // 예약 없이 사진·문진만 제출할 수 없도록 확인
    if (!demoFlow.booking) {
      setErrorMessage("의사 예약 정보가 없습니다. 먼저 예약해 주세요.");
      return;
    }

    // 이미지·문진·예약을 접수 건으로 저장한 다음 결과 화면 이동
    setSubmitting(true);
    setErrorMessage("");

    try {
      const item = createPatientCase({
        booking: demoFlow.booking,
        patient: requestData.patient,
        symptoms: requestData.symptoms,
        duration: requestData.duration,
        photos: requestData.imageFiles,
      });

      const caseId = apiEnabled ? await submitCase(item) : item.id;
      if (!apiEnabled) await saveDoctorCase(item);
      let analysisError = "";
      if (apiEnabled) {
        try {
          await requestAnalysis(caseId);
        } catch (error) {
          analysisError = error instanceof Error ? error.message : "분석을 요청하지 못했습니다.";
        }
      }
      
      // 제출한 접수번호를 환자 진료 기록에 누적
      rememberPatientCaseId(caseId);

      navigate("/patient/result", {
        state: {
          requestData,
          caseId,
          analysisError,
        },
      });
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "환자 접수 저장에 실패했습니다. 다시 시도해 주세요."
      );
    } finally {
      setSubmitting(false);
    }
  };

  /* ==========================================
    화면 렌더링
  ========================================== */

  return (
    <main className="patient-info-page">
      <section className="patient-info-card">

        {/* 상단 뒤로 가기 및 진행 단계 */}
        <div className="info-top">
          <button
            type="button"
            className="info-back-button"
            onClick={handlePrevious}
            aria-label="사진·증상 입력 화면으로 돌아가기"
          >
            <ArrowLeft size={24} />
          </button>

          {/* 2단계 진행 표시 */}
          <div className="info-progress">
            <div className="info-progress-step">
              <span className="info-progress-dot" />
              <span>사진·증상</span>
            </div>

            <div className="info-progress-step active">
              <span className="info-progress-dot" />
              <span>환자 정보</span>
            </div>
          </div>

          <span className="info-step-count">2 / 2</span>
        </div>

        {/* 페이지 제목 */}
        <h1 className="info-title">환자 정보 입력</h1>

        {/* ==================================
            환자 기본 정보 입력
        ================================== */}

        <div className="info-basic-section">
          <h2>기본 정보</h2>

          {/* 환자 이름 입력 */}
          <input
            type="text"
            className="info-input"
            placeholder="이름을 입력해 주세요."
            aria-label="환자 이름"
            autoComplete="off"
            maxLength={30}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />

          {/* 환자 나이 입력 */}
          <input
            type="number"
            className="info-input"
            placeholder="나이를 입력해 주세요."
            aria-label="환자 나이"
            min={1}
            max={120}
            value={age}
            onChange={(event) => setAge(event.target.value)}
          />

          {/* 성별 선택 버튼 3개 */}
          <div className="info-gender-grid">
            <button
              type="button"
              className={`info-gender-button ${
                gender === "female" ? "selected" : ""
              }`}
              aria-pressed={gender === "female"}
              onClick={() => handleGenderSelect("female")}
            >
              여성
            </button>

            <button
              type="button"
              className={`info-gender-button ${
                gender === "male" ? "selected" : ""
              }`}
              aria-pressed={gender === "male"}
              onClick={() => handleGenderSelect("male")}
            >
              남성
            </button>

            <button
              type="button"
              className={`info-gender-button ${
                gender === "none" ? "selected" : ""
              }`}
              aria-pressed={gender === "none"}
              onClick={() => handleGenderSelect("none")}
            >
              선택 안 함
            </button>
          </div>
        </div>

        {/* ==================================
            상세 증상 작성
        ================================== */}

        <div className="info-description-section">
          <h2>상세 증상</h2>

          <p>
            가상 의사에게 전달할 내용을 적어주세요.
          </p>

          {/* 최대 500자 입력 */}
          <textarea
            className="info-textarea"
            placeholder={
              "증상이 나타난 부위, 시작 시점, 불편한 점을 적어주세요."
            }
            maxLength={500}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />

          {/* 실시간 글자 수 표시 */}
          <div className="info-character-count">
            {description.length} / 500
          </div>
        </div>

        {/* ==================================
            이전 단계 입력 정보 요약
        ================================== */}

        <div className="info-upload-summary">
          <ImageIcon size={22} />

          <span>
            등록 사진 {uploadData?.imageFiles?.filter(Boolean).length ?? (uploadData?.imageFile ? 1 : 0)}장
            {" · "}
            선택 증상 {uploadData?.symptoms?.length ?? 0}개
          </span>
        </div>

        {/* ==================================
            서비스 안내 및 동의
        ================================== */}

        <label className="info-agreement">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(event) => setAgreed(event.target.checked)}
          />

          <span>
            모의 서비스 안내 및 정보 이용 동의
            <small>
              입력 정보는 교육용 모의 분석에 사용됩니다.
              실제 의료 진단은 제공되지 않습니다.
            </small>
          </span>
        </label>

        {/* 입력 오류 표시 */}
        {errorMessage && (
          <p className="info-error" role="alert">
            {errorMessage}
          </p>
        )}

        {/* ==================================
            하단 이전 / 분석 요청 버튼
        ================================== */}

        <div className="info-action-buttons">
          <button
            type="button"
            className="info-previous-button"
            onClick={handlePrevious}
          >
            이전
          </button>

          <button
            type="button"
            className="info-submit-button"
            disabled={submitting}
            onClick={() => void handleSubmit()}
          >
            {submitting ? "접수 저장 중..." : "AI 분석 요청"}
          </button>
        </div>
      </section>
    </main>
  );
}

export default PatientInfo;
