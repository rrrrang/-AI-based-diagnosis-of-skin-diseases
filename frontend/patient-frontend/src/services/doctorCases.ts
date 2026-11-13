import { apiEnabled, forgetCase, readCase } from "./api";
/**
 * doctorCases.ts — 교육용 환자 접수 저장소
 *
 * 역할
 * 1. 예약·사진·문진을 하나의 접수 건으로 변환
 * 2. IndexedDB에 환자 접수와 의사 소견 저장
 * 3. 의사 UI에서 접수 목록 조회
 * 4. 현재 브라우저의 시연용 담당 의사 ID 기억
 *
 * 주의: 같은 브라우저·같은 출처에서만 공유됩니다.
 * 실제 의료정보 저장, 의사 인증, 다른 기기로의 전송 기능은 없습니다.
 */

import type { Booking } from "../types/patientFlow";
import type { DoctorCase } from "../types/doctorCase";

const DB_NAME = "skin-ai-demo-v1";
const STORE_NAME = "cases";
const LAST_DOCTOR_KEY = "skin-ai-demo-last-doctor";
const UPDATED_EVENT = "skin-ai-demo-cases-updated";

// 환자 화면에서 접근 가능한 접수 ID 목록 (개인정보 자체는 저장하지 않음)
const PATIENT_CASE_IDS_KEY = "skin-ai-demo-patient-case-ids";

/* ==========================================
   1. IndexedDB 데이터베이스 열기
========================================== */

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("이 브라우저는 로컬 시연 데이터 저장을 지원하지 않습니다."));
      return;
    }

    const request = indexedDB.open(DB_NAME, 1);

    request.onupgradeneeded = () => {
      const database = request.result;

      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, {
          keyPath: "id",
        });
      }
    };

    request.onsuccess = () => {
      resolve(request.result);
    };

    request.onerror = () => {
      reject(request.error ?? new Error("저장소 열기 실패"));
    };
  });
}

/* ==========================================
   2. 읽기·쓰기 트랜잭션 공통 처리
========================================== */

async function transaction<T>(
  mode: IDBTransactionMode,
  executor: (
    store: IDBObjectStore,
    resolve: (value: T) => void,
    reject: (reason?: unknown) => void
  ) => void
): Promise<T> {
  const database = await openDatabase();

  return new Promise<T>((resolve, reject) => {
    const tx = database.transaction(STORE_NAME, mode);
    const store = tx.objectStore(STORE_NAME);
    let result: T;
    let received = false;

    executor(
      store,
      (value) => {
        result = value;
        received = true;
      },
      reject
    );

    tx.oncomplete = () => {
      database.close();

      if (received) {
        resolve(result);
      } else {
        reject(new Error("저장 처리 결과가 없습니다."));
      }
    };

    tx.onerror = () => {
      database.close();
      reject(tx.error ?? new Error("저장 실패"));
    };

    tx.onabort = () => {
      database.close();
      reject(tx.error ?? new Error("저장 취소"));
    };
  });
}

/* ==========================================
   3. 환자 접수 목록 조회
========================================== */

export async function listDoctorCases(): Promise<DoctorCase[]> {
  if (apiEnabled) {
    const cases = await Promise.all(listPatientCaseIds().map(readCase));
    return cases.filter((item): item is DoctorCase => item !== null);
  }
  const entries = await transaction<DoctorCase[]>(
    "readonly",
    (store, resolve, reject) => {
      const request = store.getAll();

      request.onsuccess = () => {
        resolve(request.result as DoctorCase[]);
      };

      request.onerror = () => {
        reject(request.error);
      };
    }
  );

  return entries.sort((a, b) => {
    return (a.date + a.time).localeCompare(b.date + b.time);
  });
}

/* ==========================================
   4. 접수 정보 및 의사 소견 저장
========================================== */

export async function saveDoctorCase(item: DoctorCase): Promise<void> {
  await transaction<void>(
    "readwrite",
    (store, resolve, reject) => {
      const request = store.put(item);

      request.onsuccess = () => {
        resolve();
      };

      request.onerror = () => {
        reject(request.error);
      };
    }
  );

  // 같은 탭에서 예약표를 갱신하도록 알림
  window.dispatchEvent(new Event(UPDATED_EVENT));
}


/* ==========================================
   환자 진료 기록 개별 삭제
   - 선택한 접수번호에 해당하는 기록만 삭제
   - 환자 기록 목록에서도 해당 접수번호 제거
   - 의사 예약 관리표에도 삭제 내용 반영
========================================== */

export async function deletePatientCase(
  caseId: string
): Promise<void> {
  if (apiEnabled) forgetCase(caseId);
  else
  await transaction<void>(
    "readwrite",
    (store, resolve, reject) => {
      const request = store.delete(caseId);

      request.onsuccess = () => {
        resolve();
      };

      request.onerror = () => {
        reject(request.error);
      };
    }
  );

  // 2. 환자 진료 기록 목록에서 접수번호 제거
  const remainingIds = listPatientCaseIds().filter(
    (id) => id !== caseId
  );

  window.localStorage.setItem(
    PATIENT_CASE_IDS_KEY,
    JSON.stringify(remainingIds)
  );

  // 3. 의사 UI와 환자 UI에 변경 알림
  window.dispatchEvent(
    new Event(UPDATED_EVENT)
  );
}


/* ==========================================
   시연용 예약자 기록 초기화
   - 현재 담당 의사의 접수 기록만 삭제
   - 다른 의사의 기록은 유지
   - 환자 기록 목록에서도 삭제된 접수번호 제거
========================================== */

export async function clearDoctorReservations(
  doctorId: string
): Promise<void> {
  // 삭제할 접수번호를 임시 저장
  const deletedIds: string[] = [];

  // IndexedDB에서 해당 의사의 접수만 삭제
  await transaction<void>(
    "readwrite",
    (store, resolve, reject) => {
      const request = store.openCursor();

      request.onsuccess = () => {
        const cursor = request.result;

        // 모든 접수 기록 확인 완료
        if (!cursor) {
          resolve();
          return;
        }

        const item = cursor.value as DoctorCase;

        if (item.doctorId === doctorId) {
          // 삭제 대상 접수번호 기억
          deletedIds.push(item.id);

          // 현재 접수 기록 삭제
          cursor.delete();
        }

        // 다음 접수 기록 검사
        cursor.continue();
      };

      request.onerror = () => {
        reject(request.error);
      };
    }
  );

  // 환자 진료 기록 목록에서도 삭제된 ID 제거
  const deletedSet = new Set(deletedIds);

  const remainingIds = listPatientCaseIds().filter(
    (id) => !deletedSet.has(id)
  );

  window.localStorage.setItem(
    PATIENT_CASE_IDS_KEY,
    JSON.stringify(remainingIds)
  );

  // 의사 UI 예약 목록에 변경 알림
  window.dispatchEvent(
    new Event(UPDATED_EVENT)
  );
}


/* ==========================================
   5. 접수 데이터 변경 감지
========================================== */

export function subscribeDoctorCases(listener: () => void): () => void {
  window.addEventListener(UPDATED_EVENT, listener);
  window.addEventListener("focus", listener);
  const polling = apiEnabled ? window.setInterval(listener, 5000) : undefined;

  return () => {
    window.removeEventListener(UPDATED_EVENT, listener);
    window.removeEventListener("focus", listener);
    if (polling !== undefined) window.clearInterval(polling);
  };
}

/* ==========================================
   6. 시연용 담당 의사 ID 저장
========================================== */

export function rememberDoctor(doctorId: string): void {
  // 환자 정보는 localStorage에 저장하지 않음
  window.localStorage.setItem(LAST_DOCTOR_KEY, doctorId);
}

export function lastDoctorId(): string | null {
  return window.localStorage.getItem(LAST_DOCTOR_KEY);
}

/* ==========================================
   7. 환자 결과 확인을 위한 접수 ID 목록

   - 진료 데이터의 원본은 IndexedDB에 저장
   - localStorage에는 접수번호만 보관
   - 시연용 동일 브라우저/동일 주소에서만 사용
========================================== */

// 환자가 제출한 접수번호를 이전 기록 목록에 누적
export function rememberPatientCaseId(caseId: string): void {
  const ids = listPatientCaseIds();

  // 같은 접수번호를 다시 저장하더라도 중복 등록하지 않음
  const updated = [caseId, ...ids.filter((id) => id !== caseId)];

  window.localStorage.setItem(
    PATIENT_CASE_IDS_KEY,
    JSON.stringify(updated)
  );
}

// 이 브라우저에서 접수했던 기록의 ID 목록 조회
export function listPatientCaseIds(): string[] {
  try {
    const saved = window.localStorage.getItem(PATIENT_CASE_IDS_KEY);
    const parsed: unknown = saved ? JSON.parse(saved) : [];

    return Array.isArray(parsed)
      ? parsed.filter((id): id is string => typeof id === "string")
      : [];
  } catch {
    return [];
  }
}

/* ==========================================
   8. 환자 문진 데이터를 접수 건으로 변환
========================================== */

export function createPatientCase(input: {
  booking: Booking;
  patient: {
    name: string;
    age: number;
    gender: "female" | "male" | "none";
    description: string;
  };
  symptoms: string[];
  duration: string;
  photos: (File | null)[];
}): DoctorCase {
  const now = new Date().toISOString();

  return {
    id: `REQ-${crypto.randomUUID()}`,
    doctorId: input.booking.doctor.id,
    doctorName: input.booking.doctor.name,
    doctorHospital: input.booking.doctor.hospital,
    date: input.booking.date,
    time: input.booking.time,
    patientName: input.patient.name,
    age: input.patient.age,
    gender: input.patient.gender,
    description: input.patient.description,
    symptoms: input.symptoms,
    duration: input.duration,
    photos: [0, 1, 2].map((index) => input.photos[index] ?? null),

    // AI 모델 미연결: 실제 결과인 것처럼 표시하지 않음
    aiState: "대기",
    predictions: [],
    analysisPhoto: null,
    maskPhoto: null,

    reviewState: "검토 대기",
    diagnosis: "",
    opinion: "",
    visitRequired: false,
    visitMessage: "",
    submittedAt: now,
    updatedAt: now,
  };
}
