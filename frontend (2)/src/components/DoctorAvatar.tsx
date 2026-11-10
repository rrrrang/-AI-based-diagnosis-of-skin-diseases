
/**
 * 파일명: DoctorAvatar.tsx
 *
 * 역할:
 * 가상 의사별 프로필 PNG 이미지를 표시하는 컴포넌트
 */

// 의사별 프로필 종류
type AvatarType = "long" | "short" | "bob";

// 컴포넌트에 전달할 속성
interface DoctorAvatarProps {
  avatar: AvatarType; // 의사 구분
  size?: number;      // 이미지 크기
}

// 프로필 이미지 경로
const avatarImages: Record<AvatarType, string> = {
  long: "/doctors/doctor1.png",  // 김서연
  short: "/doctors/doctor2.png", // 박지훈
  bob: "/doctors/doctor3.png",   // 이다은
};

export default function DoctorAvatar({
  avatar,
  size = 92,
}: DoctorAvatarProps) {
  return (
    <img
      // 의사별 이미지 선택
      src={avatarImages[avatar]}

      // 접근성을 위한 이미지 설명
      alt="가상 의사 프로필 일러스트"

      // 화면 표시 크기 및 스타일
      style={{
        width: size,
        height: size * 1.1,
        objectFit: "cover",
        borderRadius: "14px",
        flexShrink: 0,
        display: "block",
      }}
    />
  );
}
