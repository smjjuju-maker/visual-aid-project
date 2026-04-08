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