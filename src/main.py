"""
main.py
-------
시각 보조 시스템 메인 루프.

[안내 정책]
  - 장애물(stop): 같은 상태일 때 최대 2회만 발화 후 조용. 상태가 바뀌면 리셋.
  - 장애물(warn): 같은 상태일 때 1회만. 상태가 바뀌면 다시.
  - 상태 키에 '걸음수'는 넣지 않는다. 같은 물체에 다가가는 동안 걸음수가
    4→3→2→1로 줄어도 매번 새 안내가 나가지 않게 하기 위함이다. 안내는
    '등급(warn↔stop)·라벨·방향·회피'가 바뀔 때만 새로 나간다.
      예) 처음 감지: "주의, 4걸음 앞 의자" 1회 →
          (다가가는 동안 조용) →
          1.0m 안에 들어와 stop 등급이 되는 순간: "정지" 1회
  - 안내 최소 간격(쿨다운): 카메라가 1초에 여러 번(예: 20fps) 돌므로, 같은
    상태가 유지되는 동안 매 프레임 안내가 쏟아지지 않도록 마지막 발화로부터
    일정 시간이 지나야 다음 안내를 내보낸다. (stop은 짧게, warn은 길게)
  - 겹침 방지: 안내는 say()로 보낸다. 정지(stop)는 약한 안내(warn)를 끊고
    끼어들지만 stop끼리는 안 끊는다. 그 외는 재생 중이면 tts가 '최신 하나'만
    펜딩 슬롯에 보류했다 이어 재생한다. (tts.py가 처리)
  - 점자블록(자동): 자동 안내 없음. 버튼(GPIO17)을 누를 때만 안내.
  - 좁은 통로: 진입 시 1회. (위급 장애물이 그 프레임에 안내됐거나 재생 중이면 보류)
  - 모든 판정은 깜빡임 방지 위해 hysteresis (연속 N프레임 확정) 적용.

[흐름]
  1. 사용자 보폭 + 어깨너비 확보
  2. OAK-D-Lite 연결
  3. 반복: 장애물 → 점자블록(버튼) → 좁은 통로 순으로 이벤트 판정 후 안내

[실행]
  python main.py                # 매번 새로 보정
  python main.py --keep-stride  # 저장된 보폭/어깨너비 재사용
  python main.py --dry-run      # 음성 없이 화면 출력
  python main.py --debug        # 디버그 출력
"""

import sys
import time

from oak_reader import OakReader
from step_converter import (
    get_user_profile,
    get_narrow_threshold,
    get_front_half_width,
    build_guidance,
    build_narrow_corridor_guidance,
    build_dropoff_guidance,
    build_tactile_query_guidance,
    build_environment_query_guidance,
    distance_to_steps,
    assess_safety,
)
from tts import Speaker

# ── 안내 정책 상수 ────────────────────────────────────
STOP_MAX_REPEATS = 2          # 같은 stop 상태에서 최대 2회까지 발화
STOP_REPEAT_INTERVAL = 1.0    # stop 두 번 발화 사이 최소 간격(초)

# ── 안내 최소 간격(쿨다운) ────────────────────────────
#   카메라 루프는 1초에 여러 번(예: 20fps) 돈다. 같은 상황이 유지되는 동안
#   매 프레임 안내를 던지면 폭주하고 펜딩이 누적돼 안내가 늦어진다(지연).
#   그래서 마지막으로 '실제 발화'한 시각으로부터 아래 간격이 지나기 전에는
#   같은 상태의 새 안내를 내보내지 않는다.
#     · stop: 위급하므로 비교적 짧게(자주 갱신 허용)
#     · warn: 여유 있으므로 길게(불필요한 반복 억제)
#   상태 키가 '바뀌면'(등급/라벨/방향/회피) 쿨다운과 무관하게 즉시 안내한다.
STOP_SPEAK_COOLDOWN = 5.0     # 같은 정지 상황 반복 안내 최소 간격(초)
WARN_SPEAK_COOLDOWN = 10.0     # 같은 주의 상황 반복 안내 최소 간격(초)

# ── 전체 최소 간격(떨림으로 인한 폭주 방지) ────────────
#   라벨/방향/회피가 깜빡이면 '상태 키'가 매번 바뀐 걸로 보여 쿨다운을
#   건너뛰고 안내가 쏟아진다. 그래서 키가 바뀌어도 마지막 발화로부터
#   아래 간격 안에는 새 안내를 내보내지 않는다(= 모든 장애물 안내의 하한선).
#   단, warn→stop으로 '승격'될 때는 위급하므로 이 간격을 무시하고 즉시 안내.
OBSTACLE_MIN_INTERVAL = 3.0   # 키가 바뀌어도 지켜야 할 장애물 안내 최소 간격(초)

# ── 거리 갱신 안내 ────────────────────────────────────
#   같은 장애물(등급/라벨/방향 동일)이라도, 사용자가 다가가 걸음 수가
#   이만큼 줄면 "지금 거리"로 한 번 다시 안내한다. 매 걸음(4→3→2→1)
#   떠드는 폭주는 막으면서, "8걸음"이라고 했다가 5걸음 앞인데 그대로 두는
#   '거리 정보 정체'를 해결한다. (값↑ = 갱신 덜 자주)
STEP_REFRESH_DELTA = 2

# 점자블록 "곧 벗어남" 판정: 노란 영역의 먼 끝이 이 걸음수 이내면 발화
TACTILE_LEAVING_STEPS = 4

# 깜빡임 방지(hysteresis): 연속 N프레임 같은 상태가 잡혀야 확정
TACTILE_CONFIRM_FRAMES = 3
NARROW_CONFIRM_FRAMES = 3

# 단차(계단/drop-off) 안내 정책
#   · 연속 N프레임 같은 상태일 때만 확정(노이즈로 인한 헛경고 방지).
#   · 위험 상태(down/up)로 새로 진입하면 즉시 1회 안내.
#   · 같은 위험 상태가 계속되면 쿨다운 간격마다 한 번씩 환기(낙상 위험이라 반복 알림).
ENABLE_DROPOFF = False         # 단차 기능 ON/OFF 스위치. False면 단차 감지·안내 전체 비활성
DROPOFF_CONFIRM_FRAMES = 3
DROPOFF_SPEAK_COOLDOWN = 2.0

# depth로 미확인 장애물을 안내할 때, 근처 검출 물체의 라벨을 빌려오는 기준
NEAR_NOISE_M = 0.4            # 이보다 가까운 검출 거리는 측정 신뢰도 낮음 → 라벨 후보 제외
LABEL_BORROW_MARGIN_M = 0.6  # 정면 depth 거리보다 이만큼 이내로 가까운 검출이면 같은 물체로 보고 라벨 차용


def pick_priority_obstacle(obstacles, center_m=None):
    """안내할 정면 장애물 1개 선택. (depth 우선 + 검출로 라벨·거리 보강)

    [정책]
      1) MobileNet이 정면에서 잡은 물체가 있으면 그중 가장 가까운 것.
      2) 정면 검출은 없지만 depth상 정면(center_m)이 가까우면 경고(라벨/거리 보강).
      3) 정면에 검출도 없고 depth도 충분히 멀면 None(조용).
    """
    obstacles = obstacles or []
    front = [o for o in obstacles if o["direction"] == "정면"]

    # 1) 정면 검출 물체 우선
    if front:
        return min(front, key=lambda o: o["distance_m"])

    # 2) 정면 검출 없음 + depth 정면이 가까움 → 경고 (라벨/거리 보강)
    if center_m is not None and center_m > 0:
        if assess_safety(center_m) in ("stop", "warn"):
            label = "장애물"
            dist = center_m
            candidates = [
                o for o in obstacles
                if o["distance_m"] >= NEAR_NOISE_M
                and o["distance_m"] <= center_m + LABEL_BORROW_MARGIN_M
            ]
            if candidates:
                closest = min(candidates, key=lambda o: o["distance_m"])
                label = closest["label"]
                dist = min(center_m, closest["distance_m"])   # 더 가까운 값(안전 우선)
            return {
                "label": label,
                "distance_m": dist,
                "direction": "정면",
                "x_mm": 0,
                "confidence": None,
                "unknown": (label == "장애물"),
            }
    return None


def make_obstacle_state_key(target, stride_m, avoid_situation):
    """장애물의 '안내 상태' 키. 이 키가 변하면 새 이벤트로 본다.

    [걸음수 제외] 같은 물체에 다가가는 동안 걸음수(4→3→2→1)가 줄어도
    같은 이벤트로 보고 반복 안내하지 않는다. 안내가 새로 나가는 경우는
    등급(warn↔stop)·라벨·방향·회피상황이 바뀔 때뿐이다.
    (거리/걸음수 변화만으로는 새 안내를 만들지 않는다.)
    """
    if target is None:
        return None
    safety = assess_safety(target["distance_m"], stride_m)
    return (target["label"], target["direction"], safety, avoid_situation)


def main():
    keep_stride = "--keep-stride" in sys.argv
    dry_run = "--dry-run" in sys.argv
    debug = "--debug" in sys.argv

    print("=" * 60)
    print("  시각 보조 시스템 (장애물 + 점자블록 + 좁은 통로)")
    print("=" * 60)

    # 1) 사용자 보폭 + 어깨너비
    stride_m, body_width_m = get_user_profile(force_recalibrate=not keep_stride)
    narrow_threshold = get_narrow_threshold(body_width_m)
    front_half_width = get_front_half_width(body_width_m)
    print(f"[설정] 좁은 통로 기준: 양옆 {narrow_threshold:.2f}m 이내")
    print(f"[설정] 정면 경로 반폭: {front_half_width:.2f}m")

    # 2) 음성 엔진
    speaker = Speaker(dry_run=dry_run)

    # 2-1) 환경 조회 버튼 (GPIO17). 누르면 현재 점자블록 + 횡단보도 상태를 안내.
    button = None
    button_state = {"tactile": None, "crosswalk": None}   # 루프가 최신 측정값을 넣어줌
    try:
        from gpiozero import Button
        button = Button(17, pull_up=True, bounce_time=0.05)

        def on_button_press():
            guidance = build_environment_query_guidance(
                button_state["tactile"], button_state["crosswalk"], stride_m)
            speaker.say_now(guidance)   # 버튼 응답은 즉시(인터럽트)

        button.when_pressed = on_button_press
        print("[버튼] 환경 조회 버튼 준비 완료 (GPIO17) — 점자블록 + 횡단보도")
    except ImportError:
        print("[버튼] gpiozero 없음 → 버튼 비활성화 (노트북 테스트 모드)")
    except Exception as e:
        print(f"[버튼] 초기화 실패 → 버튼 비활성화: {e}")

    # 3) OAK 연결
    print("\n[연결] OAK-D-Lite 시작 중...")
    try:
        with OakReader() as reader:
            usb = reader.get_usb_speed()
            if usb is not None:
                print(f"[연결] USB 속도: {usb}")
            print("[시작] 안내를 시작합니다. (Ctrl+C로 종료)\n")
            speaker.say("sys_start")

            # ── 장애물 안내 상태 ──
            current_obstacle_key = None
            obstacle_speak_count = 0      # 현재 키에서 발화한 횟수
            last_obstacle_speak_time = 0.0   # 마지막으로 '실제 발화'한 시각
            last_announced_steps = None   # 마지막으로 안내한 걸음 수(거리 갱신 판단용)

            # ── 좁은 통로 상태 ──
            in_narrow = False
            narrow_raw_streak_in = 0
            narrow_raw_streak_out = 0
            narrow_pending = False        # 진입 안내 대기(충돌로 못 나갔으면 계속 재시도)

            # ── 단차(계단/drop-off) 상태 ──
            dropoff_status = "flat"                       # 확정된 현재 단차 상태
            dropoff_raw_streak = {"flat": 0, "down": 0, "up": 0}
            last_dropoff_speak_time = 0.0

            try:
                while True:
                    obstacles = reader.get_obstacles(
                        front_half_width_m=front_half_width)
                    if obstacles is None:
                        time.sleep(0.02)
                        continue

                    tactile = reader.detect_tactile_paving()
                    situation, clearance = reader.get_open_direction(
                        narrow_side_m=narrow_threshold)
                    dropoff = reader.detect_dropoff() if ENABLE_DROPOFF else None
                    crosswalk = reader.detect_crosswalk()

                    # 버튼 핸들러(다른 스레드)가 읽을 최신 점자블록·횡단보도 상태 보관
                    button_state["tactile"] = tactile
                    button_state["crosswalk"] = crosswalk

                    if debug:
                        if obstacles:
                            info = [(o["label"], f"{o['distance_m']:.2f}m")
                                    for o in obstacles]
                            print(f"[디버그] 장애물 {info}")
                        if clearance is not None:
                            print(f"[디버그] 통로 L{clearance['left_m']:.2f}/"
                                  f"C{clearance['center_m']:.2f}/"
                                  f"R{clearance['right_m']:.2f} → {situation}")
                        if dropoff is not None:
                            fm = dropoff["floor_m"]
                            bm = dropoff["baseline_m"]
                            print(f"[디버그] 단차 {dropoff['status']:4} "
                                  f"floor={fm if fm is None else round(fm,2)} "
                                  f"base={bm if bm is None else round(bm,2)} "
                                  f"valid={dropoff['valid_ratio']:.2f}")

                    # ─────────────────────────────────────────────────
                    # 좁은 통로 상태 확정 + 이벤트 판정
                    # ─────────────────────────────────────────────────
                    narrow_event = None    # "enter" | None
                    is_narrow_now = (situation == "narrow")
                    if is_narrow_now:
                        narrow_raw_streak_in += 1
                        narrow_raw_streak_out = 0
                    else:
                        narrow_raw_streak_out += 1
                        narrow_raw_streak_in = 0

                    if (not in_narrow
                            and narrow_raw_streak_in >= NARROW_CONFIRM_FRAMES):
                        in_narrow = True
                        narrow_event = "enter"
                        narrow_pending = True   # 진입 안내 예약(나갈 때까지 재시도)
                    elif (in_narrow
                          and narrow_raw_streak_out >= NARROW_CONFIRM_FRAMES):
                        in_narrow = False
                        narrow_pending = False  # 통로를 벗어남 → 대기 취소

                    # ─────────────────────────────────────────────────
                    # (1) 장애물 안내
                    #     - 상태(등급/라벨/방향/회피)가 바뀌면 즉시 안내.
                    #     - 같은 상태가 유지되면 쿨다운 간격을 둬서 폭주 방지.
                    #     - 걸음수가 줄어드는 것만으로는 새 안내를 만들지 않는다.
                    # ─────────────────────────────────────────────────
                    center_m = clearance["center_m"] if clearance else None
                    target = pick_priority_obstacle(obstacles, center_m=center_m)
                    obstacle_announced_this_frame = False

                    # 회피 상황 (정면 장애물에만 의미)
                    avoid_sit = None
                    if target is not None and target["direction"] == "정면":
                        if situation in ("right", "left", "either", "blocked"):
                            avoid_sit = situation

                    new_key = make_obstacle_state_key(target, stride_m, avoid_sit)

                    if new_key is None:
                        # 안내할 장애물 없음
                        current_obstacle_key = None
                        obstacle_speak_count = 0
                        last_announced_steps = None
                    else:
                        safety = new_key[2]   # "stop" | "warn" | "ok"
                        prev_key = current_obstacle_key
                        prev_safety = (prev_key[2]
                                       if prev_key is not None else None)
                        key_changed = (new_key != prev_key)
                        appeared = (prev_key is None)   # 비어있다가 새 장애물 출현
                        # warn(또는 없음) → stop 으로 위급해진 경우만 '승격'
                        escalated_to_stop = (safety == "stop"
                                             and prev_safety != "stop")

                        # 현재 장애물까지의 걸음 수(거리 갱신 판단용)
                        cur_steps = distance_to_steps(
                            target["distance_m"], stride_m)

                        if key_changed:
                            # 상태 변화 → 새 이벤트
                            current_obstacle_key = new_key
                            obstacle_speak_count = 0

                        if safety == "ok":
                            pass   # 안전 등급은 안내 안 함
                        else:
                            now = time.time()
                            allowed = (STOP_MAX_REPEATS if safety == "stop" else 1)
                            cooldown = (STOP_SPEAK_COOLDOWN if safety == "stop"
                                        else WARN_SPEAK_COOLDOWN)
                            elapsed = now - last_obstacle_speak_time

                            # 같은 장애물에 STEP_REFRESH_DELTA 이상 가까워졌나
                            got_closer = (
                                last_announced_steps is not None
                                and cur_steps
                                <= last_announced_steps - STEP_REFRESH_DELTA)

                            # 발화 조건:
                            #   · 위급 승격(→stop) 또는 새 장애물 출현 → 즉시(빠른 반응).
                            #   · 다른 장애물로 바뀜(깜빡임 포함) → 최소 간격 지켜 1회.
                            #   · 같은 장애물인데 의미 있게 가까워짐 → 거리 갱신(최소 간격).
                            #   · 같은 상태 유지 → 횟수 한도 미만 + 쿨다운 경과.
                            can_speak = False
                            if escalated_to_stop or appeared:
                                can_speak = True
                            elif key_changed:
                                can_speak = (elapsed >= OBSTACLE_MIN_INTERVAL)
                            elif got_closer and elapsed >= OBSTACLE_MIN_INTERVAL:
                                can_speak = True
                                obstacle_speak_count = 0   # 거리 갱신은 새 안내로 취급
                            elif (obstacle_speak_count < allowed
                                  and elapsed >= cooldown):
                                can_speak = True

                            if can_speak:
                                guidance = build_guidance(
                                    target, stride_m, avoid_situation=avoid_sit)
                                chunks, text = guidance
                                if chunks is not None:
                                    speaker.say(guidance)
                                    obstacle_speak_count += 1
                                    last_obstacle_speak_time = now
                                    last_announced_steps = cur_steps
                                    obstacle_announced_this_frame = True

                    # ─────────────────────────────────────────────────
                    # (1.5) 단차(계단/drop-off) 안내
                    #     내려가는 단차는 낙상 위험이라 자동 안내(버튼 불필요).
                    #     연속 N프레임 확정 후, 위험 상태로 새로 진입하면 즉시 1회,
                    #     같은 위험 상태가 지속되면 쿨다운 간격마다 환기.
                    # ─────────────────────────────────────────────────
                    dropoff_announced_this_frame = False
                    if dropoff is not None:
                        raw = dropoff["status"]            # "flat" | "down" | "up"
                        for k in dropoff_raw_streak:
                            dropoff_raw_streak[k] = (
                                dropoff_raw_streak[k] + 1 if k == raw else 0)
                        confirmed = (dropoff_raw_streak[raw]
                                     >= DROPOFF_CONFIRM_FRAMES)

                        speak_dropoff = False
                        if confirmed and raw != dropoff_status:
                            # 상태가 새로 확정됨 (예: flat → down)
                            dropoff_status = raw
                            if dropoff_status in ("down", "up"):
                                speak_dropoff = True
                        elif (confirmed and raw == dropoff_status
                              and dropoff_status in ("down", "up")
                              and (time.time() - last_dropoff_speak_time
                                   >= DROPOFF_SPEAK_COOLDOWN)):
                            # 같은 위험 상태 지속 → 쿨다운마다 환기
                            speak_dropoff = True

                        if speak_dropoff:
                            g = build_dropoff_guidance(dropoff_status)
                            if g[0] is not None:
                                speaker.say(g)
                                last_dropoff_speak_time = time.time()
                                dropoff_announced_this_frame = True

                    # ─────────────────────────────────────────────────
                    # (2) 점자블록 안내 — 버튼(GPIO17)을 누를 때만.
                    # ─────────────────────────────────────────────────

                    # ─────────────────────────────────────────────────
                    # (3) 좁은 통로 진입 안내
                    #     진입 시 예약(narrow_pending)해두고, 위급 장애물·단차가
                    #     그 프레임에 안내됐거나 재생 중이면 보류 → 다음 프레임에 재시도.
                    #     성공하면 예약 해제. (한 번 충돌로 영영 삼켜지던 문제 해결)
                    # ─────────────────────────────────────────────────
                    if (narrow_pending
                            and not obstacle_announced_this_frame
                            and not dropoff_announced_this_frame
                            and not speaker.is_speaking()):
                        speaker.say(build_narrow_corridor_guidance())
                        narrow_pending = False

            except KeyboardInterrupt:
                print("\n[종료] 사용자 종료")
                speaker.say_now("sys_end")

    except FileNotFoundError as e:
        print(f"\n[오류] {e}")
        print("models 폴더에 blob 파일이 있는지 확인하세요.")
    except Exception as e:
        print(f"\n[오류] 장치 연결 실패: {e}")
        print("USB 연결과 케이블을 확인하세요.")


if __name__ == "__main__":
    main()