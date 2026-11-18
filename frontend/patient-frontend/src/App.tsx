/** 환자 전용 앱: 의사 페이지는 이 프로젝트에 포함하지 않습니다. */
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import MainHeader from "./components/MainHeader";
import PatientLogin from "./pages/patient_mobile/PatientLogin";
import PatientHome from "./pages/patient_mobile/PatientHome";
import DoctorReservation from "./pages/patient_mobile/DoctorReservation";
import ImageUpload from "./pages/patient_mobile/ImageUpload";
import PatientInfo from "./pages/patient_mobile/PatientInfo";
import PatientResult from "./pages/patient_mobile/PatientResult";
import { currentPatient } from "./services/auth";
import "./App.css";

// 로그인하지 않았으면 첫 화면(전화번호·이름)으로 보냅니다.
function RequireLogin({ children }: { children: ReactNode }) {
  return currentPatient() ? children : <Navigate to="/patient/login" replace />;
}

export default function App() {
  return (
    <div className="app-container">
      <MainHeader />
      <Routes>
        <Route path="/" element={<Navigate to="/patient" replace />} />
        <Route path="/patient/login" element={<PatientLogin />} />
        <Route path="/patient" element={<RequireLogin><PatientHome /></RequireLogin>} />
        <Route path="/patient/reservation" element={<RequireLogin><DoctorReservation /></RequireLogin>} />
        <Route path="/patient/upload" element={<RequireLogin><ImageUpload /></RequireLogin>} />
        <Route path="/patient/info" element={<RequireLogin><PatientInfo /></RequireLogin>} />
        <Route path="/patient/result" element={<RequireLogin><PatientResult /></RequireLogin>} />
        <Route path="/patient/my" element={<RequireLogin><Navigate to="/patient/result" replace /></RequireLogin>}/>
        <Route path="*" element={<Navigate to="/patient" replace />} />
      </Routes>
    </div>
  );
}
