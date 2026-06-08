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

# ── 안전 임계값 (실측 거리 m 기준) ───────────────────
#   [설계 변경 근거]
#   기존엔 "걸음 수"로 안전을 판단했으나, 걸음 수는 보폭에 따라 같은 위험거리가
#   사람마다 다른 거리로 환산되는 문제가 있다(보폭 짧은 사람일수록 더 일찍 경고).
#   안전은 보폭과 무관한 물리량이므로 "실측 거리(m)"로 판단하는 것이 옳다.
#
#   [수치 근거 — 시각장애인 보행 특성 연구]
#   · 독립 보행 시각장애인의 평균 보행속도는 약 1.0~1.44 m/s로 정안인보다 느리고,
#     시야가 완전히 차단된 조건에서는 0.84 m/s 수준까지 떨어진다.
#   · 시각장애인 보행보조장치(ETA) 평가 연구들은 "장애물을 최소 1.5 m 거리에서
#     감지·인지"할 수 있어야 안전한 대응이 가능하다고 본다.
#   · 음성 안내는 "재생 + 청취 + 인지 + 정지"에 통상 1~2초가 걸린다.
#
#   [현재 설정] 사용자 요청으로 STOP을 1.0 m로 운용한다.
#     WARN: 3.0 m (미리 알림 — 감속·대비 시간 확보)
#     STOP: 1.0 m (즉시 정지 — 더 가까이 접근해야 정지 안내)
#     ※ 1.0 m는 권장 안전거리(1.5 m)보다 짧아 반응 여유가 줄어든다.
#       보행 속도가 빠른 사용자에겐 1.5 m 복귀를 고려할 것.
STOP_DISTANCE_M = 1.0
WARN_DISTANCE_M = 3.0

# (참고) 음성 문구의 '걸음 수'는 사용자의 거리 체감을 돕는 표시용일 뿐,
#        안전 등급 판단에는 쓰지 않는다.

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
    """좁은 통로 판단 기준 거리 = 어깨너비 × 배수."""
    return body_width_m * NARROW_SIDE_RATIO


def get_front_half_width(body_width_m):
    """'정면(진행 경로)'으로 볼 좌우 반폭(m). 어깨너비 + 여유의 절반."""
    return (body_width_m + BODY_SIDE_MARGIN_M) / 2.0


def distance_to_steps(distance_m, stride_m):
    """거리(m)를 걸음 수로 환산. 매 순간 새로 계산되므로 오차 누적 없음."""
    if stride_m <= 0:
        stride_m = DEFAULT_STRIDE_M
    return round(distance_m / stride_m)


def assess_safety(distance_m, stride_m=None):
    """실측 거리(m) 기준 안전 등급. 반환: "stop" / "warn" / "ok".

    stride_m 인자는 하위호환을 위해 받기만 하고 사용하지 않는다.
    (안전 판단은 보폭과 무관한 절대 거리로 한다)
    """
    if distance_m <= STOP_DISTANCE_M:
        return "stop"
    elif distance_m <= WARN_DISTANCE_M:
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


# ── 음성 조각(gen_voices.py의 키) 매핑 ───────────────────
LABEL_TO_CHUNK = {
    "사람": "obj_person",
    "의자": "obj_chair",
    "소파": "obj_sofa",
    "식탁": "obj_table",
    "모니터": "obj_monitor",
    "장애물": "obj_unknown",
}
AVOID_TO_CHUNK = {
    "right": "avoid_right",
    "left": "avoid_left",
    "either": "avoid_both",
    # "blocked"는 회피 방향이 없으므로 조각 없음
}
CLOCK_TO_CHUNK = {
    "10시": "clock_10", "11시": "clock_11", "12시": "clock_12",
    "1시": "clock_1", "2시": "clock_2",
}


def _step_chunk(steps):
    """걸음 수 → step_N 조각 키. 범위(1~30) 밖이면 가까이로 클램프."""
    n = max(1, min(30, int(steps)))
    return f"step_{n}"


def build_guidance(obstacle, stride_m, avoid_situation=None):
    """장애물 정보 → (chunks, text).
       안내할 게 없으면 (None, None).

    [stop은 짧게] 위급할수록 빨리 전달돼야 하므로, stop은 거리(걸음 수)를
    빼고 "정지 + 물체 + 회피"로 압축한다. warn은 거리까지 상세히 안내한다.
    """
    label = obstacle["label"]
    distance_m = obstacle["distance_m"]
    direction = obstacle["direction"]

    safety = assess_safety(distance_m, stride_m)
    steps = distance_to_steps(distance_m, stride_m)

    obj_chunk = LABEL_TO_CHUNK.get(label, "obj_unknown")
    avoid_chunk = None if avoid_situation == "blocked" \
        else AVOID_TO_CHUNK.get(avoid_situation)
    avoid_text = avoidance_phrase(avoid_situation) if avoid_situation else ""

    if safety == "stop":
        # 짧게: 정지 + 물체 (+ 회피)
        chunks = ["grade_stop", obj_chunk]
        text = f"정지. {label}."
        if avoid_chunk:
            chunks.append(avoid_chunk)
            text = f"정지. {label}.{avoid_text}"
        return chunks, text

    elif safety == "warn":
        # 상세: 주의 + 정면 + N걸음 + 앞에 + 물체 (+ 회피)
        chunks = ["grade_warn", "pos_front", _step_chunk(steps), "ape", obj_chunk]
        text = f"주의. {direction} {steps}걸음 앞에 {label}."
        if avoid_chunk:
            chunks.append(avoid_chunk)
            text = f"주의. {direction} {steps}걸음 앞에 {label}.{avoid_text}"
        return chunks, text

    return None, None


def build_narrow_corridor_guidance():
    """좁은 통로 진입 안내. → (chunks, text)"""
    return ["narrow"], "좁은 통로, 주의하세요."


def build_dropoff_guidance(status):
    """단차(계단) 안내. → (chunks, text). 안내할 게 없으면 (None, None).

    status: "down" = 내려가는 계단(메인 기능),
            "up"   = 올라가는 계단(ENABLE_STEP_UP일 때만 들어옴, 실험용).
    """
    if status == "down":
        return ["step_down"], "주의, 앞에 내려가는 계단."
    elif status == "up":
        return ["step_up"], "주의, 앞에 올라가는 계단."
    return None, None


def build_tactile_appear_guidance(clock_direction, distance_m, stride_m):
    """점자블록 출현 안내. → (chunks, text)"""
    clock_chunk = CLOCK_TO_CHUNK.get(clock_direction)
    if distance_m is not None and distance_m > 0:
        steps = distance_to_steps(distance_m, stride_m)
        chunks = []
        if clock_chunk:
            chunks.append(clock_chunk)
        chunks += [_step_chunk(steps), "ape", "tactile"]
        text = f"{clock_direction} 방향 {steps}걸음 앞에 점자블록."
        return chunks, text
    chunks = ([clock_chunk] if clock_chunk else []) + ["tactile"]
    return chunks, f"{clock_direction} 방향에 점자블록."


def build_tactile_leaving_guidance():
    """점자블록 곧 벗어남 안내. → (chunks, text)"""
    return ["tactile_leaving"], "점자블록 곧 벗어남."


def build_tactile_query_guidance(tactile, stride_m):
    """버튼을 눌렀을 때 점자블록 상태 안내. → (chunks, text)
       있으면 방향·거리까지, 없으면 "주변에 점자블록이 없습니다."
    """
    if tactile is None or not tactile.get("present"):
        return ["tactile_none"], "주변에 점자블록이 없습니다."
    return build_tactile_appear_guidance(
        tactile.get("clock_direction"),
        tactile.get("distance_m"),
        stride_m,
    )


def build_crosswalk_appear_guidance(clock_direction):
    """횡단보도 출현 안내. → (chunks, text)
       거리는 흰 줄 무게중심 기준이라 부정확할 수 있어 방향만 안내한다.
    """
    clock_chunk = CLOCK_TO_CHUNK.get(clock_direction)
    chunks = ([clock_chunk] if clock_chunk else []) + ["crosswalk"]
    return chunks, f"{clock_direction} 방향에 횡단보도."


def build_environment_query_guidance(tactile, crosswalk, stride_m):
    """버튼을 눌렀을 때 점자블록 + 횡단보도 상태를 모두 안내. → (chunks, text)

    [정책]
      · 둘 다 잡히면 점자블록 → 횡단보도 순서로 둘 다 안내.
        예) "1시 방향 세 걸음 앞에 점자블록. 11시 방향에 횡단보도."
      · 하나만 잡히면 그것만 안내.
      · 둘 다 없으면 "주변에 점자블록이나 횡단보도가 없습니다."
    """
    chunks = []
    texts = []

    if tactile is not None and tactile.get("present"):
        c, t = build_tactile_appear_guidance(
            tactile.get("clock_direction"), tactile.get("distance_m"), stride_m)
        chunks += c
        texts.append(t)

    if crosswalk is not None and crosswalk.get("present"):
        c, t = build_crosswalk_appear_guidance(crosswalk.get("clock_direction"))
        chunks += c
        texts.append(t)

    if not chunks:
        return ["env_none"], "주변에 점자블록이나 횡단보도가 없습니다."
    return chunks, " ".join(texts)


def build_tactile_disappear_guidance():
    """점자블록이 사라졌을 때 안내. (현재 미사용) → (chunks, text)"""
    return ["tactile_leaving"], "점자블록 벗어남."