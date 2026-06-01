"""
step_converter.py
-----------------
거리(m) → 걸음 수 환산 + 사용자 보폭/키 보정(calibration) + 안전 판단 모듈.

[핵심 철학]
  - 걸음 수는 "누적해서 세는 값"이 아니라, 매 순간 측정된 거리를
    사용자 보폭으로 나눈 "순간 환산값"이다. → 오차가 누적되지 않음.
  - 충돌 경고(안전)는 걸음 수가 아니라 실측 거리(m)로 판단한다.
    → 보폭 오차가 안전을 위협하지 않음.
  - 사용자 키 → 어깨너비 추정 (키 × 0.259, 인체 측정 비율).
    → 좁은 통로 판단 기준에 사용 (어깨너비 + 여유 = "좁다" 기준).

[보정 루틴 (calibration)]
  - 처음 1회만 실행: 줄자로 미리 잰 거리(예: 10m)를 걷게 하고
    "몇 걸음 걸었는지"를 입력받아 보폭 = 거리 / 걸음수 로 계산.
  - 같은 시점에 키도 함께 입력받아 어깨너비를 추정.
  - 측정한 값들은 파일에 저장 → 다음 실행부터는 다시 안 물어봄.
"""

import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STRIDE_FILE = os.path.join(SCRIPT_DIR, "stride_config.json")

# ── 안전 임계값 (걸음 수 기준) ─────────────────────────
#   사용자(시각장애인)는 거리를 '걸음'으로 체감하므로 안전 등급도 걸음 수로 판단.
#   걸음 수 = 매 프레임 실측 거리 ÷ 사용자 보폭 (누적 아님 → 오차 누적 없음)
STOP_STEPS = 3       # 이 걸음 수 이내면 "정지" (비상)
WARN_STEPS = 7       # 이 걸음 수 이내면 "주의"  ← 6에서 7로 변경
                     # WARN_STEPS 초과는 "안전" → 안내 안 함

DEFAULT_STRIDE_M = 0.7        # 보정 안 했을 때 임시 기본 보폭
DEFAULT_BODY_WIDTH_M = 0.45   # 어깨너비 기본값 (성인 평균)
BODY_SIDE_MARGIN_M = 0.20     # (정면 경로 반폭 계산에 사용)
NARROW_SIDE_RATIO = 3.0       # 좁은 통로: 양옆이 어깨너비 × 이 값 이내면 '가깝다'

# 인체 측정 비율: 어깨너비 ≈ 키 × 0.259
SHOULDER_RATIO = 0.259


def load_config():
    """저장된 사용자 보폭/어깨너비를 불러옴. 없으면 None."""
    if not os.path.exists(STRIDE_FILE):
        return None
    try:
        with open(STRIDE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "stride_m": float(data.get("stride_m")),
            "body_width_m": float(data.get("body_width_m", DEFAULT_BODY_WIDTH_M)),
        }
    except Exception:
        return None


def save_config(stride_m, body_width_m):
    """사용자 보폭/어깨너비를 파일에 저장."""
    with open(STRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "stride_m": stride_m,
            "body_width_m": body_width_m,
        }, f, ensure_ascii=False, indent=2)


def estimate_shoulder_width(height_cm):
    """키(cm)로부터 어깨너비(m) 추정. 키 × 0.259 / 100."""
    return round(height_cm * SHOULDER_RATIO / 100.0, 3)


def calibrate_user():
    """보정 루틴: 보폭(걸은 거리/걸음수) + 어깨너비(키 입력) 측정.

    [사용 방법]
      1. 줄자로 바닥에 정확한 거리(예: 10m)를 미리 표시해둔다.
      2. 사용자가 그 거리를 평소처럼 걷는다.
      3. 걸은 거리와 걸음 수, 그리고 키를 입력하면 보폭과 어깨너비가 계산된다.

    반환: (stride_m, body_width_m)
    """
    print("=" * 50)
    print("  사용자 보정")
    print("=" * 50)
    print("줄자로 바닥에 정해진 거리를 표시하고, 그 거리를 평소처럼 걸어주세요.")
    print()

    # ── 보폭 측정 ──
    while True:
        try:
            distance_m = float(input("  걸은 거리는 몇 m 인가요? (예: 10): ").strip())
            steps = int(input("  그 거리를 몇 걸음에 걸었나요? (예: 14): ").strip())
            if distance_m <= 0 or steps <= 0:
                print("  [오류] 0보다 큰 값을 입력하세요.\n")
                continue
            stride_m = distance_m / steps
            print(f"\n  → 측정된 보폭: {stride_m:.3f} m (한 걸음 약 {stride_m*100:.0f}cm)")
            break
        except ValueError:
            print("  [오류] 숫자를 입력하세요.\n")

    # ── 키 입력 → 어깨너비 추정 ──
    print()
    while True:
        try:
            raw = input("  사용자의 키는 몇 cm 인가요? (예: 170, 모르면 엔터): ").strip()
            if raw == "":
                body_width_m = DEFAULT_BODY_WIDTH_M
                print(f"  → 키 미입력. 기본 어깨너비 {body_width_m} m 사용\n")
                break
            height_cm = float(raw)
            if height_cm <= 0:
                print("  [오류] 0보다 큰 값을 입력하세요.\n")
                continue
            body_width_m = estimate_shoulder_width(height_cm)
            print(f"  → 추정 어깨너비: {body_width_m} m "
                  f"(키 {height_cm:.0f}cm × 0.259)\n")
            break
        except ValueError:
            print("  [오류] 숫자를 입력하세요.\n")

    save_config(stride_m, body_width_m)
    return stride_m, body_width_m


def get_user_profile(force_recalibrate=False):
    """사용자 보폭/어깨너비를 확보. 저장값이 있으면 쓰고, 없으면 보정 실행.

    반환: (stride_m, body_width_m)
    """
    if not force_recalibrate:
        saved = load_config()
        if saved is not None:
            print(f"[보정] 저장된 값 사용 — 보폭: {saved['stride_m']:.3f} m, "
                  f"어깨너비: {saved['body_width_m']:.3f} m")
            return saved["stride_m"], saved["body_width_m"]
    return calibrate_user()


# ── 하위호환: 기존 코드(main.py)가 get_user_stride를 부르고 있어서 유지 ──
def get_user_stride(force_recalibrate=False):
    """[deprecated] 보폭만 반환. 가능하면 get_user_profile() 사용 권장."""
    stride_m, _ = get_user_profile(force_recalibrate=force_recalibrate)
    return stride_m


def get_narrow_threshold(body_width_m):
    """좁은 통로 판단 기준 거리 = 어깨너비 × 배수.
    양옆 거리가 둘 다 이 값 이내일 때 '벽/책상이 가깝다'고 본다.
    실측(키155, 어깨0.40, 책상사이 양옆 0.9~1.2m) 기준으로 배수 3.0 시작.
    키 큰 사람은 어깨너비가 커서 자동으로 더 넉넉해진다."""
    return body_width_m * NARROW_SIDE_RATIO


def get_front_half_width(body_width_m):
    """'정면(진행 경로)'으로 볼 좌우 반폭(m).
    어깨너비 + 여유의 절반. 이 폭 안의 장애물만 부딪힐 경로로 본다.
    예: 어깨너비 0.45 + 여유 0.20 = 0.65 → 반폭 0.325m
    """
    return (body_width_m + BODY_SIDE_MARGIN_M) / 2.0


def distance_to_steps(distance_m, stride_m):
    """거리(m)를 걸음 수로 환산. 매 순간 새로 계산되므로 오차 누적 없음."""
    if stride_m <= 0:
        stride_m = DEFAULT_STRIDE_M
    return round(distance_m / stride_m)


def assess_safety(distance_m, stride_m):
    """걸음 수 기준 안전 등급. 반환: "stop" / "warn" / "ok"."""
    steps = distance_to_steps(distance_m, stride_m)
    if steps <= STOP_STEPS:
        return "stop"
    elif steps <= WARN_STEPS:
        return "warn"
    else:
        return "ok"


def avoidance_phrase(situation):
    """회피 상황 코드 → 안내 덧붙임 문구."""
    if situation == "right":
        return " 오른쪽으로 이동."
    elif situation == "left":
        return " 왼쪽으로 이동."
    elif situation == "either":
        return " 양옆으로 피할 수 있음."
    elif situation == "blocked":
        return " 막다른 길입니다."
    else:
        return ""


def build_guidance(obstacle, stride_m, avoid_situation=None):
    """장애물 정보 → 음성 안내 문구. (기존 로직 유지, WARN 임계값만 7로 영향)"""
    label = obstacle["label"]
    distance_m = obstacle["distance_m"]
    direction = obstacle["direction"]

    safety = assess_safety(distance_m, stride_m)
    steps = distance_to_steps(distance_m, stride_m)

    if avoid_situation == "blocked":
        if safety == "stop":
            return "정지. 막다른 길입니다."
        elif safety == "warn":
            return f"주의. {steps}걸음 앞에 막다른 길."
        else:
            return None

    avoid = avoidance_phrase(avoid_situation) if avoid_situation else ""

    if safety == "stop":
        return f"정지. {direction} {steps}걸음 앞에 {label}.{avoid}"
    elif safety == "warn":
        return f"주의. {direction} {steps}걸음 앞에 {label}.{avoid}"
    else:
        return None


def build_narrow_corridor_guidance():
    """좁은 통로 진입 안내. 폭 숫자는 말하지 않음."""
    return "좁은 통로, 주의하세요."


def build_tactile_appear_guidance(clock_direction, distance_m, stride_m):
    """점자블록이 새로 나타났을 때 안내.
       예: "11시 방향 세 걸음 앞에 점자블록."
       거리 측정이 안 됐으면 걸음 수 부분 생략.
    """
    if distance_m is not None and distance_m > 0:
        steps = distance_to_steps(distance_m, stride_m)
        return f"{clock_direction} 방향 {steps}걸음 앞에 점자블록."
    return f"{clock_direction} 방향에 점자블록."


def build_tactile_disappear_guidance():
    """점자블록이 사라졌을 때 안내."""
    return "점자블록 벗어남."