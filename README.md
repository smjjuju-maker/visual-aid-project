# visual-aid-project

BNO085 IMU step counting, OAK-D-Lite depth detection, fusion, and TTS project in Python.

## Project Goal
This project aims to build a visual aid pipeline using:
- BNO085 IMU for acceleration data
- OAK-D-Lite for depth information
- Step detection from IMU Z-axis
- Fusion of step count and obstacle distance
- Text-to-speech output

## Project Structure
```text
visual-aid-project/
├─ README.md
├─ requirements.txt
├─ data/
│  └─ dummyimu.csv
├─ src/
│  ├─ imureader.py
│  ├─ oakreader.py
│  ├─ ttsoutput.py
│  ├─ stepdetector.py
│  ├─ fusion.py
│  └─ main.py
└─ .vscode/
   └─ settings.json
```

## Environment Setup
1. Create and activate virtual environment
2. Install packages from requirements.txt
3. Select Python interpreter in VS Code

## Install
```powershell
pip install -r requirements.txt
```

## Run Current Modules

### IMU reader
```powershell
python src/imureader.py
```

### OAK reader
```powershell
python src/oakreader.py
```

### TTS output
```powershell
python src/ttsoutput.py
```

## Progress

### Day1
- VS Code, Git, venv, requirements.txt setup completed
- Python environment and package import checked

### Day2
- Created `src` and `data` folders
- Added `dummyimu.csv`
- Created starter files for module structure

### Day3
- Completed `imureader.py`: CSV to DataFrame and accel_z extraction
- Completed `oakreader.py`: dummy depth dictionary return
- Completed `ttsoutput.py`: message speech output
- Tested IMU plot and basic module connection
- test_week1.py: 통합 테스트 PASS

## Next Steps
- Day5: implement `stepdetector.py`
- Day6: implement `fusion.py`
- Day7: integrate in `main.py`



============================
🍓 캡스톤 라즈베리파이 정보
============================

[SSH 접속]
호스트: capstone26.local
사용자: capstone26
비밀번호: capstone_26

[접속 명령어]
ssh capstone26@capstone26.local

[Wi-Fi]
아이폰 핫스팟 (호환성 최대화 ON)

[설치된 것들]
- OrbbecSDK v1.10.35: ~/OrbbecSDK/
- 빌드 완료: ~/OrbbecSDK/build/bin/
- espeak-ng (TTS)
- OpenGL 라이브러리

[검증 결과]
- Femto Bolt: ✅ 컬러 작동, ❌ Depth 안 됨 (retCode:204)
- Depth Engine과 RPi GPU 비호환

[다음에 할 일]
- 지도교수님과 상의
- 또는 SDK v2 시도
- TTS (espeak-ng) 테스트
- BNO055 IMU 연결

[자주 쓰는 명령어]
가상환경: source ~/tts-env/bin/activate
TTS 테스트: espeak-ng -v ko "안녕하세요"
카메라 확인: ~/OrbbecSDK/build/bin/ob_hello_orbbec