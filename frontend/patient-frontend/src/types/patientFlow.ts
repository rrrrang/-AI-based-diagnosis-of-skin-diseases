
/* ==========================================
   patientFlow.ts
   환자 예약 시스템 공통 데이터 타입
========================================== */

/**
 * 의사 프로필 이미지 종류
 *
 * long  : 김서연
 * short : 박지훈
 * bob   : 이다은
 */
export type DoctorAvatarType =
  | "long"
  | "short"
  | "bob";

/**
 * 가상 의사 정보
 *
 * DoctorReservation.tsx의 doctors 배열에서 사용
 */
export interface DoctorProfile {
  id: string;                  // 의사 고유 ID
  name: string;                // 의사 이름
  hospital: string;            // 병원명
  gender: string;              // 성별
  rank: number;                // 예약 순위
  avatar: DoctorAvatarType;    // 프로필 이미지 종류
}

/**
 * 환자 예약 정보
 *
 * 예약 확정 시 선택된 의사와
 * 날짜 및 시간을 저장하는 데 사용
 */
export interface Booking {
  doctor: DoctorProfile; // 선택한 의사 정보
  date: string;          // 예약 날짜 (YYYY-MM-DD)
  time: string;          // 예약 시간 (HH:mm)
}
