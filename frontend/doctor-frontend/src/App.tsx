/** 의사 전용 앱: 환자 페이지는 이 프로젝트에 포함하지 않습니다. */
import { Navigate, Route, Routes } from "react-router-dom";
import MainHeader from "./components/MainHeader";
import DoctorDashboard from "./pages/doctor_web/DoctorDashboard";
import "./App.css";

export default function App() {
  return (
    <div className="app-container doctor-app">
      <MainHeader />
      <Routes>
        <Route path="/" element={<Navigate to="/doctor" replace />} />
        <Route path="/doctor" element={<DoctorDashboard />} />
        <Route path="*" element={<Navigate to="/doctor" replace />} />
      </Routes>
    </div>
  );
}
