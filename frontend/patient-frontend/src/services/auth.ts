/**
 * 환자 로그인: 아이디는 전화번호, 비밀번호는 이름.
 * 서버 연결(VITE_SKINAI_API=true)이면 서버에서 확인하고, 데모 모드면 이 브라우저 탭에만 기억합니다.
 * 로그인 정보는 탭을 닫으면 사라지는 sessionStorage에 둡니다.
 */
const apiEnabled = import.meta.env.VITE_SKINAI_API === "true";
const SESSION_KEY = "skinai-patient-session";

export interface PatientSession {
  token: string;   // 서버가 준 로그인 토큰 (데모 모드는 빈 값)
  name: string;
  phone: string;
}

export function normalizePhone(value: string): string {
  return value.replace(/[\s-]/g, "");
}

export function currentPatient(): PatientSession | null {
  try {
    const saved = sessionStorage.getItem(SESSION_KEY);
    return saved ? (JSON.parse(saved) as PatientSession) : null;
  } catch {
    return null;
  }
}

/** 로그인한 환자의 Authorization 헤더 (없으면 빈 객체) */
export function patientAuthHeader(): Record<string, string> {
  const session = currentPatient();
  return session?.token ? { Authorization: `Bearer ${session.token}` } : {};
}

/**
 * @param create true = 첫 화면 '시작하기'(처음이면 계정 생성), false = '내 예약 확인'
 */
export async function patientLogin(phone: string, name: string, create: boolean): Promise<PatientSession> {
  const cleanPhone = normalizePhone(phone);
  const cleanName = name.trim();
  if (!/^0\d{8,10}$/.test(cleanPhone)) throw new Error("전화번호를 숫자로 정확히 입력해 주세요.");
  if (!cleanName) throw new Error("이름을 입력해 주세요.");

  let session: PatientSession = { token: "", name: cleanName, phone: cleanPhone };
  if (apiEnabled) {
    const response = await fetch("/api/auth/patient", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: cleanPhone, name: cleanName, create }),
      cache: "no-store",
    });
    if (response.status === 401) throw new Error("전화번호 또는 이름이 맞지 않아요.");
    if (response.status === 429) throw new Error("로그인 시도가 너무 많아요. 5분 뒤에 다시 시도해 주세요.");
    if (response.status === 422) throw new Error("전화번호와 이름을 확인해 주세요.");
    if (!response.ok) throw new Error(`서버 요청에 실패했습니다 (${response.status}).`);
    const body = await response.json() as { accessToken: string; name: string; loginId: string };
    session = { token: body.accessToken, name: body.name, phone: body.loginId };
  }
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  return session;
}

export async function patientLogout(): Promise<void> {
  const session = currentPatient();
  sessionStorage.removeItem(SESSION_KEY);
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith("skinai-case-token:") || key.startsWith("skinai-case-booking:")) sessionStorage.removeItem(key);
  }
  if (apiEnabled && session?.token) {
    await fetch("/api/auth/logout", {
      method: "POST", headers: { Authorization: `Bearer ${session.token}` },
    }).catch(() => undefined);
  }
}
