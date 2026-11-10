
/* 환자 UI / 의사 UI 공통 헤더
 * 기능:
 * - 프로젝트 로고 표시
 * - 피부진단 AI 브랜드명 표시
 * - 환자 UI와 의사 UI 전환
*/

// *react-router-dom*: React에서 페이지 이동과 URL 경로를 관리하는 라이브러리
// 웹사이트에서 메뉴를 클릭했을 때 해당 페이지로 이동하도록 만들어주는 기능
import { NavLink, useLocation } from "react-router-dom";

function MainHeader() {
  
  const location = useLocation();                             // 현재 접속 중인 페이지 주소 확인
  const isPatient = location.pathname.startsWith("/patient"); // 환자 하위 페이지 환자 버튼 활성화
  const isDoctor = location.pathname.startsWith("/doctor");   // 의사 하위 페이지 의사 버튼 활성화

  return (
    <header
      className={
        isPatient
          ? "main-header patient-mode"
          : "main-header doctor-mode"
      }
    >
      {/* 의사 UI에서만 로고와 브랜드명 표시 */}
      {isDoctor && (
        <NavLink to="/doctor" className="header-brand">
          <img
            src="/main_logo.png"
            alt="피부진단 AI 로고"
            className="header-logo"
          />
          <span className="header-title">
            피부진단 AI
          </span>
        </NavLink>
      )}
  
      {/* 환자·의사 UI 전환 버튼은 모두 표시 */}
      <nav className="header-nav" aria-label="UI 선택">
        <NavLink
          to="/patient"
          className={
            isPatient
              ? "header-button active"
              : "header-button"
          }
        >
          환자 UI
        </NavLink>
  
        <NavLink
          to="/doctor"
          className={
            isDoctor
              ? "header-button active"
              : "header-button"
          }
        >
          의사 UI
        </NavLink>
      </nav>
    </header>
  );
}

export default MainHeader;