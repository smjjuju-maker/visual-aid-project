"""
oak_reader.py
-------------
OAK-D-Lite 파이프라인 생성 + 장애물 거리/방향 + 점자블록 + 좁은 통로 측정 모듈.

[역할]
  - 카메라 파이프라인 구성 (RGB + Stereo Depth + MobileNet-SSD)
  - 매 프레임마다 실내 관련 장애물의 (라벨, 거리, 방향) 측정
  - 색(노란색) 기반 점자블록 검출 + 시계 방향/걸음 거리 안내용 정보 반환
    + 점자블록 영역의 '끝(가장 위쪽 노란 픽셀)' 거리 → '곧 벗어남' 판단용
  - depth 좌/중/우 분석으로 좁은 통로 판단

[중요 수정 사항]
  - setLeftRightCheck(True): CAM_A 정렬에는 LR Check 필수
  - maxUsbSpeed=HIGH: 노트북 USB 환경 안정화
  - RGB preview(300x300)를 점자블록 색 검출에도 같이 사용 (선택지 A)
"""

import os
from collections import defaultdict, deque
import numpy as np
import cv2
import depthai as dai

# ── 모델 파일 경로 (로컬) ─────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BLOB_PATH = os.path.join(SCRIPT_DIR, "models",
                         "mobilenet-ssd_openvino_2021.4_6shave.blob")

# ── MobileNet-SSD 클래스 라벨 ─────────────────────────
LABELS = [
    "background", "aeroplane", "bicycle", "bird", "boat",
    "bottle", "bus", "car", "cat", "chair",
    "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train",
    "tvmonitor"
]

# 실내 보행에 의미 있는 클래스만 (영문 → 한글)
INDOOR_RELEVANT = {
    "person":      "사람",
    "chair":       "의자",
    "sofa":        "소파",
    "diningtable": "식탁",
    "tvmonitor":   "모니터",
    "pottedplant": "화분",
    "cat":         "고양이",
    "dog":         "강아지",
    "bottle":      "병",
}

# ── 설정값 ────────────────────────────────────────────
TARGET_FPS = 10
CONFIDENCE_THRESHOLD = 0.5
SMOOTHING_WINDOW = 5

# ── 회피 판단 기준 ────────────────────────────────────
CLEAR_THRESHOLD_M = 1.5
SIDE_DIFF_THRESHOLD_M = 0.8

# ── 좁은 통로 판단 기준 ───────────────────────────────
#   narrow_side_m: 양옆이 이 거리 이내면 "벽/책상이 가깝다".
#     main에서 어깨너비 × 배수로 계산해 넘김 (없으면 이 기본값).
#   NARROW_FRONT_MARGIN_M: 정면이 양옆보다 이만큼 이상 멀어야 "통로"로 인정.
#     실측(양옆 0.9, 정면 1.73 → 차이 0.8 이상)을 근거로 0.4m로 시작.
NARROW_SIDE_DEFAULT_M = 1.2
NARROW_FRONT_MARGIN_M = 0.4

# ── 점자블록(노란색) 색 검출 기준 ─────────────────────
#   채도(S) 하한을 높여 아이보리/베이지(연한 저채도) 오검출을 줄인다.
#   실제 점자블록은 채도 높은 '쨍한 노랑'이라 살아남고,
#   아이보리 책상처럼 흰끼 도는 연한 색은 걸러진다.
#   ※ 진짜 점자블록 앞에서 최종 튜닝 필요 (지금은 오검출 억제 위주)
YELLOW_HSV_LOWER = np.array([20, 130, 90])
YELLOW_HSV_UPPER = np.array([35, 255, 255])
TACTILE_RATIO_THRESHOLD = 0.05          # 화면 하단 ROI 중 노란 픽셀 비율
TACTILE_ROI_Y_START_RATIO = 0.5         # ROI: 화면 세로 아래쪽 절반


def create_pipeline():
    """AI Spatial Detection 파이프라인 생성. RGB preview도 외부로 출력."""
    pipeline = dai.Pipeline()

    cam_rgb = pipeline.create(dai.node.ColorCamera)
    cam_rgb.setPreviewSize(300, 300)
    cam_rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam_rgb.setInterleaved(False)
    cam_rgb.setFps(TARGET_FPS)
    cam_rgb.setBoardSocket(dai.CameraBoardSocket.CAM_A)

    mono_left = pipeline.create(dai.node.MonoCamera)
    mono_left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    mono_left.setCamera("left")
    mono_left.setFps(TARGET_FPS)

    mono_right = pipeline.create(dai.node.MonoCamera)
    mono_right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    mono_right.setCamera("right")
    mono_right.setFps(TARGET_FPS)

    stereo = pipeline.create(dai.node.StereoDepth)
    stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.DEFAULT)
    stereo.initialConfig.setConfidenceThreshold(200)
    stereo.initialConfig.setMedianFilter(dai.MedianFilter.MEDIAN_OFF)
    stereo.setLeftRightCheck(True)
    stereo.setSubpixel(False)
    stereo.setExtendedDisparity(False)
    stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)

    mono_left.out.link(stereo.left)
    mono_right.out.link(stereo.right)

    spatial_nn = pipeline.create(dai.node.MobileNetSpatialDetectionNetwork)
    spatial_nn.setBlobPath(BLOB_PATH)
    spatial_nn.setConfidenceThreshold(CONFIDENCE_THRESHOLD)
    spatial_nn.input.setBlocking(False)
    spatial_nn.setBoundingBoxScaleFactor(0.5)
    spatial_nn.setDepthLowerThreshold(200)
    spatial_nn.setDepthUpperThreshold(5000)

    cam_rgb.preview.link(spatial_nn.input)
    stereo.depth.link(spatial_nn.inputDepth)

    xout_nn = pipeline.create(dai.node.XLinkOut)
    xout_nn.setStreamName("detections")
    spatial_nn.out.link(xout_nn.input)

    xout_depth = pipeline.create(dai.node.XLinkOut)
    xout_depth.setStreamName("depth")
    spatial_nn.passthroughDepth.link(xout_depth.input)

    xout_rgb = pipeline.create(dai.node.XLinkOut)
    xout_rgb.setStreamName("rgb")
    cam_rgb.preview.link(xout_rgb.input)

    return pipeline


def describe_direction(x_mm, front_half_width_m=0.3):
    """좌우 좌표(mm) → 한글 방향.

    front_half_width_m: '정면'으로 볼 좌우 반폭(m).
      중심에서 이 거리 안에 있으면 정면(=사용자 진행 경로 상).
      어깨너비+여유의 절반을 넘겨주면 실제 통과 경로와 맞는다.
    """
    x_m = x_mm / 1000.0
    if x_m < -front_half_width_m:
        return "왼쪽"
    elif x_m > front_half_width_m:
        return "오른쪽"
    else:
        return "정면"


def describe_clock_direction(x_norm):
    """화면 가로 위치(0=왼끝, 1=오른끝) → 시계 방향(10시~2시)."""
    if x_norm < 0.2:
        return "10시"
    elif x_norm < 0.4:
        return "11시"
    elif x_norm < 0.6:
        return "12시"
    elif x_norm < 0.8:
        return "1시"
    else:
        return "2시"


class OakReader:
    """OAK-D-Lite 장애물/점자블록/통로 감지를 캡슐화."""

    def __init__(self):
        if not os.path.exists(BLOB_PATH):
            raise FileNotFoundError(f"모델 파일 없음: {BLOB_PATH}")
        self.pipeline = create_pipeline()
        self.device = None
        self.det_queue = None
        self.depth_queue = None
        self.rgb_queue = None
        self._latest_depth = None
        self._latest_rgb = None
        self._distance_history = defaultdict(lambda: deque(maxlen=SMOOTHING_WINDOW))

    def __enter__(self):
        self.device = dai.Device(self.pipeline, maxUsbSpeed=dai.UsbSpeed.HIGH)
        self.det_queue = self.device.getOutputQueue(
            name="detections", maxSize=4, blocking=False)
        self.depth_queue = self.device.getOutputQueue(
            name="depth", maxSize=4, blocking=False)
        self.rgb_queue = self.device.getOutputQueue(
            name="rgb", maxSize=4, blocking=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.device is not None:
            self.device.close()

    def get_usb_speed(self):
        try:
            return self.device.getUsbSpeed()
        except Exception:
            return None

    def get_obstacles(self, front_half_width_m=0.3):
        """현재 프레임의 실내 관련 장애물 목록.
        front_half_width_m: '정면' 판정 좌우 반폭(m). main에서 어깨너비 기반으로 넘김.
        """
        in_det = self.det_queue.tryGet()
        if in_det is None:
            return None

        obstacles = []
        seen_labels = set()
        for det in in_det.detections:
            label_en = LABELS[det.label] if det.label < len(LABELS) else "unknown"
            if label_en not in INDOOR_RELEVANT:
                continue

            x_mm = det.spatialCoordinates.x
            z_mm = det.spatialCoordinates.z
            distance_m = z_mm / 1000.0
            if distance_m <= 0.1:
                continue

            label_ko = INDOOR_RELEVANT[label_en]
            seen_labels.add(label_ko)

            history = self._distance_history[label_ko]
            history.append(distance_m)
            smoothed_m = sum(history) / len(history)

            obstacles.append({
                "label": label_ko,
                "distance_m": smoothed_m,
                "raw_distance_m": distance_m,
                "direction": describe_direction(x_mm, front_half_width_m),
                "x_mm": x_mm,
                "confidence": det.confidence,
            })

        for label_ko in list(self._distance_history.keys()):
            if label_ko not in seen_labels:
                self._distance_history[label_ko].clear()

        return obstacles

    def _update_depth(self):
        in_depth = self.depth_queue.tryGet()
        if in_depth is not None:
            self._latest_depth = in_depth.getFrame()

    def _update_rgb(self):
        in_rgb = self.rgb_queue.tryGet()
        if in_rgb is not None:
            self._latest_rgb = in_rgb.getCvFrame()

    def get_open_direction(self, narrow_side_m=NARROW_SIDE_DEFAULT_M):
        """depth 맵을 좌/중/우로 3등분해 회피 + 좁은 통로 판단.
        반환: (situation, info)
          situation: "right"/"left"/"either"/"blocked"/"narrow"
          info: {"left_m":.., "center_m":.., "right_m":..}
        """
        self._update_depth()
        if self._latest_depth is None:
            return None, None

        depth = self._latest_depth
        h, w = depth.shape
        y0, y1 = int(h * 0.2), int(h * 0.8)
        band = depth[y0:y1, :]

        third = w // 3
        left = band[:, :third]
        center = band[:, third:2 * third]
        right = band[:, 2 * third:]

        def region_clearance(region):
            valid = region[region > 0]
            if valid.size == 0:
                return 0.0
            return float(np.percentile(valid, 10)) / 1000.0

        left_m = region_clearance(left)
        center_m = region_clearance(center)
        right_m = region_clearance(right)
        info = {"left_m": left_m, "center_m": center_m, "right_m": right_m}

        center_open = center_m >= CLEAR_THRESHOLD_M

        # ── 좁은 통로 판정 (blocked보다 우선) ──
        #   실측 데이터 기준: 책상 사이 통로 = 양옆 0.85~1.2m, 정면 1.65~1.78m.
        #   조건: 양옆이 둘 다 narrow_side_m 이내(벽/책상이 가까움)
        #         + 정면이 양옆보다 확실히 멀다(앞은 트임).
        #   "정면이 양옆 최댓값보다 NARROW_FRONT_MARGIN_M 이상 멀다"로 본다.
        side_max = max(left_m, right_m)
        front_clear_vs_side = (center_m - side_max) >= NARROW_FRONT_MARGIN_M
        both_sides_close = (left_m < narrow_side_m and right_m < narrow_side_m
                            and left_m > 0 and right_m > 0)
        if both_sides_close and front_clear_vs_side:
            return "narrow", info

        left_open = left_m >= CLEAR_THRESHOLD_M
        right_open = right_m >= CLEAR_THRESHOLD_M
        diff = abs(right_m - left_m)

        if not left_open and not right_open:
            situation = "blocked"
        elif left_open and right_open:
            if diff < SIDE_DIFF_THRESHOLD_M:
                situation = "either"
            else:
                situation = "right" if right_m > left_m else "left"
        else:
            situation = "right" if right_open else "left"

        return situation, info

    def _depth_at(self, rgb_x, rgb_y, rgb_h, rgb_w, patch_radius=5):
        """RGB 좌표를 depth 좌표로 환산해 중앙값 거리(m) 추정. 실패 시 None."""
        if self._latest_depth is None:
            return None
        dh, dw = self._latest_depth.shape
        px = int(rgb_x / rgb_w * dw)
        py = int(rgb_y / rgb_h * dh)
        x0, x1 = max(0, px - patch_radius), min(dw, px + patch_radius + 1)
        y0, y1 = max(0, py - patch_radius), min(dh, py + patch_radius + 1)
        patch = self._latest_depth[y0:y1, x0:x1]
        valid = patch[patch > 0]
        if valid.size == 0:
            return None
        return float(np.median(valid)) / 1000.0

    def detect_tactile_paving(self):
        """
        화면 하단 ROI에서 노란색으로 점자블록 유무/방향/거리/끝거리 검출.

        반환: {
            "present": bool,                  # 점자블록 존재 여부 (이번 프레임)
            "clock_direction": "11시" 등 or None,  # 무게중심의 시계 방향
            "distance_m": float or None,      # 무게중심까지 거리(m)
            "far_end_distance_m": float or None,  # 노란 영역의 '먼 끝' 거리(m)
                                              # 작을수록 곧 벗어남에 가까움
                                              # → 이게 N걸음 이내면 "곧 벗어남"
            "ratio": float                    # 노란 픽셀 비율 (디버그용)
        }
        RGB가 아직 없으면 None.

        [far_end_distance_m 의미]
          노란 영역의 '가장 위쪽 픽셀' = 카메라에서 가장 먼 점자블록 지점.
          그 지점의 depth가 점자블록이 끝나는 지점까지의 거리.
          사용자가 그 거리만큼 걸어가면 점자블록 위에서 벗어남.
        """
        self._update_rgb()
        self._update_depth()
        if self._latest_rgb is None:
            return None

        frame = self._latest_rgb
        h, w = frame.shape[:2]
        y_start = int(h * TACTILE_ROI_Y_START_RATIO)
        roi = frame[y_start:, :]

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, YELLOW_HSV_LOWER, YELLOW_HSV_UPPER)

        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        ratio = float(cv2.countNonZero(mask)) / mask.size
        present = ratio >= TACTILE_RATIO_THRESHOLD

        if not present:
            return {"present": False, "clock_direction": None,
                    "distance_m": None, "far_end_distance_m": None,
                    "ratio": ratio}

        ys, xs = np.where(mask > 0)
        cx_roi = float(xs.mean())
        cy_roi = float(ys.mean())
        x_norm = cx_roi / mask.shape[1]
        clock = describe_clock_direction(x_norm)

        center_full_x = cx_roi
        center_full_y = cy_roi + y_start
        distance_m = self._depth_at(center_full_x, center_full_y, h, w)

        # ── '먼 끝' 찾기: 노란 마스크에서 가장 위쪽(y가 작은) 행 ──
        top_y_roi = int(ys.min())
        xs_at_top = xs[ys == top_y_roi]
        top_x_roi = float(np.median(xs_at_top))
        far_full_x = top_x_roi
        far_full_y = top_y_roi + y_start
        far_end_distance_m = self._depth_at(far_full_x, far_full_y, h, w)

        return {"present": True, "clock_direction": clock,
                "distance_m": distance_m,
                "far_end_distance_m": far_end_distance_m,
                "ratio": ratio}