"""
tts.py
------
음성 출력 모듈 (pyttsx3 기반, 오프라인).

[환경]
  - 라즈베리파이에서 동작, 블루투스 골전도 이어폰으로 출력.
  - 블루투스 페어링은 OS(라즈베리파이) 레벨에서 미리 연결해두면,
    pyttsx3는 시스템 기본 출력 장치로 소리를 내보낸다.

[설치]
  pip install pyttsx3
  # 라즈베리파이(리눅스)는 espeak 음성엔진 필요:
  #   sudo apt-get install espeak
  # 한국어 발음을 위해 voice를 'korean'으로 시도 (아래 _pick_korean_voice).

[중복 안내 방지]
  - 같은 문구를 매 프레임 반복하면 시끄럽다.
  - 직전과 동일한 문구이고 짧은 시간 내면 다시 말하지 않는다.
"""

import time
import threading

try:
    import pyttsx3
    _HAS_PYTTSX3 = True
except ImportError:
    _HAS_PYTTSX3 = False


class Speaker:
    """음성 안내 담당. 중복 문구는 일정 시간 억제한다."""

    def __init__(self, rate=170, repeat_cooldown=2.0, dry_run=False):
        """
        rate: 말하는 속도 (기본 170, 시각장애인용은 조금 빠르게도 가능)
        repeat_cooldown: 같은 문구를 다시 말하기까지 최소 대기(초)
        dry_run: True면 실제 음성 없이 화면 출력만 (PC 테스트용)
        """
        self.repeat_cooldown = repeat_cooldown
        self.dry_run = dry_run or not _HAS_PYTTSX3
        self.rate = rate
        self._last_text = None
        self._last_time = 0.0
        self._speaking = False          # 현재 음성 재생 중인지
        self._lock = threading.Lock()

        if self.dry_run and not _HAS_PYTTSX3:
            print("[TTS] pyttsx3 미설치 → 화면 출력 모드로 동작")

    def _pick_korean_voice(self, engine):
        """가능하면 한국어 음성을 선택."""
        try:
            for voice in engine.getProperty("voices"):
                vid = (voice.id or "").lower()
                vname = (getattr(voice, "name", "") or "").lower()
                if "korea" in vid or "ko" in vid or "korean" in vname:
                    engine.setProperty("voice", voice.id)
                    return
        except Exception:
            pass  # 한국어 음성 없으면 기본 음성 사용

    def _speak_blocking(self, text):
        """엔진을 새로 만들어 한 문장 재생하고 닫는다.
        (윈도우 pyttsx3의 runAndWait 반복 블로킹 문제 회피)"""
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            self._pick_korean_voice(engine)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
            del engine
        except Exception as e:
            print(f"[TTS 오류] {e}")
        finally:
            self._speaking = False

    def is_speaking(self):
        """현재 음성 재생 중인지 여부."""
        return self._speaking

    def say(self, text, force=False):
        """문구를 음성으로 출력. 백그라운드 스레드에서 재생하여
        메인 루프(카메라)를 막지 않음. (반복/타이밍 제어는 main에서 담당)"""
        if not text:
            return

        now = time.time()

        if self.dry_run:
            self._last_text = text
            self._last_time = now
            print(f"[음성] {text}")
            return

        # 이미 말하는 중이면 새 안내는 건너뜀 (말 겹침 방지)
        with self._lock:
            if self._speaking:
                return
            self._speaking = True

        self._last_text = text
        self._last_time = now

        t = threading.Thread(target=self._speak_blocking, args=(text,), daemon=True)
        t.start()

    def say_now(self, text):
        """긴급 경고용. (현재 구조상 say와 동일하게 동작하되 의미 구분)"""
        self.say(text, force=True)