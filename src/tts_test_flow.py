#!/usr/bin/env python3
"""
gen_flow_mp3.py
---------------
데모용 '흐름' 전체를 하나의 mp3 파일로 만든다.

- 단어 조각을 잇는 대신, 문장을 통째로 gTTS로 생성해 음질이 자연스럽다.
- 안내 사이의 (N초 후) 시간은 무음으로 정확히 삽입한다.
- 전부 한 파일이라 블루투스가 사이사이 잠들어 앞 음절이 잘리는 문제가 없다.

필요 패키지 / 도구 (노트북에서 한 번만):
    pip install gTTS pydub
    그리고 ffmpeg 가 PATH 에 있어야 한다. (이미 winget 으로 설치돼 있음)
    ※ gTTS 는 인터넷이 필요하다(구글 TTS 호출).

실행:
    python src/gen_flow_mp3.py
결과:
    flow_demo.mp3  (이 파일을 재생/다운로드해서 데모에 사용)
"""
import os
import sys
import tempfile

OUT_FILE = "flow_demo.mp3"
BITRATE = "192k"          # 음질(높일수록 큼). 128k~256k 권장.

# 맨 앞 무음(초): 블루투스 이어폰이 깨어나기 전에 첫 음절이 잘리는 걸 막는다.
# 첫 단어가 여전히 끊기면 1.5~2.0 으로 늘린다.
LEAD_IN_SILENCE_SEC = 1.0

# 버튼(=Enter)을 누른 뒤 나오던 마지막 안내를, 단일 mp3에서는 시간 간격으로 처리.
BUTTON_GAP_SEC = 3.0      # 마지막 안내 전 무음(초). 원하는 만큼 조절.

# ── 흐름 정의 ─────────────────────────────────────────
# (앞에 둘 무음 초, 읽을 문장)
FLOW = [
    (0.0,            "안내를 시작합니다."),
    (2.0,            "주의. 여덟 걸음 앞에 식탁. 왼쪽으로 이동 가능."),
    (8.0,            "정지. 식탁. 왼쪽으로 이동."),
    (2.0,            "좁은 통로, 주의하세요."),
    (9.0,            "주의. 일곱 걸음 앞에 의자."),
    (7.0,            "정지. 의자. 막다른 길."),
    (BUTTON_GAP_SEC, "주변에 점자블록이나 횡단보도가 없습니다."),
]


def main():
    try:
        from gtts import gTTS
    except ImportError:
        print("[오류] gTTS 가 없습니다.  pip install gTTS pydub")
        sys.exit(1)
    try:
        from pydub import AudioSegment
    except ImportError:
        print("[오류] pydub 가 없습니다.  pip install gTTS pydub")
        sys.exit(1)

    tmp = tempfile.mkdtemp()
    # 맨 앞 무음으로 시작 → 블루투스 워밍업(첫 음절 끊김 방지)
    combined = AudioSegment.silent(duration=int(LEAD_IN_SILENCE_SEC * 1000))

    for i, (gap, text) in enumerate(FLOW, start=1):
        if gap > 0:
            combined += AudioSegment.silent(duration=int(gap * 1000))
        print(f"[{i}/{len(FLOW)}] (앞 무음 {gap:.0f}초) {text}")
        line_mp3 = os.path.join(tmp, f"line{i}.mp3")
        try:
            gTTS(text, lang="ko").save(line_mp3)   # 문장 전체를 자연스럽게 생성
        except Exception as e:
            print(f"[오류] gTTS 생성 실패(인터넷 확인): {e}")
            sys.exit(1)
        combined += AudioSegment.from_mp3(line_mp3)

    combined.export(OUT_FILE, format="mp3", bitrate=BITRATE)
    secs = len(combined) / 1000.0
    print(f"\n[완료] {OUT_FILE} 저장 (총 길이 {secs:.1f}초, {BITRATE})")


if __name__ == "__main__":
    main()