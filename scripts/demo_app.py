import gradio as gr

from inference_core import Predictor, decision_text

P = Predictor()

INTRO = """# 피부 질환 분류 데모 (연구·교육용)
**의학적 진단이 아닙니다.** 이 모델은 공개 데이터셋의 측면(병변 확대) 사진 5,400장으로 학습한 실험용 분류기입니다.

사용 안내
- **병변 부위를 가까이서 선명하게 찍은 사진**을 올려 주세요. 얼굴 전체가 나온 사진은 학습·검증하지 않았습니다.
- 분류 대상은 건선, 아토피, 여드름, 정상, 주사, 지루 **6가지뿐**입니다. 다른 질환이나 피부가 아닌 사진도 6개 중 하나로 답할 수 있습니다.
- 메신저 전송본처럼 **압축이 심한 사진은 정확도가 떨어질 수 있습니다.**
- 색 지도(Grad-CAM)는 모델이 판단에 많이 반영한 영역을 보여 줄 뿐, 병변의 위치를 뜻하지 않습니다.
"""


def run(img, thr, show_cam):
    if img is None:
        return None, "사진을 올려 주세요.", None
    r = P.predict(img, threshold=thr, with_cam=show_cam)
    label = {n: float(p) for n, p in zip(r["names"], r["probs"])}
    md = decision_text(r) + "".join(f"\n\n주의: {w}" for w in r["warnings"])
    return label, md, r["overlay"]


with gr.Blocks(title="피부 질환 분류 데모") as demo:
    gr.Markdown(INTRO)
    with gr.Row():
        with gr.Column():
            inp = gr.Image(type="pil", label="병변 부위 사진")
            thr = gr.Slider(0.30, 0.95, value=P.threshold, step=0.01, label="판단 불가 기준 (최고 확률이 이보다 낮으면 판단 불가)")
            cam = gr.Checkbox(value=True, label="설명 시각화(Grad-CAM) 표시")
            btn = gr.Button("분석", variant="primary")
        with gr.Column():
            lab = gr.Label(num_top_classes=6, label="클래스별 확률")
            msg = gr.Markdown()
            out_img = gr.Image(label="Grad-CAM (예측 클래스 기준)")
    btn.click(run, [inp, thr, cam], [lab, msg, out_img])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", share=False)   # 건강 정보 사진이므로 share=True 금지