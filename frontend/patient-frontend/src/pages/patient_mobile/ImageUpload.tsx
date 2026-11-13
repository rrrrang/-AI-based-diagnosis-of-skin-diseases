/**
 * 환자 피부 사진 등록 및 증상 선택 화면
 * - 정면 사진 1장·근접 사진 1장 필수 + 추가 근접 사진 1장 선택 (총 2~3장)
 * - 사진 촬영 / 갤러리 등록 / 미리보기 / 삭제
 * - 증상 복수 선택 및 증상 발생 시점 입력
 * - PatientInfo로 사진과 증상 데이터 전달
 * ※ 사진 품질 안내는 현재 시연용 문구이며 자동 판별 모델은 미연결
 */

import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, Camera,
  Image as ImageIcon, X, Plus,
  AlertTriangle, CheckCircle2,
  Sun, Waves, Zap, Droplet, CircleDot, Activity,
} from "lucide-react";
import "../../css/Patient.css";

const symptomOptions = [
  { id: "redness", label: "붉어짐", Icon: Sun },
  { id: "itching", label: "가려움", Icon: Waves },
  { id: "stinging", label: "따가움", Icon: Zap },
  { id: "dryness", label: "건조함", Icon: Droplet },
  { id: "scaling", label: "각질", Icon: CircleDot },
  { id: "trouble", label: "트러블", Icon: Activity },
];

const durationOptions = [
  "1일 이내", "1~3일", "4~7일", "1~4주", "1개월 이상", "잘 모르겠음",
];

// 이전 화면에서 돌아왔을 때 입력값을 복원하기 위한 데이터 형태
interface UploadState {
  imageFile?: File | null;
  imageFiles?: (File | null)[];
  symptoms?: string[];
  duration?: string;
}

const SLOT_LABELS = ["정면", "부위 1", "부위 2"] as const;

export default function ImageUpload() {
  const navigate = useNavigate();
  const location = useLocation();
  const previous = (location.state ?? {}) as UploadState;

  // 슬롯 0 = 얼굴 정면, 슬롯 1~2 = 피부질환 부위 확대
  const [imageFiles, setImageFiles] = useState<(File | null)[]>(() => {
    if (previous.imageFiles) {
      return [0, 1, 2].map((index) => previous.imageFiles?.[index] ?? null);
    }
    return [previous.imageFile ?? null, null, null];
  });
  const [previews, setPreviews] = useState<(string | null)[]>([null, null, null]);
  const [targetSlot, setTargetSlot] = useState(0);
  const [selectedSymptoms, setSelectedSymptoms] = useState<string[]>(() =>
    symptomOptions.filter((item) => previous.symptoms?.includes(item.label)).map((item) => item.id)
  );
  const [duration, setDuration] = useState(previous.duration ?? "");
  const [errorMessage, setErrorMessage] = useState("");

  const cameraInputRef = useRef<HTMLInputElement>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);

  // 각 파일의 브라우저 미리보기 URL 생성 및 정리
  useEffect(() => {
    const urls = imageFiles.map((file) => file ? URL.createObjectURL(file) : null);
    setPreviews(urls);
    return () => urls.forEach((url) => { if (url) URL.revokeObjectURL(url); });
  }, [imageFiles]);

  const uploadedCount = imageFiles.filter(Boolean).length;

  const updateFile = (slotIndex: number, file: File | null) => {
    setImageFiles((current) => current.map((item, index) => index === slotIndex ? file : item));
    setErrorMessage("");
  };

  // 사진 촬영/선택 버튼은 비어 있는 첫 슬롯을 기본 대상으로 사용
  const selectTarget = () => imageFiles.findIndex((file) => file === null) >= 0
    ? imageFiles.findIndex((file) => file === null)
    : targetSlot;

  const openPicker = (mode: "camera" | "gallery", slotIndex = selectTarget()) => {
    setTargetSlot(slotIndex);
    if (mode === "camera") cameraInputRef.current?.click();
    else galleryInputRef.current?.click();
  };

  const handleImageChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // 동일 파일 다시 선택 허용
    if (!file) return;

    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setErrorMessage("JPG, PNG, WEBP 이미지만 등록할 수 있습니다.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setErrorMessage("사진 한 장의 크기는 10MB 이하여야 합니다.");
      return;
    }
    updateFile(targetSlot, file);
  };

  const handleSymptomToggle = (id: string) => {
    setSelectedSymptoms((current) => current.includes(id)
      ? current.filter((value) => value !== id)
      : [...current, id]);
    setErrorMessage("");
  };

  const handleNext = () => {
    if (!imageFiles[0]) {
      setErrorMessage("얼굴 전체가 보이는 정면 사진을 먼저 등록해 주세요.");
      return;
    }
    if (!imageFiles[1]) {
      setErrorMessage("부위 1에 피부질환이 잘 보이는 근접 사진을 등록해 주세요.");
      return;
    }
    if (!selectedSymptoms.length) {
      setErrorMessage("현재 피부 증상을 하나 이상 선택해 주세요.");
      return;
    }
    if (!duration) {
      setErrorMessage("증상 발생 시점을 선택해 주세요.");
      return;
    }

    navigate("/patient/info", {
      state: {
        imageFile: imageFiles[0], // 기존 PatientInfo/PatientResult 호환
        imageFiles,              // 새 3장 데이터
        symptoms: symptomOptions.filter((item) => selectedSymptoms.includes(item.id)).map((item) => item.label),
        duration,
      },
    });
  };

  return (
    <main className="patient-upload-page">
      <section className="patient-upload-card">
        {/* 기존 2단계 진행 헤더 유지: 로고/브랜드명 없음 */}
        <div className="upload-top">
          <button type="button" className="upload-back-button" onClick={() => navigate("/patient")} aria-label="환자 홈으로 이동">
            <ArrowLeft size={24} />
          </button>
          <div className="upload-progress">
            <div className="progress-step active">
              <span className="progress-dot" />
              <span>사진·증상</span>
              </div>
            <div className="progress-step">
              <span className="progress-dot" />
              <span>환자 정보</span>
            </div>
          </div>
          <span className="upload-step-count">1 / 2</span>
        </div>

        {/* 확정한 시안 기준: 사진 등록 영역 */}
        <div className="upload-photo-heading">
          <h1>피부 사진 등록</h1>
          <span className="upload-photo-count">{uploadedCount} / 3장</span>
        </div>
        <p className="upload-photo-description">
          얼굴 전체가 보이는 정면 사진과 부위 1의 근접 사진은 필수입니다. 부위 2는 선택이며, 총 2~3장을 등록해 주세요.
        </p>

        <div className="upload-photo-slots">
          {SLOT_LABELS.map((label, index) => (
            <div className="upload-photo-slot" key={label}>
              <strong>{label}</strong>
              <div className={`upload-photo-frame ${!imageFiles[index] ? "is-empty" : ""}`}>
                {previews[index] ? (
                  <>
                    <img
                      src={previews[index] ?? undefined}
                      alt={index === 0 ? "얼굴 정면 사진 미리보기" : `${label} 피부질환 부위 미리보기`}
                    />
                    <button
                      type="button"
                      className="upload-photo-remove"
                      aria-label={`${label} 사진 삭제`}
                      onClick={() => updateFile(index, null)}
                    ><X size={14} /></button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="upload-photo-add"
                    onClick={() => openPicker("gallery", index)}
                    aria-label={`${label} 사진 추가`}
                  ><Plus size={27} /></button>
                )}
              </div>
              <span className={`upload-photo-badge ${imageFiles[index] ? "is-uploaded" : ""}`}>
                {index === 0 ? "정면 필수" : index === 1 ? "근접 필수" : "추가 근접 선택"}{imageFiles[index] ? " · 등록됨" : ""}
              </span>
            </div>
          ))}
        </div>

        {/* 사진 촬영 또는 갤러리 선택: 다음 빈 슬롯에 추가 */}
        <div className="upload-image-buttons">
          <button type="button" className="upload-camera-button" onClick={() => openPicker("camera")}>
            <Camera size={19} /> 사진 촬영
          </button>
          <button type="button" onClick={() => openPicker("gallery")}>
            <ImageIcon size={19} /> 사진 선택
          </button>
        </div>

        <input ref={cameraInputRef} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={handleImageChange} hidden aria-label="카메라로 사진 촬영" />
        <input ref={galleryInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleImageChange} hidden aria-label="갤러리에서 사진 선택" />

        {/* 자동 블러/근접 판별은 미연결: 안내 문구만 제공 */}
        <div className="upload-photo-warning">
          <AlertTriangle size={17} />
          <span>사진이 흐리다면 다시 촬영해 주세요. <br />너무 가까이 촬영했다면 거리를 조절해 주세요.</span>
        </div> 
        
        {/* 기존 6개 증상 선택 UI 유지 */}
        <div className="upload-symptom-section">
          <div className="upload-section-heading">
            <h2>어떤 증상이 있나요?</h2>
            <span>복수 선택 가능</span>
          </div>
          <div className="upload-symptom-grid">
            {symptomOptions.map((symptom) => {
              const isSelected = selectedSymptoms.includes(symptom.id);
              const SymptomIcon = symptom.Icon;
              return (
                <button key={symptom.id} type="button" aria-pressed={isSelected}
                  className={`upload-symptom-item ${isSelected ? "selected" : ""}`}
                  onClick={() => handleSymptomToggle(symptom.id)}>
                  {isSelected && <CheckCircle2 className="symptom-check-icon" size={20} />}
                  <SymptomIcon size={26} strokeWidth={1.7} />
                  <span>{symptom.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* 기존 증상 발생 시점 드롭다운 유지 */}
        <div className="upload-duration-section">
          <label htmlFor="symptom-duration">증상 발생 시점</label>
          <select id="symptom-duration" value={duration} onChange={(event) => {
            setDuration(event.target.value);
            setErrorMessage("");
          }}>
            <option value="">선택해 주세요.</option>
            {durationOptions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>
        {errorMessage && <p className="upload-error" role="alert">{errorMessage}</p>}

        <button type="button" className="upload-next-button" onClick={handleNext}>다음 <ArrowRight size={20} /></button>
        <footer className="upload-footer">
          <p>교육용 시뮬레이션</p>
          <p>실제 의료 진단·치료가 아닙니다.</p>
        </footer>
      </section>
    </main>
  );
}
