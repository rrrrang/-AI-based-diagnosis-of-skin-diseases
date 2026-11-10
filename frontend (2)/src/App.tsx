/*전체 앱 레이아웃과 페이지 전환*/

import {
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import MainHeader from "./components/MainHeader";                         // 공통 헤더 컴포넌트
import PatientHome from "./pages/patient_mobile/PatientHome";             // 환자 모바일 앱 시작 화면
import DoctorReservation from "./pages/patient_mobile/DoctorReservation"; // 가상 의사 선택 및 예약 페이지
import ImageUpload from "./pages/patient_mobile/ImageUpload";             // 환자 피부 사진 및 증상 입력 페이지
import PatientInfo from "./pages/patient_mobile/PatientInfo";             // 환자 정보 입력 화면
import PatientResult from "./pages/patient_mobile/PatientResult";         // 환자 AI 분석 진행 및 결과 화면

import DoctorDashboard from "./pages/doctor_web/DoctorDashboard";         // 의사 PC 웹 대시보드 화면
import "./App.css";                                                       // 앱 공통 CSS


/* 전체 애플리케이션 */
export default function App() {
  // 의사 화면에만 전체 페이지 스크롤과 고정 헤더 적용
  const location = useLocation();
  const isDoctor = location.pathname.startsWith("/doctor");

  return (
    <div className={`app-container ${isDoctor ? "doctor-app" : ""}`}>
      {/* 모든 페이지에 표시되는 공통 헤더 */}
      <MainHeader />

      {/* 현재 URL에 따라 페이지 변경 */}
      <Routes>
        {/* 최초 접속 시 환자 홈 화면으로 이동 */}
        <Route path="/" element={<Navigate to="/patient/" replace />}/>
        {/* 환자 모바일 앱 시작 화면 */}
        <Route path="/patient" element={<PatientHome />}/>
        {/* 의사 선택 및 예약 화면 */}
        <Route path="/patient/reservation" element={<DoctorReservation />}/>
        {/* 환자 이미지 업로드 및 기본 증상 입력 */}
        <Route path="/patient/upload" element={<ImageUpload />}/>
        {/* 환자 정보 입력 화면 */}
        <Route path="/patient/info" element={<PatientInfo/>}/>
        {/* 환자 AI 분석 진행 및 결과 확인 화면 */}
        <Route path="/patient/result" element={<PatientResult />}/>
        {/* 의사 PC 웹 대시보드 */}
        <Route path="/doctor" element={<DoctorDashboard />} />
      </Routes>
    </div>
  );
}
