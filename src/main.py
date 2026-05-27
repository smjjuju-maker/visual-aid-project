"""
main.py
-------
시각 보조 시스템 메인 루프.

[흐름]
  1. 사용자 보폭 확보 (저장값 있으면 사용, 없으면 최초 1회 보정)
  2. OAK-D-Lite 연결
  3. 반복:
       - 장애물 거리/방향 측정 (oak_reader)
       - 가장 가까운 장애물 선택
       - 거리 → 걸음 수 환산 + 안전 판단 (step_converter)
       - 음성 안내 (tts)

[실행]
  python main.py                # 일반 실행
  python main.py --recalibrate  # 보폭 다시 측정
  python main.py --dry-run      # 음성 없이 화면 출력만 (PC 테스트용)
"""

import sys
import time

from oak_reader import OakReader
from step_converter import get_user_stride, build_guidance, assess_safety
from tts import Speaker

# ── 설정 ──────────────────────────────────────────────
ANNOUNCE_INTERVAL = 2.0    # 주의 안내 최소 간격(초)
STOP_INTERVAL = 1.0        # 정지 경고 최소 간격(초) — 더 자주, 단 도배 방지


def pick_priority_obstacle(obstacles):
    """안내할 장애물 1개 선택.

    우선순위: (1) 진행 경로상의 정면 장애물을 최우선,
              (2) 그중에서 가장 가까운 것,
              (3) 정면에 아무것도 없으면 좌우 중 가장 가까운 것.
    """
    if not obstacles:
        return None
    front = [o for o in obstacles if o["direction"] == "정면"]
    if front:
        return min(front, key=lambda o: o["distance_m"])
    return min(obstacles, key=lambda o: o["distance_m"])


def main():
    keep_stride = "--keep-stride" in sys.argv   # 저장된 보폭 재사용(개발용)
    dry_run = "--dry-run" in sys.argv
    debug = "--debug" in sys.argv

    print("=" * 60)
    print("  시각 보조 시스템 (걸음 수 기반 장애물 안내)")
    print("=" * 60)

    # 1) 사용자 보폭 확보
    #    기본: 시작할 때마다 새로 보정 (시연 때 사용자가 바뀔 수 있으므로)
    #    --keep-stride: 저장된 값 재사용 (개발/반복 테스트용)
    stride_m = get_user_stride(force_recalibrate=not keep_stride)

    # 2) 음성 엔진 준비
    speaker = Speaker(dry_run=dry_run)

    # 3) OAK-D-Lite 연결
    print("\n[연결] OAK-D-Lite 시작 중...")
    try:
        with OakReader() as reader:
            usb = reader.get_usb_speed()
            if usb is not None:
                print(f"[연결] USB 속도: {usb}")
            print("[시작] 안내를 시작합니다. (Ctrl+C로 종료)\n")
            speaker.say("안내를 시작합니다.")

            last_announce_time = 0.0
            last_text = None          # 직전에 안내한 문구 (거리 변화 감지용)

            try:
                while True:
                    obstacles = reader.get_obstacles()
                    if obstacles is None:
                        time.sleep(0.02)
                        continue

                    if debug and obstacles:
                        info = [(o["label"],
                                 f"{o['distance_m']:.2f}m",
                                 f"raw {o['raw_distance_m']:.2f}")
                                for o in obstacles]
                        print(f"[디버그] {info}")

                    target = pick_priority_obstacle(obstacles)
                    if target is None:
                        continue

                    safety = assess_safety(target["distance_m"], stride_m)
                    now = time.time()

                    # 안전(ok) 등급은 안내하지 않음 (조용)
                    if safety == "ok":
                        last_text = None   # 멀어졌다 다시 가까워지면 새로 안내되도록
                        continue

                    # 정면 장애물이면(주의/정지 단계) → depth로 회피 상황 판단
                    avoid_sit = None
                    if target["direction"] == "정면":
                        situation, clearance = reader.get_open_direction()
                        avoid_sit = situation
                        if debug and clearance is not None:
                            print(f"[회피] 좌 {clearance['left_m']:.2f}m / "
                                  f"중 {clearance['center_m']:.2f}m / "
                                  f"우 {clearance['right_m']:.2f}m → {situation}")

                    text = build_guidance(target, stride_m, avoid_situation=avoid_sit)
                    if text is None:
                        continue

                    # 발화 중이면 말이 끝날 때까지 기다림 (말 겹침 방지)
                    if speaker.is_speaking():
                        continue

                    if safety == "stop":
                        # 정지: 안전상, 내용이 같아도 1초마다 계속 경고
                        if now - last_announce_time >= STOP_INTERVAL:
                            speaker.say_now(text)
                            last_announce_time = now
                            last_text = text
                    else:  # warn
                        # 주의: 내용(걸음수/방향/물체)이 바뀌었을 때만 재안내,
                        #       단 같은 내용이라도 2초 지나면 한 번 더 환기
                        changed = (text != last_text)
                        elapsed = (now - last_announce_time >= ANNOUNCE_INTERVAL)
                        if changed or elapsed:
                            speaker.say(text)
                            last_announce_time = now
                            last_text = text

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