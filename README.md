# visual-aid-project

시각장애인 보행 보조 시스템

## 목표
- BNO085: 걸음수 계싼
- OAK-D-Lite: 장애물 인식
- Fusion: "앞 의자가 3걸음 앞"
- AfterShokz: 골전도 음성 안내

## Day3 Progress (2026-04-08)
- imureader.py 완성: `data/dummyimu.csv` → pandas DataFrame → `accel_z` 리스트 반환
- oakreader.py 완성: 더미 depth 정보 반환 (`min_depth`, `object`, `confidence` dict)
- ttsoutput.py 완성: `pyttsx3`로 메시지 음성 출력 (rate=150, volume=1.0)
- Jupyter notebook: IMU Z축 데이터 sine wave 시각화 ✓
- src/test_day3.py: IMU → Depth → TTS 전체 연결 테스트 성공
- Git: Day3 커밋 완료 (`git log --oneline` 최상단에 Day3 커밋 확인)