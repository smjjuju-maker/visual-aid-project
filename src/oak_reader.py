"""
oak_reader.py
-------------
OAK-D-Lite 파이프라인 생성 + 장애물 거리/방향 측정 모듈.

[역할]
  - 카메라 파이프라인 구성 (RGB + Stereo Depth + MobileNet-SSD)
  - 매 프레임마다 실내 관련 장애물의 (라벨, 거리, 방향)을 측정해서 반환

[중요 수정 사항]
  - setLeftRightCheck(True): CAM_A 정렬에는 LR Check 필수 (이전 크래시 원인 해결)
  - maxUsbSpeed=HIGH: 노트북 USB 환경 안정화
"""

import os
from collections import defaultdict, deque
import numpy as np
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
TARGET_FPS = 10               # USB 2.0 환경 안정화
CONFIDENCE_THRESHOLD = 0.5    # 객체 신뢰도 하한
SMOOTHING_WINDOW = 5          # 거리 이동 평균에 쓸 최근 프레임 수

# ── 회피 판단 기준 ────────────────────────────────────
CLEAR_THRESHOLD_M = 1.5       # 이 거리 이상이면 그 방향은 '통과 가능(트임)'
SIDE_DIFF_THRESHOLD_M = 0.8   # 좌우 차이가 이 값 미만이면 '양쪽 비슷'으로 간주


def create_pipeline():
    """AI Spatial Detection 파이프라인 생성."""
    pipeline = dai.Pipeline()

    # ── 컬러 카메라 (AI 입력용) ──
    cam_rgb = pipeline.create(dai.node.ColorCamera)
    cam_rgb.setPreviewSize(300, 300)
    cam_rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam_rgb.setInterleaved(False)
    cam_rgb.setFps(TARGET_FPS)
    cam_rgb.setBoardSocket(dai.CameraBoardSocket.CAM_A)

    # ── 모노 카메라 (depth용) ──
    mono_left = pipeline.create(dai.node.MonoCamera)
    mono_left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    mono_left.setCamera("left")
    mono_left.setFps(TARGET_FPS)

    mono_right = pipeline.create(dai.node.MonoCamera)
    mono_right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    mono_right.setCamera("right")
    mono_right.setFps(TARGET_FPS)

    # ── Stereo Depth ──
    stereo = pipeline.create(dai.node.StereoDepth)
    stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.DEFAULT)
    stereo.initialConfig.setConfidenceThreshold(200)
    stereo.initialConfig.setMedianFilter(dai.MedianFilter.MEDIAN_OFF)
    stereo.setLeftRightCheck(True)        # ★ CAM_A 정렬에는 필수 (False면 크래시)
    stereo.setSubpixel(False)
    stereo.setExtendedDisparity(False)
    stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)

    mono_left.out.link(stereo.left)
    mono_right.out.link(stereo.right)

    # ── MobileNet-SSD Spatial Detection ──
    spatial_nn = pipeline.create(dai.node.MobileNetSpatialDetectionNetwork)
    spatial_nn.setBlobPath(BLOB_PATH)
    spatial_nn.setConfidenceThreshold(CONFIDENCE_THRESHOLD)
    spatial_nn.input.setBlocking(False)
    spatial_nn.setBoundingBoxScaleFactor(0.5)
    spatial_nn.setDepthLowerThreshold(200)     # 20cm
    spatial_nn.setDepthUpperThreshold(5000)    # 5m

    cam_rgb.preview.link(spatial_nn.input)
    stereo.depth.link(spatial_nn.inputDepth)

    # ── 출력 ──
    xout_nn = pipeline.create(dai.node.XLinkOut)
    xout_nn.setStreamName("detections")
    spatial_nn.out.link(xout_nn.input)

    # depth 맵도 출력 (좌/중/우 개방도 분석용)
    # spatial_nn이 통과시킨 depth는 detection과 정렬되어 있음
    xout_depth = pipeline.create(dai.node.XLinkOut)
    xout_depth.setStreamName("depth")
    spatial_nn.passthroughDepth.link(xout_depth.input)

    return pipeline


def describe_direction(x_mm):
    """좌우 좌표(mm) → 한글 방향."""
    x_m = x_mm / 1000.0
    if x_m < -0.3:
        return "왼쪽"
    elif x_m > 0.3:
        return "오른쪽"
    else:
        return "정면"


class OakReader:
    """OAK-D-Lite 장애물 감지를 캡슐화한 클래스.

    사용 예:
        with OakReader() as reader:
            while True:
                obstacles = reader.get_obstacles()
                ...
    """

    def __init__(self):
        if not os.path.exists(BLOB_PATH):
            raise FileNotFoundError(f"모델 파일 없음: {BLOB_PATH}")
        self.pipeline = create_pipeline()
        self.device = None
        self.det_queue = None
        self.depth_queue = None
        self._latest_depth = None      # 최근 depth 프레임 (numpy 배열, mm 단위)
        # 라벨별 최근 거리 기록 (이동 평균용)
        self._distance_history = defaultdict(lambda: deque(maxlen=SMOOTHING_WINDOW))

    def __enter__(self):
        # maxUsbSpeed=HIGH: 노트북 USB 환경 안정화
        self.device = dai.Device(self.pipeline, maxUsbSpeed=dai.UsbSpeed.HIGH)
        self.det_queue = self.device.getOutputQueue(
            name="detections", maxSize=4, blocking=False)
        self.depth_queue = self.device.getOutputQueue(
            name="depth", maxSize=4, blocking=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.device is not None:
            self.device.close()

    def get_usb_speed(self):
        """현재 USB 연결 속도 반환 (디버깅용)."""
        try:
            return self.device.getUsbSpeed()
        except Exception:
            return None

    def get_obstacles(self):
        """현재 프레임의 실내 관련 장애물 목록 반환.

        반환: [{"label": "의자", "distance_m": 2.34,
                "direction": "정면", "confidence": 0.87}, ...]
        감지 결과가 아직 없으면 None 반환 (논블로킹).
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

            # 거리 측정 실패한 객체는 제외 (0에 가까우면 측정 불가)
            if distance_m <= 0.1:
                continue

            label_ko = INDOOR_RELEVANT[label_en]
            seen_labels.add(label_ko)

            # ── 이동 평균: 같은 라벨의 최근 거리들을 평균 내서 출렁임 완화 ──
            history = self._distance_history[label_ko]
            history.append(distance_m)
            smoothed_m = sum(history) / len(history)

            obstacles.append({
                "label": label_ko,
                "distance_m": smoothed_m,
                "raw_distance_m": distance_m,
                "direction": describe_direction(x_mm),
                "confidence": det.confidence,
            })

        # 이번 프레임에 안 보인 라벨의 기록은 비워서 옛 거리가 남지 않게 함
        for label_ko in list(self._distance_history.keys()):
            if label_ko not in seen_labels:
                self._distance_history[label_ko].clear()

        return obstacles

    def _update_depth(self):
        """최근 depth 프레임을 받아 저장 (논블로킹)."""
        in_depth = self.depth_queue.tryGet()
        if in_depth is not None:
            self._latest_depth = in_depth.getFrame()  # numpy (H, W), mm 단위

    def get_open_direction(self):
        """depth 맵을 좌/중/우로 3등분해 회피 상황을 판단.

        반환: (situation, info)
          situation 코드 (문자열):
            "right"      → 오른쪽으로 피하라 (오른쪽만 트임 / 오른쪽이 확실히 더 트임)
            "left"       → 왼쪽으로 피하라
            "either"     → 양쪽 다 트이고 비슷함 (아무 쪽이나 가능)
            "blocked"    → 양쪽 다 막힘 (벽/거대 장애물, 진입 불가)
          info: {"left_m":.., "center_m":.., "right_m":..}
          depth가 아직 없으면 (None, None).
        """
        self._update_depth()
        if self._latest_depth is None:
            return None, None

        depth = self._latest_depth
        h, w = depth.shape

        # 세로는 중앙 60%만 사용 (바닥/천장 노이즈 제외)
        y0, y1 = int(h * 0.2), int(h * 0.8)
        band = depth[y0:y1, :]

        third = w // 3
        left = band[:, :third]
        center = band[:, third:2 * third]
        right = band[:, 2 * third:]

        def region_clearance(region):
            """구역의 '가까운 쪽' 대표 거리(m). 값이 클수록 트여 있음."""
            valid = region[region > 0]        # 0은 측정 실패 → 제외
            if valid.size == 0:
                return 0.0
            # 가장 가까운 10% 지점(=그 구역에서 제일 가까운 장애물 수준)
            return float(np.percentile(valid, 10)) / 1000.0

        left_m = region_clearance(left)
        center_m = region_clearance(center)
        right_m = region_clearance(right)
        info = {"left_m": left_m, "center_m": center_m, "right_m": right_m}

        left_open = left_m >= CLEAR_THRESHOLD_M
        right_open = right_m >= CLEAR_THRESHOLD_M
        diff = abs(right_m - left_m)

        # ── 4가지 상황 판단 ──
        if not left_open and not right_open:
            # 양쪽 다 막힘 → 벽/거대 장애물
            situation = "blocked"
        elif left_open and right_open:
            # 양쪽 다 트임 → 차이가 크면 더 트인 쪽, 비슷하면 아무 쪽이나
            if diff < SIDE_DIFF_THRESHOLD_M:
                situation = "either"
            else:
                situation = "right" if right_m > left_m else "left"
        else:
            # 한쪽만 트임 → 그쪽으로
            situation = "right" if right_open else "left"

        return situation, info