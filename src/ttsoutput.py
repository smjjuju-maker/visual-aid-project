import pyttsx3

def speak_message(message):
    """TTS로 메시지 출력. 나중에 Bluetooth 연동 가능."""
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)  # 속도 조정 (한국어에 적합)
    engine.setProperty('volume', 1.0)
    engine.say(message)
    engine.runAndWait()

if __name__ == "__main__":
    speak_message("Day 3 TTS 테스트: 앞에 2미터 장애물, 5걸음.")