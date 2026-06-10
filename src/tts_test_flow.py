#!/usr/bin/env python3
"""
tts_flow_test.py
----------------
카메라/센서 없이, 미리 정해 둔 '흐름'을 시간 순서대로 실제 TTS(voices/*.mp3)로
재생하는 데모/테스트 스크립트.

안내 멘트는 새로 만들지 않고, 코드에서 쓰는 음성 조각(gen_voices.py 의
VOICE_CHUNKS 키)을 그대로 이어 붙여 재생한다. → "멘트는 코드에 맞게".

실행:
  라파(실제 음성):   python src/tts_flow_test.py
  노트북(소리 없이):  python src/tts_flow_test.py --dry-run
  버튼 단계:          해당 차례가 되면 Enter 키를 누르면 '버튼 누름'으로 처리

각 항목은 (앞 안내가 끝난 뒤 기다릴 초, [조각 키들], 화면표시 텍스트, 버튼대기?).
앞 안내 재생이 '끝난 다음' 그 초만큼 기다렸다가 다음 안내를 낸다(겹치지 않음).
"""
import sys
import time

from tts import Speaker

# ── 흐름 정의 (요청하신 시나리오) ─────────────────────
SCENARIO = [
    # gap(초), 조각 키들, 표시 텍스트, 버튼대기
    (0.0, ["sys_start"],
          "안내를 시작합니다.", False),
    (2.0, ["grade_stop", "step_8", "ape", "obj_table"],
          "정지. 여덟 걸음 앞에 식탁.", False),
    (8.0, ["avoid_left"],
          "왼쪽으로 이동.", False),
    (2.0, ["narrow"],
          "좁은 통로, 주의하세요.", False),
    (9.0, ["grade_warn", "step_7", "ape", "obj_chair"],
          "주의. 일곱 걸음 앞에 의자.", False),
    (7.0, ["grade_stop"],
          "정지.", False),
    (0.0, ["crosswalk", "tactile_none"],
          "횡단보도. 주변에 점자블록이 없습니다.", True),   # ← 버튼 누른 후
]


def speak_and_wait(speaker, chunks, text):
    """한 안내를 재생하고 끝날 때까지 기다린다(다음 안내와 겹치지 않게)."""
    speaker.say((chunks, text))
    # say()는 비동기(별도 스레드). 재생이 끝날 때까지 대기.
    # dry_run이면 is_speaking()이 계속 False라 즉시 통과(화면 출력만).
    time.sleep(0.05)
    while speaker.is_speaking():
        time.sleep(0.05)


def main():
    dry_run = "--dry-run" in sys.argv
    speaker = Speaker(dry_run=dry_run)

    print("=" * 52)
    print("  TTS 흐름 테스트" + ("  (--dry-run: 소리 없음)" if dry_run else ""))
    print("=" * 52)

    for i, (gap, chunks, text, wait_button) in enumerate(SCENARIO, start=1):
        if wait_button:
            input("\n[버튼] Enter 를 누르면 버튼을 누른 것으로 처리합니다... ")
        elif gap > 0:
            time.sleep(gap)
        print(f"[{i}] {text}")
        speak_and_wait(speaker, chunks, text)

    print("\n[완료] 흐름 재생 끝.")


if __name__ == "__main__":
    main()