"""
view_camera.py
--------------
테스트용 카메라 뷰어. OAK-D-Lite가 '무엇을 보고 어떻게 잡는지'를
눈으로 확인하기 위한 독립 실행 스크립트.

main.py / oak_reader.py 의 동작에는 전혀 영향을 주지 않는다.
(oak_reader 의 파이프라인·라벨 정의만 재사용한다.)

[보여주는 것]
  - RGB 창: 검출된 장애물의 박스 + 한글 라벨 + 거리(m) + 방향(정면/좌/우)
            + 통로 좌/중/우 3분할 경계선과 각 구역 대표거리
  - Depth 창: 거리 컬러맵 (가까움=빨강 계열, 멀음=파랑 계열)

[실행]
  (capstone 활성화 상태에서)
  python src/view_camera.py

  q 또는 ESC 키를 누르면 종료.

[주의]
  - 한글 라벨이 깨져 보이면(□□□) OpenCV 기본 폰트가 한글을 못 그리는 것이라,
    영문 라벨로 보고 싶으면 USE_KOREAN_LABEL = False 로 바꾼다.
"""

import numpy as np
import cv2
import depthai as dai

from oak_reader import (
    create_pipeline,
    LABELS,
    INDOOR_RELEVANT,
    CLEAR_THRESHOLD_M,
)

# 한글 라벨 표시 시도 여부 (깨지면 False 로)
USE_KOREAN_LABEL = False

# 영문 라벨 (한글이 깨질 때 대체용)
INDOOR_RELEVANT_EN = {
    "person": "person", "chair": "chair", "sofa": "sofa",
    "diningtable": "table", "tvmonitor": "monitor",
    "pottedplant": "plant", "cat": "cat", "dog": "dog", "bottle": "bottle",
}


def region_clearance(region):
    """oak_reader 와 동일한 방식으로 한 구역의 대표 거리(m) 계산."""
    valid = region[(region > 300) & (region < 10000)]
    if valid.size < region.size * 0.05:
        return 0.0
    return float(np.percentile(valid, 20)) / 1000.0


def main():
    pipeline = create_pipeline()
    print("[연결] OAK-D-Lite 시작 중... (창이 뜨면 q 또는 ESC 로 종료)")

    with dai.Device(pipeline, maxUsbSpeed=dai.UsbSpeed.HIGH) as device:
        q_det = device.getOutputQueue("detections", maxSize=4, blocking=False)
        q_depth = device.getOutputQueue("depth", maxSize=4, blocking=False)
        q_rgb = device.getOutputQueue("rgb", maxSize=4, blocking=False)

        latest_depth = None

        while True:
            in_rgb = q_rgb.tryGet()
            in_det = q_det.tryGet()
            in_depth = q_depth.tryGet()

            if in_depth is not None:
                latest_depth = in_depth.getFrame()

            # ── Depth 창 ──
            if latest_depth is not None:
                d = latest_depth.copy()
                # 0~6m 범위를 컬러로 (가까울수록 빨강)
                d_clip = np.clip(d, 0, 6000)
                d_norm = (d_clip / 6000.0 * 255).astype(np.uint8)
                d_color = cv2.applyColorMap(255 - d_norm, cv2.COLORMAP_JET)
                d_color[d == 0] = (0, 0, 0)   # 측정 실패는 검정
                cv2.imshow("Depth", d_color)

            # ── RGB 창 (검출 박스 + 통로 분할) ──
            if in_rgb is not None:
                frame = in_rgb.getCvFrame()
                h, w = frame.shape[:2]

                # 통로 좌/중/우 3분할 경계선
                third = w // 3
                cv2.line(frame, (third, 0), (third, h), (80, 80, 80), 1)
                cv2.line(frame, (2 * third, 0), (2 * third, h), (80, 80, 80), 1)

                # 각 구역 대표 거리 (depth 기준, oak_reader 와 동일 밴드)
                if latest_depth is not None:
                    dh, dw = latest_depth.shape
                    y0, y1 = int(dh * 0.2), int(dh * 0.8)
                    band = latest_depth[y0:y1, :]
                    dt = dw // 3
                    regions = {
                        "L": band[:, :dt],
                        "C": band[:, dt:2 * dt],
                        "R": band[:, 2 * dt:],
                    }
                    xpos = {"L": 10, "C": third + 10, "R": 2 * third + 10}
                    for name, reg in regions.items():
                        cm = region_clearance(reg)
                        open_ = cm >= CLEAR_THRESHOLD_M
                        color = (0, 200, 0) if open_ else (0, 0, 255)
                        txt = f"{name}:{cm:.2f}m" if cm > 0 else f"{name}:--"
                        cv2.putText(frame, txt, (xpos[name], 25),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

                # 검출 박스
                if in_det is not None:
                    for det in in_det.detections:
                        label_en = LABELS[det.label] if det.label < len(LABELS) else "?"
                        if label_en not in INDOOR_RELEVANT:
                            continue

                        x1 = int(det.xmin * w)
                        y1b = int(det.ymin * h)
                        x2 = int(det.xmax * w)
                        y2 = int(det.ymax * h)

                        z_m = det.spatialCoordinates.z / 1000.0
                        x_mm = det.spatialCoordinates.x
                        # 방향 (정면 반폭 0.3m 기준, 디버그용 간단 판정)
                        x_m = x_mm / 1000.0
                        if x_m < -0.3:
                            dir_txt = "L"
                        elif x_m > 0.3:
                            dir_txt = "R"
                        else:
                            dir_txt = "F"   # Front(정면)

                        if USE_KOREAN_LABEL:
                            label = INDOOR_RELEVANT[label_en]
                        else:
                            label = INDOOR_RELEVANT_EN.get(label_en, label_en)

                        cv2.rectangle(frame, (x1, y1b), (x2, y2), (0, 255, 255), 2)
                        cap = f"{label} {z_m:.2f}m [{dir_txt}]"
                        cv2.putText(frame, cap, (x1, max(y1b - 8, 15)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                    (0, 255, 255), 2)

                cv2.imshow("RGB + Detections", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:   # q 또는 ESC
                break

        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()