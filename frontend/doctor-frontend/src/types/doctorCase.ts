
/* 환자 제출 자료 / AI 분석 결과 / 가상 의사 검토 자료의 공통 타입
*/

// AI 분석 진행 상태
export type AIState =
  | "대기"
  | "분석 중"
  | "시연 결과"
  | "완료"
  | "실패";

// 의사 검토 진행 상태
export type ReviewState =
  | "검토 대기"
  | "임시 저장"
  | "결과 전달 완료";

// AI가 예측한 질환별 점수
export interface Prediction {
  label: string;
  score: number;
}

// 환자 접수부터 의사 최종 결과까지의 정보
export interface DoctorCase {
  // 접수 번호
  id: string;

  // 환자가 예약한 의사
  doctorId: string;
  doctorName: string;
  doctorHospital: string;

  // 예약 날짜 및 시간
  date: string;
  time: string;

  // 환자 기본 정보
  patientName: string;
  age: number;
  gender: "female" | "male" | "none";

  // 환자 증상 및 문진
  symptoms: string[];
  duration: string;
  description: string;

  // 환자 등록 사진
  // 0: 정면 / 1: 증상 부위 1 / 2: 증상 부위 2
  photos: (File | null)[];

  // AI 분석 정보
  aiState: AIState;
  predictions: Prediction[];
  photoIndices?: number[];
  analysis?: {
    candidate: string | null;
    decision: "majority" | "single_qualified" | "normal_consensus" | "deferred" | "undetermined";
    votes: Record<string, number>;
    analyzedPhotoIndex: number;
  } | null;

  // AI 분석 원본 및 마스킹 이미지
  analysisPhoto: File | Blob | null;
  maskPhoto: File | Blob | null;

  // 의사 최종 검토 정보
  reviewState: ReviewState;
  diagnosis: string;
  opinion: string;
  visitRequired: boolean;
  visitMessage: string;

  // 접수 및 수정 시각
  submittedAt: string;
  updatedAt: string;
}
