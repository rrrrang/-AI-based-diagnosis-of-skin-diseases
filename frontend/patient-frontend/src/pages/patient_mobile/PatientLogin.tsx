/* 환자 첫 화면: 전화번호(아이디) + 이름(비밀번호)
 *
 * - 시작하기: 처음 온 환자는 계정을 만들고 바로 접수 흐름으로 이동
 * - 내 예약 확인: 이미 접수한 환자가 같은 값으로 로그인해 예약 현황 확인
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, CalendarCheck } from "lucide-react";

import { patientLogin } from "../../services/auth";
import "../../css/Patient.css";
import "../../css/Login.css";

function PatientLogin() {
  const navigate = useNavigate();
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const login = async (create: boolean) => {
    if (busy) return;
    setBusy(true);
    setErrorMessage("");
    try {
      await patientLogin(phone, name, create);
      navigate(create ? "/patient" : "/patient/my", { replace: true });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "로그인하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void login(true);
  };

  return (
    <div className="patient-home">
      <div className="patient-home-logo">
        <div className="patient-logo-symbol">
          <img src="/main_logo.png" alt="피부진단 AI 로고" className="patient-logo" />
        </div>
        <h1>피부진단 AI</h1>
        <p>
          AI 기반 안면부 피부질환 분석
          <br />
          진단 보조 플랫폼
        </p>
      </div>

      <form className="login-form" onSubmit={handleSubmit}>
        <h2 className="login-title">전화번호와 이름으로 시작해요</h2>

        <label className="login-label" htmlFor="patient-phone">전화번호</label>
        <input
          id="patient-phone"
          className="info-input"
          type="tel"
          inputMode="numeric"
          autoComplete="tel"
          placeholder="01012345678"
          maxLength={13}
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
        />

        <label className="login-label" htmlFor="patient-name">이름</label>
        <input
          id="patient-name"
          className="info-input"
          type="text"
          autoComplete="name"
          placeholder="이름을 입력해 주세요."
          maxLength={20}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />

        {errorMessage && <p className="info-error" role="alert">{errorMessage}</p>}

        <button type="submit" className="patient-start-button" disabled={busy}>
          시작하기
          <ArrowRight size={24} />
        </button>

        <button
          type="button"
          className="login-secondary-button"
          disabled={busy}
          onClick={() => void login(false)}
        >
          <CalendarCheck size={20} />
          내 예약 확인
        </button>

        <p className="login-help">
          다음에 예약을 확인할 때도 같은 전화번호와 이름을 넣어 주세요.
        </p>
      </form>

      <footer className="patient-home-footer">
        <p>교육용 시뮬레이션</p>
        <p>실제 의료 진단 · 치료가 아닙니다.</p>
      </footer>
    </div>
  );
}

export default PatientLogin;
