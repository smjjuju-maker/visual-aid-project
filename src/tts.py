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
  - 한 안내의 여러 조각은 단일 mpg123 프로세스로 연속 재생한다(청크 간 갭 제거).
  - 맨 앞에 짧은 무음(_silence.mp3)을 끼워 블루투스 스피커를 미리 깨운다
    (절전에서 깨어나며 첫 멘트 앞부분이 잘리는 문제 방지). 단, 연속 재생
    체인의 첫 안내에만 붙인다(이미 깨어있는 이어 재생엔 불필요).

[겹침 방지 — 펜딩 슬롯(핵심)]
  - say()는 진행 중인 안내를 끊지 않는다(끝까지 재생).
  - 재생 중에 새 say()가 오면 큐에 쌓지 않고 '펜딩 슬롯 1칸'을 최신 것으로
    계속 덮어쓴다. 재생이 끝나면 펜딩에 남은 '가장 최신' 하나만 이어서 재생.
    → 안내가 누적되어 지연되는 일 없이, 항상 최신 상황만 안내된다.
  - 안전장치: 펜딩에 stop(정지)이 대기 중이면, 그보다 약한 warn 등이
    덮어쓰지 못한다(stop은 stop 또는 더 최신 stop으로만 교체).

[인터럽트]
  - say_now()는 현재 재생을 즉시 중단하고 새 안내를 처음부터 재생한다.
    (현재는 종료 안내(sys_end) 같은 즉시성 필요 케이스용. 장애물 안내는
     겹침 방지를 위해 say()의 펜딩 슬롯 방식을 쓴다.)

[환경]
  - 라즈베리파이 + 블루투스 골전도 이어폰/스피커(OS 기본 출력 장치).
  - 재생기: mpg123 (mp3). 라파에 설치 필요: sudo apt-get install -y mpg123
  - 무음 파일: voices/_silence.mp3. 없으면 워밍업 없이 동작.
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


def _is_stop(chunks):
    """안내가 '정지(stop)' 안내인지. 첫 조각이 grade_stop이면 stop."""
    return bool(chunks) and chunks[0] == "grade_stop"


class Speaker:
    """미리 만든 mp3 조각을 mpg123으로 연속 재생.
       say는 진행 중이면 양보하고 '최신'만 펜딩 슬롯에 보류했다 이어 재생.
    """

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self._lock = threading.Lock()
        self._proc = None             # 현재 재생 중인 mpg123 프로세스
        self._gen = 0                 # 재생 세대(인터럽트/새 재생 식별)
        self._speaking = False
        self._pending = None          # 재생 중 들어온 '최신' 안내 1개(chunks)
        if not dry_run and not os.path.isdir(VOICES_DIR):
            print(f"[TTS] voices 폴더 없음: {VOICES_DIR}")
            print("      gen_voices.py 를 먼저 실행해 mp3를 만들어 주세요.")

    def is_speaking(self):
        return self._speaking

    def _wav(self, key):
        return os.path.join(VOICES_DIR, f"{key}.mp3")

    def _play_sequence(self, chunks, my_gen):
        """조각들을 단일 mpg123 프로세스로 연속 재생(청크 간 갭 제거).
           재생이 끝나면 펜딩에 최신 안내가 있으면 같은 스레드에서 이어 재생.
           세대(my_gen)가 바뀌면(인터럽트) 즉시 중단."""
        first = True   # 체인의 첫 안내에만 무음 워밍업을 붙인다
        try:
            while True:
                if my_gen != self._gen:
                    return                      # 인터럽트됨

                # 존재하는 조각만 경로로 변환
                paths = []
                if first:
                    silence = self._wav("_silence")
                    if os.path.exists(silence):
                        paths.append(silence)   # 첫 안내: 스피커 깨우기용 무음
                for key in chunks:
                    p = self._wav(key)
                    if os.path.exists(p):
                        paths.append(p)         # 없는 조각은 건너뜀
                first = False

                if paths:
                    try:
                        proc = subprocess.Popen(
                            ["mpg123", "-q"] + paths,  # 여러 파일 → 한 프로세스 연속 재생
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
                        self._proc = None

                # 재생이 끝났다. 대기 중인 '최신' 안내가 있으면 이어 재생.
                with self._lock:
                    if my_gen != self._gen:
                        return                  # 인터럽트됨(새 재생이 상태 관리)
                    if self._pending is not None:
                        chunks = self._pending
                        self._pending = None
                        continue                # 같은 스레드에서 최신 것 이어 재생
                    self._speaking = False
                    return
        finally:
            # 예외 등으로 빠져나갈 때도 현재 세대면 speaking 해제(영구 잠김 방지)
            with self._lock:
                if my_gen == self._gen:
                    self._speaking = False

    def _start(self, chunks, interrupt):
        """재생 시작.
           interrupt=True : 진행 중 재생을 끊고 새로 시작(즉시).
           interrupt=False: 재생 중이면 펜딩 슬롯에 '최신'으로 보류(양보).
        """
        with self._lock:
            if interrupt:
                self._gen += 1                  # 기존 시퀀스 무효화
                self._pending = None            # 대기 중 일반 안내 폐기
                if self._proc is not None:
                    try:
                        self._proc.kill()       # 재생 중 mpg123 즉시 종료
                    except Exception:
                        pass
                    self._proc = None
                self._speaking = True
                my_gen = self._gen
            else:
                if self._speaking:
                    # 재생 중 → 큐에 쌓지 않고 펜딩 슬롯을 최신으로 덮어쓴다.
                    # 단, 대기 중이 stop이면 약한 안내(warn 등)는 덮어쓰지 못함.
                    incoming_stop = _is_stop(chunks)
                    pending_stop = _is_stop(self._pending) if self._pending else False
                    if incoming_stop or not pending_stop:
                        self._pending = list(chunks)
                    return
                self._gen += 1
                self._pending = None
                self._speaking = True
                my_gen = self._gen
        t = threading.Thread(target=self._play_sequence,
                             args=(chunks, my_gen), daemon=True)
        t.start()

    def say(self, item):
        """일반 안내. 재생 중이면 끊지 않고 펜딩 슬롯에 최신만 보류했다 이어 재생."""
        chunks, text = _normalize(item)
        if not chunks and not text:
            return
        if self.dry_run:
            print(f"[음성] {text}")
            return
        self._start(chunks, interrupt=False)

    def say_now(self, item):
        """즉시 안내. 진행 중 재생을 끊고 즉시 재생(인터럽트).
           (종료 안내 등 즉시성이 꼭 필요한 경우에만 사용)"""
        chunks, text = _normalize(item)
        if not chunks and not text:
            return
        if self.dry_run:
            print(f"[음성!] {text}")
            return
        self._start(chunks, interrupt=True)