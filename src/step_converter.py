"""
step_converter.py
-----------------
거리(m) → 걸음 수 환산 + 사용자 보폭 보정(calibration) + 안전 판단 모듈.

[핵심 철학]
  - 걸음 수는 "누적해서 세는 값"이 아니라, 매 순간 측정된 거리를
    사용자 보폭으로 나눈 "순간 환산값"이다. → 오차가 누적되지 않음.
  - 충돌 경고(안전)는 걸음 수가 아니라 실측 거리(m)로 판단한다.
    → 보폭 오차가 안전을 위협하지 않음.

[보정 루틴 (calibration)]
  - 처음 1회만 실행: 줄자로 미리 잰 거리(예: 10m)를 걷게 하고
    "몇 걸음 걸었는지"를 입력받아 보폭 = 거리 / 걸음수 로 계산.
  - 측정한 보폭은 파일에 저장 → 다음 실행부터는 다시 안 물어봄.
"""

import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STRIDE_FILE = os.path.join(SCRIPT_DIR, "stride_config.json")

# ── 안전 임계값 (걸음 수 기준) ─────────────────────────
#   사용자(시각장애인)는 거리를 '걸음'으로 체감하므로 안전 등급도 걸음 수로 판단.
#   걸음 수 = 매 프레임 실측 거리 ÷ 사용자 보폭 (누적 아님 → 오차 누적 없음)
STOP_STEPS = 3       # 이 걸음 수 이내면 "정지" (가장 우선)
WARN_STEPS = 6       # 이 걸음 수 이내면 "주의"
                     # WARN_STEPS 초과는 "안전" → 안내 안 함

DEFAULT_STRIDE_M = 0.7     # 보정 안 했을 때 임시 기본 보폭


def load_stride():
    """저장된 사용자 보폭을 불러옴. 없으면 None."""
    if not os.path.exists(STRIDE_FILE):
        return None
    try:
        with open(STRIDE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return float(data.get("stride_m"))
    except Exception:
        return None


def save_stride(stride_m):
    """사용자 보폭을 파일에 저장."""
    with open(STRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump({"stride_m": stride_m}, f, ensure_ascii=False, indent=2)


def calibrate_stride():
    """보정 루틴: 정해진 거리를 걷게 해서 사용자 보폭을 측정.

    [사용 방법]
      1. 줄자로 바닥에 정확한 거리(예: 10m)를 미리 표시해둔다.
      2. 사용자가 그 거리를 평소처럼 걷는다.
      3. 걸은 거리와 걸음 수를 입력하면 보폭이 계산된다.

    반환: 측정된 보폭(m)
    """
    print("=" * 50)
    print("  보폭 측정")
    print("=" * 50)
    print("줄자로 바닥에 정해진 거리를 표시하고, 그 거리를 평소처럼 걸어주세요.")
    print()

    while True:
        try:
            distance_m = float(input("  걸은 거리는 몇 m 인가요? (예: 10): ").strip())
            steps = int(input("  그 거리를 몇 걸음에 걸었나요? (예: 14): ").strip())
            if distance_m <= 0 or steps <= 0:
                print("  [오류] 0보다 큰 값을 입력하세요.\n")
                continue
            stride_m = distance_m / steps
            print(f"\n  → 측정된 보폭: {stride_m:.3f} m (한 걸음 약 {stride_m*100:.0f}cm)\n")
            save_stride(stride_m)
            return stride_m
        except ValueError:
            print("  [오류] 숫자를 입력하세요.\n")


def get_user_stride(force_recalibrate=False):
    """사용자 보폭을 확보. 저장값이 있으면 쓰고, 없으면 보정 실행.

    force_recalibrate=True 면 저장값을 무시하고 다시 보정.
    """
    if not force_recalibrate:
        saved = load_stride()
        if saved is not None:
            print(f"[보폭] 저장된 값 사용: {saved:.3f} m")
            return saved
    return calibrate_stride()


def distance_to_steps(distance_m, stride_m):
    """거리(m)를 걸음 수로 환산. 매 순간 새로 계산되므로 오차 누적 없음."""
    if stride_m <= 0:
        stride_m = DEFAULT_STRIDE_M
    return round(distance_m / stride_m)


def assess_safety(distance_m, stride_m):
    """걸음 수 기준 안전 등급 판단.

    걸음 수 = 실측 거리 ÷ 사용자 보폭 (매 프레임 새로 환산 → 오차 누적 없음)

    반환: "stop"(정지) / "warn"(주의) / "ok"(안전, 안내 안 함)
    """
    steps = distance_to_steps(distance_m, stride_m)
    if steps <= STOP_STEPS:
        return "stop"
    elif steps <= WARN_STEPS:
        return "warn"
    else:
        return "ok"


def avoidance_phrase(situation):
    """회피 상황 코드 → 안내 덧붙임 문구. 해당 없으면 빈 문자열."""
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
    """장애물 정보 → 음성 안내 문구 생성.

    obstacle: {"label", "distance_m", "direction", "confidence"}
    avoid_situation: 회피 상황 코드("right"/"left"/"either"/"blocked").
                     주어지면 안내 끝에 적절한 문구를 덧붙임.
    반환: 안내 문구 문자열. "안전"(ok) 등급이면 None (안내 안 함).
    """
    label = obstacle["label"]
    distance_m = obstacle["distance_m"]
    direction = obstacle["direction"]

    safety = assess_safety(distance_m, stride_m)
    steps = distance_to_steps(distance_m, stride_m)

    # 막다른 길 처리: 정지 거리에선 핵심만 간결하게, 주의 거리에선 미리 알림
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
        return None   # 안전 등급은 안내하지 않음