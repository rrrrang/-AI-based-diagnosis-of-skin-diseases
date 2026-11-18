import type { DoctorCase } from "../types/doctorCase";

export const apiEnabled = import.meta.env.VITE_SKINAI_API === "true";
// 의사 로그인 정보: 탭을 닫으면 사라지는 sessionStorage에 둡니다.
const doctorTokenKey = "skinai-doctor-session-token";
const doctorNameKey = "skinai-doctor-session-name";

export function doctorLoggedIn(): boolean {
  return Boolean(sessionStorage.getItem(doctorTokenKey));
}

export function doctorDisplayName(): string {
  return sessionStorage.getItem(doctorNameKey) ?? "";
}

/** 의사 아이디·비밀번호 로그인 */
export async function doctorLogin(loginId: string, password: string): Promise<void> {
  if (!loginId.trim() || !password) throw new Error("아이디와 비밀번호를 입력해 주세요.");
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ loginId: loginId.trim(), password }),
    cache: "no-store",
  });
  if (response.status === 401) throw new Error("아이디 또는 비밀번호가 맞지 않아요.");
  if (response.status === 429) throw new Error("로그인 시도가 너무 많아요. 5분 뒤에 다시 시도해 주세요.");
  if (!response.ok) throw new Error(`로그인 요청 실패 (${response.status})`);
  const body = await response.json() as { accessToken: string; name: string; role: string };
  if (body.role !== "doctor") {
    await fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${body.accessToken}` } });
    throw new Error("의사 계정으로 로그인해 주세요.");
  }
  sessionStorage.setItem(doctorTokenKey, body.accessToken);
  sessionStorage.setItem(doctorNameKey, body.name);
}

export async function doctorLogout(): Promise<void> {
  const token = sessionStorage.getItem(doctorTokenKey);
  sessionStorage.removeItem(doctorTokenKey);
  sessionStorage.removeItem(doctorNameKey);
  if (token) {
    await fetch("/api/auth/logout", {
      method: "POST", headers: { Authorization: `Bearer ${token}` },
    }).catch(() => undefined);
  }
}

type Detail = Pick<DoctorCase, "id" | "doctorId" | "date" | "time" | "patientName" |
  "age" | "gender" | "symptoms" | "duration" | "description" | "aiState" |
  "reviewState" | "submittedAt" | "analysis"> &
  Partial<Pick<DoctorCase, "diagnosis" | "opinion" | "visitRequired" | "visitMessage">> &
  { photoIndices: number[] };

async function request(path: string, options?: RequestInit) {
  const token = sessionStorage.getItem(doctorTokenKey);
  if (!token) throw new Error("의사 아이디와 비밀번호로 로그인해 주세요.");
  const headers = new Headers(options?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  if (response.status === 401) {
    sessionStorage.removeItem(doctorTokenKey);
    throw new Error("로그인이 끝났어요. 다시 로그인해 주세요.");
  }
  if (!response.ok) throw new Error(`의사 API 요청 실패 (${response.status})`);
  return response;
}

export async function listAssignedCases(): Promise<DoctorCase[]> {
  if (!sessionStorage.getItem(doctorTokenKey)) return [];
  const response = await request("/api/cases");
  const details: Detail[] = await response.json();
  return details.map((detail) => ({
    doctorName: "", doctorHospital: "",
    photos: [null, null, null], predictions: [], analysisPhoto: null, maskPhoto: null,
    diagnosis: "", opinion: "", visitRequired: false, visitMessage: "",
    updatedAt: detail.submittedAt, ...detail,
  }));
}

export async function readCasePhotos(item: DoctorCase): Promise<DoctorCase> {
  const photos = await Promise.all([0, 1, 2].map(async (index) => {
    if (!item.photoIndices?.includes(index)) return null;
    const response = await request(`/api/cases/${encodeURIComponent(item.id)}/photos/${index}`);
    const blob = await response.blob();
    return new File([blob], `photo${index}`, { type: blob.type });
  }));
  return { ...item, photos, analysisPhoto: photos[item.analysis?.analyzedPhotoIndex ?? -1] ?? null };
}

export async function saveReview(item: DoctorCase) {
  const { diagnosis, opinion, visitRequired, visitMessage, reviewState } = item;
  await request(`/api/cases/${encodeURIComponent(item.id)}/review`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ diagnosis, opinion, visitRequired, visitMessage, reviewState }),
  });
}
