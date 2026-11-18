/** 의사 전용 헤더: 기존 doctor-mode 외형 유지. */
import { NavLink } from "react-router-dom";

export default function MainHeader() {
  return (
    <header className="main-header doctor-mode">
      <NavLink to="/doctor" className="header-brand">
        <img src="/main_logo.png" alt="피부진단 AI 로고" className="header-logo" />
        <span className="header-title">피부진단 AI</span>
      </NavLink>
      <nav className="header-nav" aria-label="의사 서비스">
        <NavLink to="/doctor" className="header-button active">
          의사 UI
        </NavLink>
      </nav>
    </header>
  );
}
