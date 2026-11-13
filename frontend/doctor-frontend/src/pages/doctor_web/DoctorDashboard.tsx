
/* 의사 PC 웹의 상단 예약 관리 화면 환자 자료 및 AI 결과는 PatientReview에서 표시
*/
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
  UserRound,
  Trash2,
} from "lucide-react";

import PatientReview from "./PatientReview";

import type { DoctorCase } from "../../types/doctorCase";

import {
  lastDoctorId,
  listDoctorCases,
  subscribeDoctorCases,
  clearDoctorReservations,
} from "../../services/doctorCases";

import "../../css/Doctor.css";

/* ==========================================
   1. 예약 목록 기본 설정
========================================== */

// 예약자 최대 3명씩 표시
const PAGE_SIZE = 3;

// 교육용 가상 의사 정보
const DOCTORS: Record<
  string,
  { name: string; hospital: string }
> = {
  d1: {
    name: "김서연",
    hospital: "서울아산병원",
  },
  d2: {
    name: "박지훈",
    hospital: "삼성서울병원",
  },
  d3: {
    name: "이다은",
    hospital: "세브란스병원",
  },
};

// 날짜를 YYYY-MM-DD 형식으로 변환
function formatDate(date: Date): string {
  const year = date.getFullYear();

  const month = String(
    date.getMonth() + 1
  ).padStart(2, "0");

  const day = String(
    date.getDate()
  ).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

/* ==========================================
   2. 의사 대시보드
========================================== */

export default function DoctorDashboard() {
  // 접수된 전체 환자 정보
  const [cases, setCases] = useState<DoctorCase[]>([]);

  // 데이터 조회 상태
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  // 담당 의사 ID
  const [doctorId, setDoctorId] = useState<string | null>(
    () => lastDoctorId()
  );

  // 예약 날짜
  const [date, setDate] = useState(
    () => formatDate(new Date())
  );

  // 환자 검색어
  const [search, setSearch] = useState("");

  // 예약 검토 상태 필터
  const [filter, setFilter] = useState<
    "전체" | "검토 대기" | "완료"
  >("전체");

  // 예약 목록 페이지
  const [page, setPage] = useState(1);

  // 현재 선택된 환자 ID
  const [selectedId, setSelectedId] = useState<
    string | null
  >(null);

  /* ========================================
     3. 환자 접수 정보 조회
  ======================================== */

  const refresh = useCallback(async () => {
    setLoading(true);

    try {
      const items = await listDoctorCases();

      setCases(items);
      setLoadError("");

      // 시연용: 최근 예약한 의사 정보를 사용
      const remembered = lastDoctorId();

      const recent = [...items].sort(
        (a, b) =>
          b.submittedAt.localeCompare(a.submittedAt)
      )[0];

      setDoctorId(
        remembered ?? recent?.doctorId ?? null
      );
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : "환자 접수 정보 조회에 실패했습니다."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  /* ========================================
     4. 데이터 변경 감지
  ======================================== */

  useEffect(() => {
    void refresh();

    return subscribeDoctorCases(() => {
      void refresh();
    });
  }, [refresh]);

  /* ========================================
     5. 담당 의사의 예약만 조회
  ======================================== */

  const doctorCases = useMemo(() => {
    return cases.filter(
      (item) => item.doctorId === doctorId
    );
  }, [cases, doctorId]);

  const doctorName =
    doctorCases[0]?.doctorName ??
    (doctorId ? DOCTORS[doctorId]?.name : undefined);

  const doctorHospital =
    doctorCases[0]?.doctorHospital ??
    (doctorId ? DOCTORS[doctorId]?.hospital : undefined);

  /* ========================================
     6. 날짜별 예약 조회
  ======================================== */

  const dated = useMemo(() => {
    return doctorCases
      .filter((item) => item.date === date)
      .sort(
        (a, b) => a.time.localeCompare(b.time)
      );
  }, [doctorCases, date]);

  /* ========================================
     7. 환자 검색 및 상태 필터
  ======================================== */

  const visible = useMemo(() => {
    return dated.filter((item) => {
      const matchesName = item.patientName
        .toLowerCase()
        .includes(search.trim().toLowerCase());

      const matchesStatus =
        filter === "전체" ||
        (filter === "완료"
          ? item.reviewState === "결과 전달 완료"
          : item.reviewState !== "결과 전달 완료");

      return matchesName && matchesStatus;
    });
  }, [dated, search, filter]);

  /* ========================================
     8. 예약자 3명씩 표시
  ======================================== */

  const pageCount = Math.max(
    1,
    Math.ceil(visible.length / PAGE_SIZE)
  );

  const currentPage = Math.min(page, pageCount);

  const shown = visible.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  /* ========================================
     9. 예약 통계 및 선택 환자
  ======================================== */

  const waitingCount = dated.filter(
    (item) =>
      item.reviewState !== "결과 전달 완료"
  ).length;

  const completedCount = dated.filter(
    (item) =>
      item.reviewState === "결과 전달 완료"
  ).length;

  const selectedPatient =
    cases.find(
      (item) =>
        item.id === selectedId &&
        item.doctorId === doctorId
    ) ?? null;

  /* ========================================
     10. 예약 날짜 변경
  ======================================== */

  const changeDate = (offset: number) => {
    const nextDate = new Date(`${date}T12:00:00`);

    nextDate.setDate(
      nextDate.getDate() + offset
    );

    setDate(formatDate(nextDate));
    setPage(1);
    setSelectedId(null);
  };

  const selectDate = (newDate: string) => {
    if (!newDate) return;

    setDate(newDate);
    setPage(1);
    setSelectedId(null);
  };
  
  /* ==========================================
     시연용 예약자 명단 초기화
     - 버튼 클릭 시 확인창 표시
     - 현재 담당 의사의 기록만 삭제
     - 삭제 후 예약 목록 자동 갱신
  ========================================== */
  
  const handleClearReservations = async () => {
    // 담당 의사가 정해지지 않았다면 중단
    if (!doctorId) {
      window.alert("담당 의사 정보가 없습니다.");
      return;
    }
  
    // 실수로 기록을 삭제하지 않도록 확인
    const confirmed = window.confirm(
      `${doctorName ?? "현재 담당 의사"}의 시연 예약 기록을 ` +
      `모두 삭제하시겠습니까?\n\n` +
      `환자 사진, 문진, AI 결과 및 의사 소견도 함께 삭제되며 ` +
      `복구할 수 없습니다.`
    );
  
    if (!confirmed) {
      return;
    }
  
    try {
      // 저장된 시연 접수 기록 삭제
      await clearDoctorReservations(doctorId);
  
      // 선택 중인 환자와 페이지 초기화
      setSelectedId(null);
      setPage(1);
  
      // 예약자 목록 다시 불러오기
      await refresh();
  
      window.alert(
        "현재 담당 의사의 시연 기록이 초기화되었습니다."
      );
    } catch (error) {
      console.error("예약 기록 초기화 실패:", error);
  
      window.alert(
        "기록 삭제 중 오류가 발생했습니다."
      );
    }
  };


  /* ========================================
     11. 의사 화면
  ======================================== */

  return (
    <main className="doctor-dashboard">

      {/* 상단 담당 의사 정보 */}
      <div className="doctor-heading">
        <div>
          <h1>가상 의사 검토</h1>

          <p>
            <UserRound size={17} />

            {doctorName
              ? `${doctorName} 의사 · ${doctorHospital}`
              : "담당 의사 정보가 없습니다."}
          </p>
        </div>

        <span className="doctor-demo-pill">
          교육용 시뮬레이션
        </span>
      </div>

      {/* 예약 관리 카드 */}
      <section
        className="doctor-panel doctor-booking-panel"
        aria-label="예약 관리"
      >
        <div className="doctor-booking-header">

          {/* 예약 현황 */}
          <div className="doctor-booking-title">
            <h2>예약 관리</h2>

            <p>
              예약 {dated.length}건
              <span>·</span>
              검토 대기 {waitingCount}건
              <span>·</span>
              완료 {completedCount}건
            </p>
          </div>

          <div className="doctor-tools">

            {/* 날짜 선택 */}
            <div className="doctor-calendar-tools">
              <button
                type="button"
                aria-label="이전 날짜"
                onClick={() => changeDate(-1)}
              >
                <ChevronLeft size={18} />
              </button>

              <label>
                <CalendarDays size={16} />

                <input
                  type="date"
                  aria-label="예약 날짜"
                  value={date}
                  onChange={(event) =>
                    selectDate(event.target.value)
                  }
                />
              </label>

              <button
                type="button"
                aria-label="다음 날짜"
                onClick={() => changeDate(1)}
              >
                <ChevronRight size={18} />
              </button>

              <button
                type="button"
                className="doctor-today"
                onClick={() =>
                  selectDate(formatDate(new Date()))
                }
              >
                오늘
              </button>
            </div>

            {/* 환자 이름 검색 */}
            <label className="doctor-search">
              <Search size={17} />

              <input
                type="search"
                placeholder="환자명 검색"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPage(1);
                }}
              />
            </label>

            {/* 상태별 필터 */}
            <div
              className="doctor-filters"
              role="group"
              aria-label="검토 상태"
            >
              {(
                ["전체", "검토 대기", "완료"] as const
              ).map((option) => (
                <button
                  key={option}
                  type="button"
                  className={
                    filter === option ? "is-active" : ""
                  }
                  onClick={() => {
                    setFilter(option);
                    setPage(1);
                  }}
                >
                  {option}
                </button>
              ))}
            </div>

            {/* 예약 정보 새로고침 */}
            <button
              type="button"
              className="doctor-refresh"
              aria-label="예약 정보 새로고침"
              onClick={() => void refresh()}
            >
              <RefreshCw size={17} />
            </button>

            
            {/* ==================================
                시연용 예약 기록 초기화 버튼
            ================================== */}
            
            <button
              type="button"
              className="doctor-clear-button"
              onClick={() => void handleClearReservations()}
              disabled={!doctorId || loading}
              title="현재 담당 의사의 시연 기록 삭제"
            >
              <Trash2 size={16} />
              시연 기록 초기화
            </button>

          </div>
        </div>

        {/* 예약 환자 테이블 */}
        <div className="doctor-table-outer">
          <table className="doctor-table">
            <thead>
              <tr>
                <th>예약 시간</th>
                <th>환자 정보</th>
                <th>주요 증상</th>
                <th>AI 상태</th>
                <th>의사 검토</th>
                <th>상세 보기</th>
              </tr>
            </thead>

            <tbody>
              {shown.map((item) => (
                <tr
                  key={item.id}
                  className={
                    selectedId === item.id
                      ? "is-selected"
                      : ""
                  }
                >
                  <td>{item.time}</td>

                  <td>
                    <strong>{item.patientName}</strong>

                    <small>
                      {item.age}세 ·{" "}
                      {item.gender === "female"
                        ? "여성"
                        : item.gender === "male"
                          ? "남성"
                          : "미선택"}
                    </small>
                  </td>

                  <td>{item.symptoms.join(", ")}</td>

                  <td>
                    <span
                      className={`doctor-status ${
                        item.aiState === "완료"
                          ? "is-done"
                          : item.aiState === "시연 결과"
                            ? "is-demo"
                            : "is-wait"
                      }`}
                    >
                      {item.aiState}
                    </span>
                  </td>

                  <td>
                    <span
                      className={`doctor-status ${
                        item.reviewState ===
                        "결과 전달 완료"
                          ? "is-done"
                          : item.reviewState ===
                            "임시 저장"
                            ? "is-demo"
                            : "is-wait"
                      }`}
                    >
                      {item.reviewState}
                    </span>
                  </td>

                  <td>
                    <button
                      type="button"
                      className="doctor-review-link"
                      onClick={() =>
                        setSelectedId(item.id)
                      }
                    >
                      {item.reviewState ===
                      "결과 전달 완료"
                        ? "결과 보기"
                        : "검토하기"}

                      <ChevronRight size={15} />
                    </button>
                  </td>
                </tr>
              ))}

              {shown.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="doctor-table-empty"
                  >
                    {loading
                      ? "예약 정보를 불러오는 중입니다."
                      : loadError ||
                        "선택한 조건에 해당하는 예약이 없습니다."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 3명씩 페이지 이동 */}
        <div className="doctor-pagination">
          <span>예약자 최대 3명씩 표시</span>

          <div>
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => {
                setPage(currentPage - 1);
                setSelectedId(null);
              }}
            >
              이전
            </button>

            <span>
              {currentPage} / {pageCount}
            </span>

            <button
              type="button"
              disabled={currentPage >= pageCount}
              onClick={() => {
                setPage(currentPage + 1);
                setSelectedId(null);
              }}
            >
              다음
            </button>
          </div>
        </div>
      </section>

      {/* 2단계 환자 자료 및 AI 분석 연결 */}
      <PatientReview
        patient={selectedPatient}
        onSaved={refresh}
      />

      {/* 교육용 안내 */}
      <footer className="doctor-footer">
        교육용 시뮬레이션입니다.
        실제 의료 진단·치료를 제공하지 않습니다.
      </footer>
    </main>
  );
}
