
/* ==========================================
   demoFlow.ts
   교육용 시뮬레이션 임시 데이터 저장소
========================================== */

// 예약 정보 타입 가져오기
import type { Booking } from "../types/patientFlow";

/**
 * 환자 UI에서 공통으로 사용하는
 * 시뮬레이션 데이터 저장소
 *
 * 현재는 백엔드 및 데이터베이스 미연결 상태
 */
interface DemoFlow {
  // 예약이 없으면 null
  booking: Booking | null;
}

/**
 * 예약 화면에서 선택한 데이터를
 * 임시로 저장하는 객체
 */
export const demoFlow: DemoFlow = {
  booking: null,
};
