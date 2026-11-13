/** 환자 전용 헤더: 기존 patient-mode 외형 유지. */
import { NavLink } from "react-router-dom";

export default function MainHeader() {
  return (
    <header className="main-header patient-mode">
      <nav className="header-nav" aria-label="환자 서비스">
        <NavLink to="/patient" className="header-button active">
          환자 UI
        </NavLink>
      </nav>
    </header>
  );
}
