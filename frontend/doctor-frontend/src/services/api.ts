import type { DoctorCase } from "../types/doctorCase";

export const apiEnabled = import.meta.env.VITE_SKINAI_API === "true";
export const doctorTokenKey = "skinai-demo-doctor-token";

type Detail = Pick<DoctorCase, "id" | "doctorId" | "date" | "time" | "patientName" |
  "age" | "gender" | "symptoms" | "duration" | "description" | "aiState" |
  "reviewState" | "submittedAt" | "analysis"> &
  Partial<Pick<DoctorCase, "diagnosis" | "opinion" | "visitRequired" | "visitMessage">> &
  { photoIndices: number[] };

async function request(path: string, options?: RequestInit) {
  const token = sessionStorage.getItem(doctorTokenKey);
  if (!token) throw new Error("시연용 의사 토큰을 입력해 주세요.");
  const headers = new Headers(options?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
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
