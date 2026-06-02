"""
button_test.py
--------------
푸시버튼 배선 확인용 테스트 스크립트.
버튼(GPIO17 + GND)을 누르면 "연결되었습니다" 음성이 나온다.

[준비]
  1) 음성 파일 생성 (인터넷 되는 곳에서 1회):
       pip install gtts
       python -c "from gtts import gTTS; gTTS('연결되었습니다.', lang='ko').save('src/voices/test_connected.mp3')"
  2) 라파에 재생기/GPIO 라이브러리 확인:
       sudo apt-get install -y mpg123
       (gpiozero는 라즈베리파이OS에 보통 기본 설치됨)

[실행]
  python src/button_test.py
  → 버튼 누를 때마다 "연결되었습니다" 재생. Ctrl+C로 종료.

[배선]
  버튼 한쪽 → GPIO17 (물리 11번 핀)
  버튼 반대쪽 → GND (물리 9번 핀)
  (내부 풀업 사용, 외부 저항 불필요)
"""

import os
import time
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_FILE = os.path.join(SCRIPT_DIR, "voices", "test_connected.mp3")

BUTTON_PIN = 17   # BCM 번호 (물리 11번 핀)


def play_voice():
    """연결 확인 음성 재생 (mpg123)."""
    if not os.path.exists(VOICE_FILE):
        print(f"[경고] 음성 파일 없음: {VOICE_FILE}")
        print("       먼저 test_connected.mp3 를 만들어 주세요. (위 주석 참고)")
        return
    try:
        subprocess.Popen(["mpg123", "-q", VOICE_FILE],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("[오류] mpg123 없음 (sudo apt-get install -y mpg123)")


def main():
    try:
        from gpiozero import Button
    except ImportError:
        raise SystemExit(
            "gpiozero가 없습니다. 라즈베리파이에서 실행하세요.\n"
            "  sudo apt-get install -y python3-gpiozero"
        )

    # pull_up=True: 내부 풀업 사용 → 누르면 LOW = '눌림'. 외부 저항 불필요.
    button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.05)

    print("=" * 50)
    print(f"  버튼 테스트 시작 (GPIO{BUTTON_PIN}, 물리 11번 핀)")
    print("  버튼을 누르면 '연결되었습니다' 음성이 나옵니다.")
    print("  Ctrl+C 로 종료.")
    print("=" * 50)

    press_count = 0

    def on_press():
        nonlocal press_count
        press_count += 1
        print(f"[버튼] 눌림 #{press_count} → 음성 재생")
        play_voice()

    button.when_pressed = on_press

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[종료] 테스트 종료")


if __name__ == "__main__":
    main()