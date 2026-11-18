import type { DoctorCase } from "../types/doctorCase";
import { patientAuthHeader } from "./auth";

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
  // 로그인한 환자면 접수를 계정에 연결합니다.
  const response = await request("/api/cases", { method: "POST", body, headers: patientAuthHeader() });
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

/** 로그인한 환자의 예약 현황 (AI 결과는 서버가 보내지 않습니다) */
export interface MyCase {
  id: string;
  doctorId: string;
  doctorName: string;
  doctorHospital: string;
  date: string;
  time: string;
  submittedAt: string;
  reviewState: string;
  photoIndices: number[];
  symptoms: string[];
  diagnosis?: string;
  opinion?: string;
  visitRequired?: boolean;
  visitMessage?: string;
}

export async function listMyCases(): Promise<MyCase[]> {
  const response = await fetch("/api/me/cases", { headers: patientAuthHeader(), cache: "no-store" });
  if (response.status === 401) throw new Error("로그인이 끝났어요. 다시 로그인해 주세요.");
  if (!response.ok) throw new Error(`서버 요청에 실패했습니다 (${response.status}).`);
  return await response.json() as MyCase[];
}

/** 내가 올린 사진을 화면에 띄울 주소로 바꿉니다. 다 쓰면 URL.revokeObjectURL로 정리하세요. */
export async function readMyPhoto(caseId: string, index: number): Promise<string> {
  const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/photos/${index}`, {
    headers: patientAuthHeader(), cache: "no-store",
  });
  if (!response.ok) throw new Error("사진을 불러오지 못했습니다.");
  return URL.createObjectURL(await response.blob());
}

export function forgetCase(id: string) {
  sessionStorage.removeItem(tokenKey(id));
  sessionStorage.removeItem(bookingKey(id));
}
