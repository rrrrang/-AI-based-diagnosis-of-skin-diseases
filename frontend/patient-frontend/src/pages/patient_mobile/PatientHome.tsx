/* 환자 모바일 앱 시작 화면

 * 주요 기능
 * 1. 서비스 로고 및 프로젝트 이름 표시
 * 2. AI 피부 분석 서비스 소개
 * 3. 분석 시작 버튼
 * 4. 서비스 이용 단계 안내
*/
import { useNavigate } from "react-router-dom";
import{
    Camera, // 카메라 아이콘 (이미지 촬영 및 업로드)
    CalendarDays, // 문서 아이콘 (진단 결과 및 보고서)
    ChartNoAxesColumnIncreasing, // 막대그래프 아이콘 (AI 분석 결과 및 통계)
    ArrowRight, // 오른쪽 화살표 아이콘 (다음 단계 이동)
} from "lucide-react";

// 환자 UI 전용 CSS
import "../../css/Patient.css";

// 환자 시작 화면
function PatientHome() {
  // 다른 페이지로 이동할 때 사용하는 함수
  const navigate = useNavigate();

  return (
    <div className="patient-home">

      {/* 1. 서비스 로고 및 제목 */}
      <div className="patient-home-logo">
        <div className="patient-logo-symbol">
            <img src="/main_logo.png" alt="피부진단 AI 로고" className="patient-logo"/>
        </div>
        <h1>피부진단 AI</h1>
        <p>
          AI 기반 안면부 피부질환 분석
          <br />
          진단 보조 플랫폼
        </p>
      </div>

      {/* 2. 서비스 소개 */}
      <p className="patient-home-description">
        사진과 증상으로 피부 상태를 확인해 보세요.
      </p>

      {/* 3. AI 피부 분석 시작 버튼 */}
      <button type="button" className="patient-start-button" onClick={() => navigate("/patient/reservation")}>
        AI 피부 분석 시작
        <ArrowRight size={24} />
      </button>

      {/* 4. 빠른 기능 메뉴 */}
      <div className="patient-quick-menu">

      <button type="button" className="patient-quick-item" onClick={() => navigate("/patient/reservation")}>
        <CalendarDays size={32} />
        <span>예약 하기</span>
      </button>

        {/* 사진 등록 */}
        <button type="button" className="patient-quick-item" onClick={() => navigate("/patient/upload")}>
          <Camera size={32} />
          <span>사진 등록</span>
        </button>

        {/* 결과 확인 */}
        <button type="button" className="patient-quick-item" onClick={() => navigate("/patient/result")}>
          <ChartNoAxesColumnIncreasing size={32} />
          <span>결과 확인</span>
        </button>

      </div>

      {/* 5. 하단 안내 문구 */}
      <footer className="patient-home-footer">
        <p>교육용 시뮬레이션</p>
        <p>실제 의료 진단 · 치료가 아닙니다.</p>
      </footer>

    </div>
  );
}

export default PatientHome;