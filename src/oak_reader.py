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
#   ※ 화분/고양이/강아지/병은 제외(사용자 요청). 미확인 물체는 depth 기반으로
#     "장애물"이라고 안내하므로, 여기 없는 물체도 충돌 경고는 정상 작동한다.
INDOOR_RELEVANT = {
    "person":      "사람",
    "chair":       "의자",
    "sofa":        "소파",
    "diningtable": "식탁",
    "tvmonitor":   "모니터",
}

# ── 설정값 ────────────────────────────────────────────
TARGET_FPS = 15
CONFIDENCE_THRESHOLD = 0.5
SMOOTHING_WINDOW = 3

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
    stereo.setSubpixel(True)    # 먼 거리 disparity를 소수 단위로 추정 → 4~5m 양자화(계단현상) 완화
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
        # 좌/중/우 거리 이동평균용 + 방향(situation) 다수결용 버퍼
        self._clear_hist = {
            "left":   deque(maxlen=SMOOTHING_WINDOW),
            "center": deque(maxlen=SMOOTHING_WINDOW),
            "right":  deque(maxlen=SMOOTHING_WINDOW),
        }
        self._situation_hist = deque(maxlen=SMOOTHING_WINDOW)

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
          situation: "right"/"left"/"either"/"narrow"/"blocked"
            - right/left/either: 좌우로 회피 가능
            - narrow: 좌우는 가깝지만(벽/책상) 정면은 트임 → 좁은 통로, 직진 주의
                      (※ 좌우 둘 다 막혀도 정면이 열려 있으면 막다른 길이 아니라
                          좁은 통로로 본다 — 직진 경로는 살아있으므로)
            - blocked: 좌·중·우 모두 막힘 = 진짜 막다른 길
          info: {"left_m":.., "center_m":.., "right_m":..}

        [안정화 3종]
          ① region_clearance: 0.3m 미만 근접노이즈·측정실패·10m 초과 제외
          ② 좌/중/우 거리를 SMOOTHING_WINDOW 프레임 이동평균
          ③ 최종 situation을 최근 프레임 다수결로 확정 (단일 프레임 깜빡임 제거)
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
            # 0.3m 미만(근접 노이즈)·0(측정 실패)·10m 초과 제외
            valid = region[(region > 300) & (region < 10000)]
            if valid.size < region.size * 0.05:   # 유효 픽셀 5% 미만 → 신뢰 불가
                return 0.0
            return float(np.percentile(valid, 20)) / 1000.0   # 10→20%로 노이즈 완화

        # ① 이번 프레임 raw 값
        raw_l = region_clearance(left)
        raw_c = region_clearance(center)
        raw_r = region_clearance(right)

        # ② 프레임 간 이동평균 (0=측정실패는 평균에서 제외해 급격한 0 방지)
        for key, val in (("left", raw_l), ("center", raw_c), ("right", raw_r)):
            if val > 0:
                self._clear_hist[key].append(val)

        def _avg(key):
            hh = self._clear_hist[key]
            return sum(hh) / len(hh) if hh else 0.0

        left_m, center_m, right_m = _avg("left"), _avg("center"), _avg("right")
        info = {"left_m": left_m, "center_m": center_m, "right_m": right_m}

        # 세 구역 모두 측정 실패(0) → 워밍업·전면 무효 프레임.
        # blocked로 단정하지 말고 직전 확정값 유지(버퍼 비었으면 either).
        if raw_l == 0 and raw_c == 0 and raw_r == 0:
            if self._situation_hist:
                situation = max(set(self._situation_hist),
                                key=self._situation_hist.count)
            else:
                situation = "either"
            return situation, info

        left_open = left_m >= CLEAR_THRESHOLD_M
        right_open = right_m >= CLEAR_THRESHOLD_M
        center_open = center_m >= CLEAR_THRESHOLD_M

        # ── 좁은 통로 판정 (blocked보다 우선) ──
        #   (A) 실측 기준: 양옆이 둘 다 narrow_side_m 이내(벽/책상) +
        #       정면이 양옆 최댓값보다 NARROW_FRONT_MARGIN_M 이상 멀다(앞은 트임).
        #   (B) 좌우가 둘 다 안 열려 있어도(<CLEAR_THRESHOLD_M) 정면이 열려 있으면
        #       막다른 길이 아니라 좁은 통로로 본다. (직진 경로가 살아있음)
        side_max = max(left_m, right_m)
        front_clear_vs_side = (center_m - side_max) >= NARROW_FRONT_MARGIN_M
        both_sides_close = (left_m < narrow_side_m and right_m < narrow_side_m
                            and left_m > 0 and right_m > 0)
        narrow_by_margin = both_sides_close and front_clear_vs_side
        narrow_by_center = (not left_open and not right_open and center_open)

        diff = abs(right_m - left_m)
        if narrow_by_margin or narrow_by_center:
            cur = "narrow"
        elif left_open and right_open:
            cur = "either" if diff < SIDE_DIFF_THRESHOLD_M else \
                  ("right" if right_m > left_m else "left")
        elif left_open or right_open:
            cur = "right" if right_open else "left"
        else:
            cur = "blocked"   # 좌·중·우 모두 막힘 = 진짜 막다른 길

        # ③ 최근 프레임 다수결로 최종 확정 (한 프레임 튀어도 안 흔들림)
        self._situation_hist.append(cur)
        situation = max(set(self._situation_hist), key=self._situation_hist.count)
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