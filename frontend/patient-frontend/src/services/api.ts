import type { DoctorCase } from "../types/doctorCase";

export const apiEnabled = import.meta.env.VITE_SKINAI_API === "true";
const tokenKey = (id: string) => `skinai-case-token:${id}`;
const bookingKey = (id: string) => `skinai-case-booking:${id}`;

async function request(path: string, options?: RequestInit): Promise<Response> {
  const response = await fetch(path, { ...options, cache: "no-store" });
  if (!response.ok) {
    if (response.status === 503) throw new Error("분석 워커를 준비 중입니다. 잠시 후 다시 요청해 주세요.");
    if (response.status === 422) throw new Error("접수 정보와 부위 사진을 확인해 주세요.");
    throw new Error(`서버 요청에 실패했습니다 (${response.status}).`);
  }
  return response;
}

export async function submitCase(item: DoctorCase): Promise<string> {
  const body = new FormData();
  for (const key of ["doctorId", "date", "time", "patientName", "age", "gender", "duration", "description"] as const) {
    body.append(key, String(item[key]));
  }
  item.symptoms.forEach((symptom) => body.append("symptoms", symptom));
  item.photos.forEach((file, index) => { if (file) body.append(`photo${index}`, file); });
  const response = await request("/api/cases", { method: "POST", body });
  const { id, accessToken } = await response.json() as { id: string; accessToken: string };
  sessionStorage.setItem(tokenKey(id), accessToken);
  sessionStorage.setItem(bookingKey(id), JSON.stringify({
    doctorName: item.doctorName, doctorHospital: item.doctorHospital,
  }));
  return id;
}

export async function requestAnalysis(id: string, retry = false) {
  const token = sessionStorage.getItem(tokenKey(id));
  if (!token) throw new Error("이 접수의 접근 토큰이 없습니다.");
  await request(`/api/cases/${encodeURIComponent(id)}/analyze${retry ? "?retry=true" : ""}`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` },
  });
}

export async function readCase(id: string): Promise<DoctorCase | null> {
  const token = sessionStorage.getItem(tokenKey(id));
  if (!token) return null;
  const response = await request(`/api/cases/${encodeURIComponent(id)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const detail = await response.json() as Omit<DoctorCase, "doctorName" | "doctorHospital" | "photos" | "predictions" | "analysisPhoto" | "maskPhoto" | "diagnosis" | "opinion" | "visitRequired" | "visitMessage" | "updatedAt"> & Partial<Pick<DoctorCase, "diagnosis" | "opinion" | "visitRequired" | "visitMessage">>;
  return {
    doctorName: "", doctorHospital: "",
    ...JSON.parse(sessionStorage.getItem(bookingKey(id)) ?? "{}"),
    photos: [null, null, null], predictions: [], analysisPhoto: null, maskPhoto: null,
    diagnosis: "", opinion: "", visitRequired: false, visitMessage: "",
    updatedAt: detail.submittedAt, ...detail,
  };
}

export function forgetCase(id: string) {
  sessionStorage.removeItem(tokenKey(id));
  sessionStorage.removeItem(bookingKey(id));
}
