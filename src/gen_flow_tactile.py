#!/usr/bin/env python3
"""
gen_flow_tactile.py  — <점자블록 시나리오> 테스트 음성을 하나의 mp3로 만든다.
멘트는 코드(step_converter.py)에 정해진 문구 그대로 사용.

실행:  python src/gen_flow_tactile.py   →  flow_tactile.mp3
필요:  pip install gTTS pydub  +  ffmpeg  (인터넷 필요)
"""
import os, sys, tempfile

OUT_FILE = "flow_tactile.mp3"
BITRATE = "192k"
LEAD_IN_SILENCE_SEC = 1.0     # 맨 앞 무음(블루투스 첫 음절 끊김 방지)
BUTTON_GAP = 3.0              # 버튼(=Enter) 누른 뒤 안내 전 간격(초)

# (앞 무음 초, 문장) — 코드 문구 그대로
FLOW = [
    (0.0,        "안내를 시작합니다."),
    (BUTTON_GAP, "열두 시 방향 네 걸음 앞에 점자블록."),   # ← 버튼 누른 후
]


def main():
    try:
        from gtts import gTTS
        from pydub import AudioSegment
    except ImportError:
        print("[오류] 패키지 없음.  pip install gTTS pydub"); sys.exit(1)

    tmp = tempfile.mkdtemp()
    combined = AudioSegment.silent(duration=int(LEAD_IN_SILENCE_SEC * 1000))
    for i, (gap, text) in enumerate(FLOW, start=1):
        if gap > 0:
            combined += AudioSegment.silent(duration=int(gap * 1000))
        print(f"[{i}/{len(FLOW)}] (앞 무음 {gap:.0f}초) {text}")
        line = os.path.join(tmp, f"line{i}.mp3")
        try:
            gTTS(text, lang="ko").save(line)
        except Exception as e:
            print(f"[오류] gTTS 실패(인터넷 확인): {e}"); sys.exit(1)
        combined += AudioSegment.from_mp3(line)
    combined.export(OUT_FILE, format="mp3", bitrate=BITRATE)
    print(f"\n[완료] {OUT_FILE} 저장 ({len(combined)/1000:.1f}초)")


if __name__ == "__main__":
    main()