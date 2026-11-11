
/* 역할:
 * 1. 가상 의사 3명 중 한 명 선택
 * 2. 의사의 병원, 성별, 예약 순위 표시
 * 3. 월간 달력에서 예약 날짜 선택
 * 4. 의사별 예약 가능 시간 표시
 * 5. 예약 정보를 임시 저장하고 사진 등록 화면으로 이동
 *
 * 이번 수정:
 * - 기존 모바일 예약 UI 유지
 * - 담당 의사 ID 저장 기능 추가
 * - 잘못 들어간 환자 문진 저장 코드 제거
 */

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

// 예약한 담당 의사 ID 저장
import { rememberDoctor } from "../../services/doctorCases";

// 예약 화면에서 사용할 아이콘
import {
  Building2,      // 병원
  CalendarDays,   // 예약 날짜
  ChevronLeft,    // 이전 화면 / 이전 달
  ChevronRight,   // 다음 화면 / 다음 달
  Crown,          // 예약 순위
  UserRound,      // 성별
  Check,          // 의사 선택 표시
  Clock3,         // 예약 시간
} from "lucide-react";

// 의사 프로필 이미지 컴포넌트
import DoctorAvatar from "../../components/DoctorAvatar";

// 기존 시연용 예약 정보 저장소
import { demoFlow } from "../../services/demoFlow";

// 예약 데이터 타입
import type {
  Booking,
  DoctorProfile,
} from "../../types/patientFlow";

// 기존 예약 UI CSS
import "../../css/Reservation.css";

/* ==========================================
   1. 가상 의사 정보
========================================== */

const doctors: DoctorProfile[] = [
  {
    id: "d1",
    name: "김서연",
    hospital: "서울아산병원",
    gender: "여성",
    rank: 1,
    avatar: "long",
  },
  {
    id: "d2",
    name: "박지훈",
    hospital: "삼성서울병원",
    gender: "남성",
    rank: 2,
    avatar: "short",
  },
  {
    id: "d3",
    name: "이다은",
    hospital: "세브란스병원",
    gender: "여성",
    rank: 3,
    avatar: "bob",
  },
];

/* ==========================================
   2. 시연용 예약 시간
========================================== */

// 30분 단위 상담 시작 시간
// 13:00 ~ 13:30 시간은 제공하지 않음
const clockOptions = [
  "10:00",
  "10:30",
  "11:00",
  "11:30",
  "12:00",
  "12:30",
  "14:00",
  "14:30",
  "15:00",
  "15:30",
  "16:00",
  "16:30",
];

/* ==========================================
   3. 날짜 처리 함수
========================================== */

// 숫자를 두 자리 문자열로 변환
// 예: 5 → "05"
const two = (num: number): string => {
  return String(num).padStart(2, "0");
};

// 날짜를 YYYY-MM-DD 형식으로 변환
const dateKey = (
  year: number,
  month: number,
  day: number
): string => {
  return `${year}-${two(month + 1)}-${two(day)}`;
};

// 오늘 날짜를 자정으로 설정
const today = (): Date => {
  const date = new Date();

  date.setHours(0, 0, 0, 0);

  return date;
};

/* ==========================================
   4. 의사별 예약 가능 날짜
========================================== */

function canBook(
  doctor: DoctorProfile,
  year: number,
  month: number,
  day: number
): boolean {
  const selectedDate = new Date(
    year,
    month,
    day
  );

  // 지난 날짜 및 주말 예약 불가
  if (
    selectedDate < today() ||
    selectedDate.getDay() === 0 ||
    selectedDate.getDay() === 6
  ) {
    return false;
  }

  // 박지훈: 화요일 예약 불가
  if (
    doctor.id === "d2" &&
    selectedDate.getDay() === 2
  ) {
    return false;
  }

  // 이다은: 목요일 예약 불가
  if (
    doctor.id === "d3" &&
    selectedDate.getDay() === 4
  ) {
    return false;
  }

  return true;
}

/* ==========================================
   5. 의사별 특정 날짜 예약 불가 시간
========================================== */

// 의사 ID → 날짜 → 예약 불가 시간 목록
const unavailableByDate: Record<
  string,
  Record<string, string[]>
> = {
  // 김서연
  d1: {
    "2026-11-23": [
      "10:00",
      "10:30",
      "11:00",
    ],
  },

  // 박지훈
  d2: {
    "2026-11-11": [
      "15:00",
      "15:30",
      "16:00",
      "16:30",
    ],
    "2026-11-27": ["10:00"],
  },

  // 이다은
  d3: {},
};

/* ==========================================
   6. 의사별 반복 예약 불가 시간
========================================== */

const recurringUnavailableTimes: Record<
  string,
  string[]
> = {
  d1: [],
  d2: [],

  // 이다은: 매일 12:30 예약 불가
  d3: ["12:30"],
};

/* ==========================================
   7. 예약 가능한 시간만 반환
========================================== */

function availableTimes(
  doctor: DoctorProfile,
  day: string
): string[] {
  // 날짜 미선택 시 시간 목록 없음
  if (!day) {
    return [];
  }

  // 해당 날짜에 예약 불가한 시간
  const blockedByDate =
    unavailableByDate[doctor.id]?.[day] ?? [];

  // 매일 반복되는 예약 불가 시간
  const blockedRecurring =
    recurringUnavailableTimes[doctor.id] ?? [];

  // 예약 불가 시간 합치기
  const blockedTimes = [
    ...blockedByDate,
    ...blockedRecurring,
  ];

  // 예약 가능한 시간만 반환
  return clockOptions.filter(
    (time) => !blockedTimes.includes(time)
  );
}

/* ==========================================
   8. 예약 페이지 컴포넌트
========================================== */

export default function DoctorReservation() {
  // 페이지 이동
  const navigate = useNavigate();

  // 현재 화면 단계
  const [step, setStep] = useState<
    "doctor" | "calendar"
  >("doctor");

  // 선택한 의사 ID
  const [doctorId, setDoctorId] = useState(
    demoFlow.booking?.doctor.id ?? "d1"
  );

  // 현재 날짜
  const current = useMemo(
    () => new Date(),
    []
  );

  // 달력 월 이동 값
  const [monthOffset, setMonthOffset] = useState(0);

  // 선택한 날짜
  const [date, setDate] = useState(
    demoFlow.booking?.date ?? ""
  );

  // 선택한 시간
  const [time, setTime] = useState(
    demoFlow.booking?.time ?? ""
  );

  // 선택한 의사 정보
  const doctor =
    doctors.find((item) => item.id === doctorId) ??
    doctors[0];

  /* ==========================================
     9. 달력 날짜 계산
  ========================================== */

  // 현재 달을 기준으로 이동
  const displayedMonth = new Date(
    current.getFullYear(),
    current.getMonth() + monthOffset,
    1
  );

  const year = displayedMonth.getFullYear();
  const month = displayedMonth.getMonth();

  // 현재 월의 마지막 날짜
  const monthLength = new Date(
    year,
    month + 1,
    0
  ).getDate();

  // 현재 월 1일의 요일
  const leading = new Date(
    year,
    month,
    1
  ).getDay();

  // 달력에 표시할 날짜 배열
  const cells = Array.from(
    {
      length:
        Math.ceil(
          (leading + monthLength) / 7
        ) * 7,
    },
    (_, index) => index - leading + 1
  );

  // 선택한 의사의 예약 가능 시간
  const slots = availableTimes(doctor, date);

  /* ==========================================
     10. 의사 선택 함수
  ========================================== */

  const selectDoctor = (id: string) => {
    setDoctorId(id);

    // 의사가 변경되면 날짜와 시간 초기화
    setDate("");
    setTime("");
  };

  /* ==========================================
     11. 예약 확정 함수
  ========================================== */

  const confirm = () => {
    // 날짜 및 시간 미선택
    if (!date || !time) {
      return;
    }

    // 예약 가능한 시간이 아닌 경우
    if (!slots.includes(time)) {
      return;
    }

    // 예약 데이터 생성
    const booking: Booking = {
      doctor,
      date,
      time,
    };

    // 기존 예약 정보를 임시 저장소에 보관
    demoFlow.booking = booking;

    // 선택한 담당 의사 ID 저장
    // 의사 UI의 시연용 담당 의사 표시에서 사용
    rememberDoctor(booking.doctor.id);

    // 기존 환자 사진 등록 화면으로 이동
    navigate("/patient/upload");
  };

  /* ==========================================
     12. 예약 페이지 화면
  ========================================== */

  return (
    <main className="reservation-page">
      <section
        className={`reservation-card ${
          step === "doctor"
            ? "reservation-doctor-card"
            : "reservation-calendar-card"
        }`}
      >
        <div className="reservation-scroll">

          {/* 상단 로고 */}
          <button
            type="button"
            className="res-brand"
            onClick={() => navigate("/patient")}
            aria-label="환자 홈으로 이동"
          >
            <img
              src="/main_logo.png"
              alt="피부진단 AI 로고"
            />

            <strong>피부진단 AI</strong>
          </button>

          {/* ==================================
              첫 번째 화면: 가상 의사 선택
          ================================== */}

          {step === "doctor" ? (
            <>
              <h1 className="res-page-title">
                가상 의사 선택
              </h1>

              <p className="res-subtitle">
                피부 진단을 예약할 가상 의사를
                선택해 주세요.
              </p>

              {/* 의사 선택 카드 3개 */}
              <div className="res-doctor-list">
                {doctors.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className={`res-doctor-card ${
                      doctorId === item.id
                        ? "is-selected"
                        : ""
                    }`}
                    aria-pressed={doctorId === item.id}
                    onClick={() => selectDoctor(item.id)}
                  >
                    {/* 의사 프로필 일러스트 */}
                    <DoctorAvatar
                      avatar={item.avatar}
                      size={92}
                    />

                    {/* 의사 상세 정보 */}
                    <div className="res-doctor-details">
                      <strong>{item.name}</strong>

                      <span>
                        <Building2 size={16} />
                        {item.hospital}
                      </span>

                      <span>
                        <UserRound size={16} />
                        {item.gender}
                      </span>

                      <span className="res-rank">
                        <Crown size={16} />
                        예약순위 {item.rank}위
                      </span>
                    </div>

                    {/* 의사 선택 및 예약 가능 표시 */}
                    <div className="res-doctor-availability">
                      <span className="res-choice-circle">
                        {doctorId === item.id && (
                          <Check size={14} />
                        )}
                      </span>

                      <small>예약 가능</small>

                      <span className="res-available-dot">
                        가능
                      </span>
                    </div>
                  </button>
                ))}
              </div>

              {/* 다음 화면 이동 버튼 */}
              <button
                type="button"
                className="res-primary"
                onClick={() => setStep("calendar")}
              >
                날짜·시간 선택
                <ChevronRight size={22} />
              </button>
            </>
          ) : (
            <>
              {/* ==================================
                  두 번째 화면: 예약 날짜·시간
              ================================== */}

              {/* 상단 예약 정보 */}
              <div className="res-booking-top">
                <h1 className="res-booking-title">
                  예약 정보
                </h1>

                <div className="res-selected-doctor">

                  {/* 의사 프로필 */}
                  <div className="res-selected-profile">
                    <DoctorAvatar
                      avatar={doctor.avatar}
                      size={64}
                    />

                    <div className="res-selected-details">
                      <strong>{doctor.name}</strong>

                      <span>
                        <Building2 size={15} />
                        {doctor.hospital} · {doctor.gender}
                      </span>

                      <span className="res-rank">
                        <Crown size={15} />
                        예약순위 {doctor.rank}위 (샘플)
                      </span>
                    </div>
                  </div>

                  {/* 예약 정보 구분선 */}
                  <div className="res-booking-divider" />

                  {/* 선택한 예약 날짜 */}
                  <div className="res-booking-detail">
                    <span className="res-booking-label">
                      <CalendarDays size={18} />
                      예약 날짜
                    </span>

                    <strong>
                      {date || "날짜를 선택해 주세요"}
                    </strong>
                  </div>

                  {/* 선택한 예약 시간 */}
                  <div className="res-booking-detail">
                    <span className="res-booking-label">
                      <Clock3 size={18} />
                      예약 시간
                    </span>

                    <strong>
                      {time || "시간을 선택해 주세요"}
                    </strong>
                  </div>
                </div>
              </div>

              {/* 예약 일정 제목 */}
              <h1 className="res-page-title">
                예약 날짜·시간 선택
              </h1>

              <p className="res-subtitle">
                진료를 받을 날짜와 시간을 선택해 주세요.
              </p>

              {/* ==================================
                  월간 예약 달력
              ================================== */}

              <div className="res-calendar">

                {/* 달력 상단 */}
                <div className="res-calendar-head">

                  {/* 이전 달 */}
                  <button
                    type="button"
                    aria-label="이전 달"
                    disabled={monthOffset === 0}
                    onClick={() => {
                      setMonthOffset((n) =>
                        Math.max(0, n - 1)
                      );

                      setDate("");
                      setTime("");
                    }}
                  >
                    <ChevronLeft />
                  </button>

                  {/* 현재 연도 및 월 */}
                  <strong>
                    {year}년 {month + 1}월
                  </strong>

                  {/* 다음 달 */}
                  <button
                    type="button"
                    aria-label="다음 달"
                    disabled={monthOffset === 2}
                    onClick={() => {
                      setMonthOffset((n) =>
                        Math.min(2, n + 1)
                      );

                      setDate("");
                      setTime("");
                    }}
                  >
                    <ChevronRight />
                  </button>
                </div>

                {/* 요일 */}
                <div className="res-days">
                  {[
                    "일",
                    "월",
                    "화",
                    "수",
                    "목",
                    "금",
                    "토",
                  ].map((day) => (
                    <b key={day}>{day}</b>
                  ))}
                </div>

                {/* 날짜 */}
                <div className="res-dates">
                  {cells.map((day, index) => {

                    // 현재 월에 없는 칸
                    if (
                      day < 1 ||
                      day > monthLength
                    ) {
                      return (
                        <span
                          key={`blank-${index}`}
                          className="res-empty"
                        />
                      );
                    }

                    // 날짜를 문자열로 변환
                    const key = dateKey(
                      year,
                      month,
                      day
                    );

                    // 예약 가능 날짜 확인
                    const active = canBook(
                      doctor,
                      year,
                      month,
                      day
                    );

                    return (
                      <button
                        type="button"
                        key={key}
                        disabled={!active}
                        className={
                          date === key
                            ? "selected"
                            : ""
                        }
                        onClick={() => {
                          setDate(key);

                          // 날짜가 바뀌면 시간 초기화
                          setTime("");
                        }}
                      >
                        <span>{day}</span>

                        {/* 예약 가능 표시 점 */}
                        <i
                          className={
                            active
                              ? "available"
                              : ""
                          }
                        />
                      </button>
                    );
                  })}
                </div>

                {/* 달력 범례 */}
                <div className="res-calendar-legend">
                  <span>
                    <i className="available" />
                    예약 가능
                  </span>

                  <span>
                    <i />
                    예약 불가
                  </span>
                </div>
              </div>

              {/* ==================================
                  예약 시간 선택
              ================================== */}

              <h2 className="res-section-title">
                시간 선택
              </h2>

              <div className="res-time-grid">
                {date ? (
                  clockOptions.map((option) => (
                    <button
                      type="button"
                      key={option}
                      disabled={
                        !slots.includes(option)
                      }
                      className={
                        option === time
                          ? "selected"
                          : ""
                      }
                      onClick={() => setTime(option)}
                    >
                      {option}
                    </button>
                  ))
                ) : (
                  <p className="res-select-date">
                    달력에서 날짜를 먼저 선택해 주세요.
                  </p>
                )}
              </div>

              {/* ==================================
                  예약 확정 버튼
              ================================== */}

              <button
                type="button"
                className="res-primary"
                disabled={!date || !time}
                onClick={confirm}
              >
                예약 확정
              </button>

              {/* 의사 선택 화면으로 이동 */}
              <button
                type="button"
                className="res-text-back"
                onClick={() => setStep("doctor")}
              >
                <ChevronLeft size={18} />
                의사 선택으로 돌아가기
              </button>
            </>
          )}

          {/* ==================================
              하단 시뮬레이션 안내
          ================================== */}

          <p className="res-footnote">
            <Clock3 size={14} />
            화면 내 예약 정보는 시연용이며
            실제 예약이 생성되지 않습니다.
          </p>

        </div>
        {/* reservation-scroll 끝 */}

      </section>
    </main>
  );
}
