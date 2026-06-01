"""
main.py
-------
시각 보조 시스템 메인 루프.

[안내 정책]
  - 장애물(stop): 같은 상태(거리/방향/라벨/등급)일 때 최대 2회만 발화 후 조용.
                  상태가 바뀌면 카운터 리셋.
  - 장애물(warn): 같은 상태일 때 1회만. 상태가 바뀌면 다시.
  - 점자블록(자동): "있다"가 새로 확정될 때 1회 + 노란 영역의 먼 끝이
                    4걸음 이내가 됐을 때 "곧 벗어남" 1회. 사후 안내는 없음.
  - 좁은 통로: 진입 시 1회. (위급 장애물이 그 프레임에 안내됐다면 보류)
  - 모든 판정은 깜빡임 방지 위해 hysteresis (연속 N프레임 확정) 적용.

[흐름]
  1. 사용자 보폭 + 어깨너비 확보
  2. OAK-D-Lite 연결
  3. 반복: 장애물 → 점자블록 → 좁은 통로 순으로 이벤트 판정 후 안내

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
    build_tactile_appear_guidance,
    distance_to_steps,
    assess_safety,
)
from tts import Speaker

# ── 안내 정책 상수 ────────────────────────────────────
STOP_MAX_REPEATS = 2          # 같은 stop 상태에서 최대 2회까지 발화
STOP_REPEAT_INTERVAL = 1.0    # stop 두 번 발화 사이 최소 간격(초)

# 점자블록 "곧 벗어남" 판정: 노란 영역의 먼 끝이 이 걸음수 이내면 발화
TACTILE_LEAVING_STEPS = 4

# 깜빡임 방지(hysteresis): 연속 N프레임 같은 상태가 잡혀야 확정
TACTILE_CONFIRM_FRAMES = 3
NARROW_CONFIRM_FRAMES = 3


def pick_priority_obstacle(obstacles):
    """안내할 장애물 1개 선택.

    [선택지 A] 정면(사용자 진행 경로) 장애물만 안내한다.
    양옆 장애물은 진행 경로를 막지 않으므로 무시한다.
    정면에 여러 개면 가장 가까운 것.
    정면에 아무것도 없으면 None (조용).
    """
    if not obstacles:
        return None
    front = [o for o in obstacles if o["direction"] == "정면"]
    if not front:
        return None
    return min(front, key=lambda o: o["distance_m"])


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

    # 3) OAK 연결
    print("\n[연결] OAK-D-Lite 시작 중...")
    try:
        with OakReader() as reader:
            usb = reader.get_usb_speed()
            if usb is not None:
                print(f"[연결] USB 속도: {usb}")
            print("[시작] 안내를 시작합니다. (Ctrl+C로 종료)\n")
            speaker.say("안내를 시작합니다.")

            # ── 장애물 안내 상태 ──
            # 같은 상태 키가 유지되는 동안 stop은 N회까지, warn은 1회만 발화.
            current_obstacle_key = None
            obstacle_speak_count = 0      # 현재 키에서 발화한 횟수
            last_obstacle_speak_time = 0.0

            # ── 점자블록 상태 ──
            tactile_present = False
            tactile_raw_streak_present = 0
            tactile_raw_streak_absent = 0
            tactile_leaving_announced = False   # 현재 점자블록 구간에서 '곧 벗어남' 했나
            tactile_leaving_streak = 0          # 연속으로 '먼 끝 가까움' 잡힌 프레임 수

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

                    if debug:
                        if obstacles:
                            info = [(o["label"], f"{o['distance_m']:.2f}m")
                                    for o in obstacles]
                            print(f"[디버그] 장애물 {info}")
                        if tactile is not None:
                            print(f"[디버그] 점자블록 {tactile}")
                        if clearance is not None:
                            print(f"[디버그] 통로 L{clearance['left_m']:.2f}/"
                                  f"C{clearance['center_m']:.2f}/"
                                  f"R{clearance['right_m']:.2f} → {situation}")

                    # ─────────────────────────────────────────────────
                    # 점자블록 상태 확정 + 이벤트 판정
                    # ─────────────────────────────────────────────────
                    tactile_event = None   # "appear" | "leaving" | None
                    if tactile is not None:
                        if tactile["present"]:
                            tactile_raw_streak_present += 1
                            tactile_raw_streak_absent = 0
                        else:
                            tactile_raw_streak_absent += 1
                            tactile_raw_streak_present = 0

                        # 새로 나타남 확정
                        if (not tactile_present
                                and tactile_raw_streak_present >= TACTILE_CONFIRM_FRAMES):
                            tactile_present = True
                            tactile_leaving_announced = False
                            tactile_leaving_streak = 0
                            tactile_event = "appear"
                        # 완전 사라짐 확정 → 사후 안내는 안 함. 상태만 리셋.
                        elif (tactile_present
                              and tactile_raw_streak_absent >= TACTILE_CONFIRM_FRAMES):
                            tactile_present = False
                            tactile_leaving_announced = False
                            tactile_leaving_streak = 0

                        # 점자블록 위인 동안 '먼 끝이 곧'인지 확인
                        if (tactile_present
                                and tactile["present"]
                                and not tactile_leaving_announced):
                            far_m = tactile.get("far_end_distance_m")
                            if far_m is not None and far_m > 0:
                                far_steps = distance_to_steps(far_m, stride_m)
                                if far_steps <= TACTILE_LEAVING_STEPS:
                                    tactile_leaving_streak += 1
                                else:
                                    tactile_leaving_streak = 0

                                if tactile_leaving_streak >= TACTILE_CONFIRM_FRAMES:
                                    tactile_event = "leaving"
                                    tactile_leaving_announced = True

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
                    # (1) 장애물 안내 — 상태 키 기반
                    # ─────────────────────────────────────────────────
                    target = pick_priority_obstacle(obstacles)
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

                        if new_key != current_obstacle_key:
                            # 상태 변화 → 새 이벤트
                            current_obstacle_key = new_key
                            obstacle_speak_count = 0

                        if safety == "ok":
                            # 안전 등급은 안내 안 함
                            pass
                        else:
                            # 발화 횟수 한도 체크
                            allowed = (STOP_MAX_REPEATS if safety == "stop" else 1)
                            if obstacle_speak_count < allowed:
                                # stop의 두 번째 발화는 최소 간격 둔다
                                now = time.time()
                                can_speak = True
                                if (safety == "stop"
                                        and obstacle_speak_count >= 1
                                        and now - last_obstacle_speak_time
                                            < STOP_REPEAT_INTERVAL):
                                    can_speak = False

                                if can_speak and not speaker.is_speaking():
                                    text = build_guidance(target, stride_m,
                                                          avoid_situation=avoid_sit)
                                    if text is not None:
                                        if safety == "stop":
                                            speaker.say_now(text)
                                        else:
                                            speaker.say(text)
                                        obstacle_speak_count += 1
                                        last_obstacle_speak_time = now
                                        obstacle_announced_this_frame = True

                    # ─────────────────────────────────────────────────
                    # (2) 점자블록 안내 (장애물과 공존 가능. is_speaking으로 양보)
                    # ─────────────────────────────────────────────────
                    if tactile_event is not None and not speaker.is_speaking():
                        if tactile_event == "appear":
                            t_text = build_tactile_appear_guidance(
                                tactile["clock_direction"],
                                tactile["distance_m"],
                                stride_m,
                            )
                        else:  # "leaving"
                            t_text = "점자블록 곧 벗어남."
                        speaker.say(t_text)

                    # ─────────────────────────────────────────────────
                    # (3) 좁은 통로 진입 안내
                    #     위급 장애물이 이번 프레임에 안내됐다면 보류
                    # ─────────────────────────────────────────────────
                    if (narrow_event == "enter"
                            and not obstacle_announced_this_frame
                            and not speaker.is_speaking()):
                        speaker.say(build_narrow_corridor_guidance())

            except KeyboardInterrupt:
                print("\n[종료] 사용자 종료")
                speaker.say_now("안내를 종료합니다.")

    except FileNotFoundError as e:
        print(f"\n[오류] {e}")
        print("models 폴더에 blob 파일이 있는지 확인하세요.")
    except Exception as e:
        print(f"\n[오류] 장치 연결 실패: {e}")
        print("USB 연결과 케이블을 확인하세요.")


if __name__ == "__main__":
    main()