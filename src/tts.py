"""
tts.py
------
음성 출력 모듈 (gTTS로 미리 만든 mp3 조각을 mpg123으로 재생, 오프라인).

[동작]
  - gen_voices.py 로 만들어 둔 voices/*.mp3 조각을 순서대로 재생한다.
  - 안내는 "조각 키 리스트"로 들어온다. 예:
      ["grade_warn","pos_front","step_2","ape","obj_chair","avoid_right"]
    → 주의. 정면. 두 걸음. 앞에. 의자. 오른쪽으로 이동.
  - 재생은 백그라운드 스레드에서 하여 메인 루프(카메라)를 막지 않는다.

[인터럽트 — 핵심]
  - say_now()(긴급/정지용)는 현재 재생 중인 조각 시퀀스를 즉시 중단하고
    새 시퀀스를 처음부터 재생한다.
  - 구현: 재생 중인 mpg123 프로세스를 kill + 진행 중 스레드에 취소 신호.
    "안내 재생 중 빨리 걸어 충돌 임박" 상황에서 stop이 바로 끼어든다.

[환경]
  - 라즈베리파이 + 블루투스 골전도 이어폰(OS 기본 출력 장치).
  - 재생기: mpg123 (mp3). 라파에 설치 필요: sudo apt-get install -y mpg123
  - dry_run=True 면 소리 없이 화면 출력만(PC 테스트).
"""

import os
import time
import threading
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(SCRIPT_DIR, "voices")

# 조각 키 → 화면표시용 한글(폴백). dry-run에서 chunks만 있고 text가 없을 때 사용.
_CHUNK_KO = {
    "grade_stop": "정지.", "grade_warn": "주의.", "pos_front": "정면",
    "ape": "앞에", "narrow": "좁은 통로, 주의하세요.",
    "obj_person": "사람.", "obj_chair": "의자.", "obj_sofa": "소파.",
    "obj_table": "식탁.", "obj_monitor": "모니터.", "obj_unknown": "장애물.",
    "avoid_right": "오른쪽으로 이동.", "avoid_left": "왼쪽으로 이동.",
    "avoid_both": "양옆으로 피할 수 있음.",
    "tactile": "점자블록.", "tactile_leaving": "점자블록 곧 벗어남.",
    "tactile_none": "주변에 점자블록이 없습니다.",
    "sys_start": "안내를 시작합니다.", "sys_end": "안내를 종료합니다.",
}


def _normalize(item):
    """안내 입력을 (chunks, text)로 정규화.
       - (chunks, text) 튜플이면 그대로
       - 조각 키 리스트면 text는 한글 조합으로 생성
       - 단일 문자열(조각 키 or 일반 텍스트)도 허용
    """
    if item is None:
        return None, None
    if isinstance(item, tuple) and len(item) == 2:
        return item
    if isinstance(item, list):
        text = " ".join(_CHUNK_KO.get(k, k) for k in item)
        return item, text
    if isinstance(item, str):
        # 조각 키면 그 키 하나, 아니면 일반 텍스트(조각 없음)
        if item in _CHUNK_KO:
            return [item], _CHUNK_KO[item]
        return [], item
    return None, None


class Speaker:
    """미리 만든 wav 조각을 aplay로 순차 재생. say_now는 인터럽트."""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self._lock = threading.Lock()
        self._proc = None             # 현재 재생 중인 mpg123 프로세스
        self._gen = 0                 # 재생 세대(인터럽트로 무효화 판단)
        self._speaking = False
        if not dry_run and not os.path.isdir(VOICES_DIR):
            print(f"[TTS] voices 폴더 없음: {VOICES_DIR}")
            print("      gen_voices.py 를 먼저 실행해 wav를 만들어 주세요.")

    def is_speaking(self):
        return self._speaking

    def _wav(self, key):
        return os.path.join(VOICES_DIR, f"{key}.mp3")

    def _play_sequence(self, chunks, my_gen):
        """조각들을 '한 번의 mpg123 호출'로 연속 재생한다.
        파일을 하나씩 따로 띄우면 단어마다 프로세스 지연 + 무음이 끼어
        뚝뚝 끊긴다. mpg123은 인자로 받은 mp3들을 한 프로세스에서
        연달아(거의 끊김 없이) 재생하므로 멘트가 짧고 빨라진다.
        세대(my_gen)가 바뀌면(인터럽트) 프로세스를 죽여 즉시 멈춘다."""
        self._speaking = True
        try:
            if my_gen != self._gen:
                return                          # 시작 전에 이미 인터럽트됨
            paths = [self._wav(k) for k in chunks]
            paths = [p for p in paths if os.path.exists(p)]
            if not paths:
                return
            try:
                proc = subprocess.Popen(
                    ["mpg123", "-q"] + paths,   # 조각 전부를 한 번에
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                print("[TTS 오류] mpg123 없음 (sudo apt-get install -y mpg123)")
                return
            with self._lock:
                self._proc = proc
            proc.wait()
            with self._lock:
                if self._proc is proc:
                    self._proc = None
        finally:
            if my_gen == self._gen:
                self._speaking = False

    def _start(self, chunks, interrupt):
        """재생 시작. interrupt=True면 진행 중인 재생을 끊고 새로 시작."""
        with self._lock:
            if interrupt:
                self._gen += 1                  # 기존 시퀀스 무효화
                if self._proc is not None:
                    try:
                        self._proc.kill()       # 재생 중 mpg123 즉시 종료
                    except Exception:
                        pass
                    self._proc = None
            elif self._speaking:
                return                          # 일반 안내는 재생 중이면 양보
            my_gen = self._gen
        t = threading.Thread(target=self._play_sequence,
                             args=(chunks, my_gen), daemon=True)
        t.start()

    def say(self, item):
        """일반 안내. 재생 중이면 양보(겹치지 않음)."""
        chunks, text = _normalize(item)
        if not chunks and not text:
            return
        if self.dry_run:
            print(f"[음성] {text}")
            return
        self._start(chunks, interrupt=False)

    def say_now(self, item):
        """긴급/정지 안내. 진행 중 재생을 끊고 즉시 재생(인터럽트)."""
        chunks, text = _normalize(item)
        if not chunks and not text:
            return
        if self.dry_run:
            print(f"[음성!] {text}")
            return
        self._start(chunks, interrupt=True)