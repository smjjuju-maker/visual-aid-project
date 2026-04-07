import pyttsx3

def speak_text(message):
    engine = pyttsx3.init()
    engine.say(message)
    engine.runAndWait()

if __name__ == "__main__":
    speak_text("Day 2 text to speech test")