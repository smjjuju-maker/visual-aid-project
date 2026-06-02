"""
gen_voices.py
-------------
gTTS로 음성 '조각'들을 미리 생성하는 스크립트. (인터넷 있을 때 1회 실행)

[목적]
  - 실시간 gTTS 호출은 인터넷이 필요하므로, 보행 중(야외) 사용에 부적합.
  - 자주 쓰는 안내 조각들을 미리 mp3로 만들어두고,
    라파에서는 mpg123 으로 '재생만' 한다. (오프라인 동작)
  - ffmpeg/pydub 불필요 — gTTS가 만드는 mp3를 그대로 사용한다.

[사용]
  (인터넷 되는 PC/노트북에서)
  pip install gtts
  python src/gen_voices.py
  → src/voices/*.mp3 생성됨. 이 폴더를 라파로 옮기면 됨.

  (라파 재생 준비)
  sudo apt-get install -y mpg123

[조각 구성]
  등급: 정지/주의  위치: 정면  걸음: 한 걸음~서른 걸음  연결: 앞에
  물체: 사람/의자/소파/식탁/모니터/장애물  회피: 오른/왼/양옆
  통로: 좁은 통로  점자: 점자블록/곧 벗어남/시계방향  시스템: 시작/종료
"""

import os

try:
    from gtts import gTTS
except ImportError:
    raise SystemExit("gTTS가 없습니다.  pip install gtts")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "voices")

VOICE_CHUNKS = {
    "grade_stop": "정지.",
    "grade_warn": "주의.",
    "pos_front": "정면",
    "ape": "앞에",
    "obj_person": "사람.",
    "obj_chair": "의자.",
    "obj_sofa": "소파.",
    "obj_table": "식탁.",
    "obj_monitor": "모니터.",
    "obj_unknown": "장애물.",
    "avoid_right": "오른쪽으로 이동.",
    "avoid_left": "왼쪽으로 이동.",
    "avoid_both": "양옆으로 피할 수 있음.",
    "narrow": "좁은 통로, 주의하세요.",
    "tactile": "점자블록.",
    "tactile_leaving": "점자블록 곧 벗어남.",
    "tactile_none": "주변에 점자블록이 없습니다.",
    "clock_10": "열 시 방향",
    "clock_11": "열한 시 방향",
    "clock_12": "열두 시 방향",
    "clock_1": "한 시 방향",
    "clock_2": "두 시 방향",
    "sys_start": "안내를 시작합니다.",
    "sys_end": "안내를 종료합니다.",
}


def _korean_step(n):
    """걸음 수(1~30)를 순우리말로."""
    ones = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
    if n < 10:
        return ones[n]
    elif n == 10:
        return "열"
    elif n < 20:
        return "열" + ones[n - 10]
    elif n == 20:
        return "스무"
    elif n < 30:
        return "스물" + ones[n - 20]
    else:
        return "서른"


for _n in range(1, 31):
    VOICE_CHUNKS[f"step_{_n}"] = f"{_korean_step(_n)} 걸음"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    total = len(VOICE_CHUNKS)
    print(f"[gen_voices] {total}개 음성 조각(mp3) 생성 시작 → {OUT_DIR}")

    for i, (key, text) in enumerate(VOICE_CHUNKS.items(), 1):
        mp3_path = os.path.join(OUT_DIR, f"{key}.mp3")
        try:
            gTTS(text=text, lang="ko").save(mp3_path)
            print(f"  [{i:2}/{total}] {key:16} ← \"{text}\"")
        except Exception as e:
            print(f"  [오류] {key}: {e}")

    print(f"\n[완료] {OUT_DIR} 의 mp3 파일들을 라즈베리파이로 옮기세요.")
    print("       (라파 재생 준비: sudo apt-get install -y mpg123)")
    print("       (재생 테스트: mpg123 src/voices/grade_stop.mp3)")


if __name__ == "__main__":
    main()