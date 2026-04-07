import pyttsx3

def speak_text(message):
    engine = pyttsx3.init()
    engine.say(message)
    engine.runAndWait()

if __name__ == "__main__":
    speak_text("Day 2 text to speech test")

import pyttsx3

engine = pyttsx3.init()

voices = engine.getProperty("voices")
print("voice count:", len(voices))
for i, v in enumerate(voices):
    print(i, v.id, getattr(v, "name", "no-name"))

print("rate:", engine.getProperty("rate"))
print("volume:", engine.getProperty("volume"))

engine.setProperty("rate", 150)
engine.setProperty("volume", 1.0)

if len(voices) > 0:
    engine.setProperty("voice", voices[0].id)

engine.say("테스트 음성입니다. 지금 pyttsx3를 확인하고 있습니다.")
engine.runAndWait()
print("done")

import pyttsx3

engine = pyttsx3.init()
engine.setProperty("rate", 150)
engine.setProperty("volume", 1.0)
engine.save_to_file("이 파일이 생성되면 TTS 엔진은 정상입니다.", "tts_test.wav")
engine.runAndWait()
print("saved")
