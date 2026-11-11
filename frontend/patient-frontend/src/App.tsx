/** 환자 전용 앱: 의사 페이지는 이 프로젝트에 포함하지 않습니다. */
import { Navigate, Route, Routes } from "react-router-dom";
import MainHeader from "./components/MainHeader";
import PatientHome from "./pages/patient_mobile/PatientHome";
import DoctorReservation from "./pages/patient_mobile/DoctorReservation";
import ImageUpload from "./pages/patient_mobile/ImageUpload";
import PatientInfo from "./pages/patient_mobile/PatientInfo";
import PatientResult from "./pages/patient_mobile/PatientResult";
import "./App.css";

export default function App() {
  return (
    <div className="app-container">
      <MainHeader />
      <Routes>
        <Route path="/" element={<Navigate to="/patient" replace />} />
        <Route path="/patient" element={<PatientHome />} />
        <Route path="/patient/reservation" element={<DoctorReservation />} />
        <Route path="/patient/upload" element={<ImageUpload />} />
        <Route path="/patient/info" element={<PatientInfo />} />
        <Route path="/patient/result" element={<PatientResult />} />
        <Route path="*" element={<Navigate to="/patient" replace />} />
      </Routes>
    </div>
  );
}
