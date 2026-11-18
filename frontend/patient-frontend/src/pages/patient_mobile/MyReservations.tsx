/* 내 예약 현황
 *
 * 로그인한 환자가 보는 화면
 * - 어느 의사에게, 언제 예약했는지
 * - 어떤 사진을 올렸는지
 * - 지금 상태(의사 검토 중 / 결과 도착)와, 의사가 결과를 전달한 뒤의 소견
 * AI 후보·점수는 보여 주지 않습니다(의사가 확정한 소견만 공개).
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { apiEnabled, listMyCases, readMyPhoto, type MyCase } from "../../services/api";
import { currentPatient, patientLogout } from "../../services/auth";
import { listDoctorCases, listPatientCaseIds } from "../../services/doctorCases";
import "../../css/Patient.css";
import "../../css/Login.css";

// 예약 화면(DoctorReservation)과 같은 의사 정보
const DOCTORS: Record<string, { name: string; hospital: string }> = {
  d1: { name: "김서연", hospital: "서울아산병원" },
  d2: { name: "박지훈", hospital: "삼성서울병원" },
  d3: { name: "이다은", hospital: "세브란스병원" },
};

const PHOTO_LABELS = ["정면", "증상 부위 1", "증상 부위 2"];

interface Reservation extends MyCase {
  photoUrls: { label: string; url: string }[];
}

async function loadFromServer(): Promise<Reservation[]> {
  const cases = await listMyCases();
  return Promise.all(cases.map(async (item) => ({
    ...item,
    photoUrls: (await Promise.all(item.photoIndices.map(async (index) => {
      try {
        return { label: PHOTO_LABELS[index], url: await readMyPhoto(item.id, index) };
      } catch {
        return null;
      }
    }))).filter((photo): photo is { label: string; url: string } => photo !== null),
  })));
}

async function loadFromDemo(name: string): Promise<Reservation[]> {
  const mine = new Set(listPatientCaseIds());
  const cases = (await listDoctorCases()).filter((item) => mine.has(item.id) && item.patientName === name);
  return cases.map((item) => ({
    id: item.id, doctorId: item.doctorId, doctorName: item.doctorName, doctorHospital: item.doctorHospital,
    date: item.date, time: item.time, submittedAt: item.submittedAt, reviewState: item.reviewState,
    symptoms: item.symptoms, photoIndices: [],
    ...(item.reviewState === "결과 전달 완료" ? {
      diagnosis: item.diagnosis, opinion: item.opinion,
      visitRequired: item.visitRequired, visitMessage: item.visitMessage,
    } : {}),
    photoUrls: item.photos.flatMap((file, index) =>
      file ? [{ label: PHOTO_LABELS[index], url: URL.createObjectURL(file) }] : []),
  }));
}

function MyReservations() {
  const navigate = useNavigate();
  const patient = currentPatient();
  const [items, setItems] = useState<Reservation[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let urls: string[] = [];
    let active = true;
    (apiEnabled ? loadFromServer() : loadFromDemo(patient?.name ?? ""))
      .then((result) => {
        urls = result.flatMap((item) => item.photoUrls.map((photo) => photo.url));
        if (active) setItems(result);
      })
      .catch((error) => {
        if (active) setErrorMessage(error instanceof Error ? error.message : "예약 현황을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (active) setLoaded(true);
      });
    return () => {
      active = false;
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [patient?.name]);

  const logout = async () => {
    await patientLogout();
    navigate("/patient/login", { replace: true });
  };

  return (
    <main className="my-page">
      <div className="my-top">
        <button type="button" className="info-back-button" aria-label="처음 화면으로" onClick={() => navigate("/patient")}>
          <ArrowLeft size={24} />
        </button>
        <h1>내 예약 현황</h1>
        <button type="button" className="patient-logout-button" onClick={() => void logout()}>
          로그아웃
        </button>
      </div>

      {errorMessage && <p className="info-error" role="alert">{errorMessage}</p>}
      {loaded && !errorMessage && items.length === 0 && (
        <p className="my-empty">아직 접수한 예약이 없어요.<br />처음 화면에서 AI 피부 분석을 시작해 주세요.</p>
      )}

      {items.map((item) => {
        const doctor = DOCTORS[item.doctorId] ?? { name: item.doctorName, hospital: item.doctorHospital };
        const done = item.reviewState === "결과 전달 완료";
        return (
          <article key={item.id} className="my-card" aria-label={`${doctor.name} 선생님 예약`}>
            <h2>{doctor.name} 선생님</h2>
            <p className="my-hospital">{doctor.hospital}</p>

            <div className="my-row"><span>예약 일시</span><strong>{item.date} {item.time}</strong></div>
            <div className="my-row">
              <span>진행 상태</span>
              <strong><span className={`my-status ${done ? "done" : ""}`}>{done ? "결과 도착" : "의사 검토 중"}</span></strong>
            </div>
            <div className="my-row"><span>선택 증상</span><strong>{item.symptoms.join(", ") || "-"}</strong></div>

            <div className="my-row"><span>올린 사진</span><strong>{item.photoUrls.length}장</strong></div>
            <div className="my-photos">
              {item.photoUrls.map((photo) => <img key={photo.label} src={photo.url} alt={`내가 올린 사진: ${photo.label}`} />)}
            </div>

            {done ? (
              <section className="my-opinion" aria-label="의사 소견">
                <h3>의사 소견</h3>
                {item.diagnosis && <p>검토 내용: {item.diagnosis}</p>}
                {item.opinion && <p>의사 소견: {item.opinion}</p>}
                {item.visitRequired && <p>내원 안내: {item.visitMessage || "병원 방문이 필요해요."}</p>}
              </section>
            ) : (
              <p className="my-waiting">{doctor.name} 선생님이 사진과 증상을 확인하고 있어요. 결과가 오면 여기에 표시돼요.</p>
            )}
          </article>
        );
      })}
    </main>
  );
}

export default MyReservations;
