"""
main.py
-------
시각 보조 시스템 메인 루프.

[안내 정책]
  - 장애물(stop): 같은 상태일 때 최대 2회만 발화 후 조용. 상태가 바뀌면 리셋.
  - 장애물(warn): 같은 상태일 때 1회만. 상태가 바뀌면 다시.
  - 안내 최소 간격(쿨다운): 카메라가 1초에 여러 번(예: 20fps) 도므로, 같은
    상황이 유지되는 동안 매 프레임 안내가 쏟아지지 않도록 마지막 안내로부터
    일정 시간이 지나야 다음 안내를 내보낸다. 이것이 "정지 정지 정지" 폭주와
    누적 지연을 막는 핵심이다. (stop은 짧게, warn은 길게)
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
    build_tactile_query_guidance,
    distance_to_steps,
    assess_safety,
)
from tts import Speaker

# ── 안내 정책 상수 ────────────────────────────────────
STOP_MAX_REPEATS = 2          # 같은 stop 상태에서 최대 2회까지 발화
STOP_REPEAT_INTERVAL = 1.0    # stop 두 번 발화 사이 최소 간격(초)

# ── 안내 최소 간격(쿨다운) ────────────────────────────
#   카메라 루프는 1초에 여러 번(예: 20fps) 돈다. 같은 상황이 유지되는 동안
#   매 프레임 안내를 던지면 "정지 정지 정지…"처럼 폭주하고, 펜딩이 누적돼
#   실제 상황보다 안내가 늦어진다(지연). 그래서 마지막으로 '실제 발화'한
#   시각으로부터 아래 간격이 지나기 전에는 새 안내를 내보내지 않는다.
#     · stop: 위급하므로 비교적 짧게(자주 갱신 허용)
#     · warn: 여유 있으므로 길게(불필요한 반복 억제)
#   상태 키가 '바뀌면'(다른 장애물/방향 등) 이 쿨다운과 무관하게 즉시 안내한다.
STOP_SPEAK_COOLDOWN = 1.5     # 같은 정지 상황 반복 안내 최소 간격(초)
WARN_SPEAK_COOLDOWN = 3.0     # 같은 주의 상황 반복 안내 최소 간격(초)

# 점자블록 "곧 벗어남" 판정: 노란 영역의 먼 끝이 이 걸음수 이내면 발화
TACTILE_LEAVING_STEPS = 4

# 깜빡임 방지(hysteresis): 연속 N프레임 같은 상태가 잡혀야 확정
TACTILE_CONFIRM_FRAMES = 3
NARROW_CONFIRM_FRAMES = 3

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
    (라벨, 걸음수, 방향, 안전등급, 회피상황)"""
    if target is None:
        return None
    steps = distance_to_steps(target["distance_m"], stride_m)
    safety = assess_safety(target["distance_m"], stride_m)
    return (target["label"], steps, target["direction"], safety, avoid_situation)


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

    # 2-1) 점자블록 조회 버튼 (GPIO17). 누르면 현재 점자블록 상태를 안내.
    button = None
    button_state = {"latest": None}   # 루프가 최신 점자블록 측정값을 넣어줌
    try:
        from gpiozero import Button
        button = Button(17, pull_up=True, bounce_time=0.05)

        def on_button_press():
            guidance = build_tactile_query_guidance(
                button_state["latest"], stride_m)
            speaker.say_now(guidance)   # 버튼 응답은 즉시(인터럽트)

        button.when_pressed = on_button_press
        print("[버튼] 점자블록 조회 버튼 준비 완료 (GPIO17)")
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

            # ── 좁은 통로 상태 ──
            in_narrow = False
            narrow_raw_streak_in = 0
            narrow_raw_streak_out = 0

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

                    # 버튼 핸들러(다른 스레드)가 읽을 최신 점자블록 상태 보관
                    button_state["latest"] = tactile

                    if debug:
                        if obstacles:
                            info = [(o["label"], f"{o['distance_m']:.2f}m")
                                    for o in obstacles]
                            print(f"[디버그] 장애물 {info}")
                        if clearance is not None:
                            print(f"[디버그] 통로 L{clearance['left_m']:.2f}/"
                                  f"C{clearance['center_m']:.2f}/"
                                  f"R{clearance['right_m']:.2f} → {situation}")

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
                    elif (in_narrow
                          and narrow_raw_streak_out >= NARROW_CONFIRM_FRAMES):
                        in_narrow = False

                    # ─────────────────────────────────────────────────
                    # (1) 장애물 안내
                    #     - 상태가 바뀌면 즉시 안내(쿨다운 무시).
                    #     - 같은 상태가 유지되면 STOP/WARN_SPEAK_COOLDOWN 간격을
                    #       둬서 매 프레임 폭주하지 않게 한다.
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
                    else:
                        safety = new_key[3]   # "stop" | "warn" | "ok"
                        key_changed = (new_key != current_obstacle_key)

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

                            # 발화 조건:
                            #   · 상태가 막 바뀌었으면(key_changed) 즉시 1회 허용.
                            #   · 같은 상태면 발화 횟수가 한도 미만 + 쿨다운 경과.
                            can_speak = False
                            if key_changed:
                                can_speak = True
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
                                    obstacle_announced_this_frame = True

                    # ─────────────────────────────────────────────────
                    # (2) 점자블록 안내 — 버튼(GPIO17)을 누를 때만.
                    # ─────────────────────────────────────────────────

                    # ─────────────────────────────────────────────────
                    # (3) 좁은 통로 진입 안내
                    #     위급 장애물이 이번 프레임에 안내됐거나 재생 중이면 보류
                    # ─────────────────────────────────────────────────
                    if (narrow_event == "enter"
                            and not obstacle_announced_this_frame
                            and not speaker.is_speaking()):
                        speaker.say(build_narrow_corridor_guidance())

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