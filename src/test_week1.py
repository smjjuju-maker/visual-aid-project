"""Week1 Day1~Day4 통합 테스트"""

import sys
from pathlib import Path

# 현재 파일 기준으로 src 폴더를 import 경로에 추가
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))

print("=== Week1 Day1~Day4 통합 테스트 시작 ===")

# 1. imureader 테스트
print("\n=== 1. imureader 테스트 ===")
try:
    from imureader import read_imu_data, get_accel_z

    imu_data = read_imu_data()
    print("IMU 데이터 로드 성공")
    print("데이터 shape:", imu_data.shape)
    print("컬럼명:", list(imu_data.columns))

    z_list = get_accel_z(imu_data)
    print("accel_z 리스트 추출 성공")
    print("accel_z 길이:", len(z_list))
    print("accel_z 앞 5개:", z_list[:5])
    print("✓ imureader 테스트 PASS")
except Exception as e:
    print("✗ imureader 테스트 실패:", e)

# 2. oakreader 테스트
print("\n=== 2. oakreader 테스트 ===")
try:
    from oakreader import get_depth_info

    depth_info = get_depth_info()
    print("Depth 정보 로드 성공")
    print("depth_info:", depth_info)

    if isinstance(depth_info, dict):
        print("dict 반환 OK")
        print("min_depth:", depth_info.get('min_depth'))
        print("object:", depth_info.get('object'))
        print("confidence:", depth_info.get('confidence'))
        print("✓ oakoakreader 테스트 PASS")
    else:
        print("✗ dict 형식이 아님")
except Exception as e:
    print("✗ oakreader 테스트 실패:", e)

# 3. ttsoutput 테스트
print("\n=== 3. ttsoutput 테스트 ===")
try:
    from ttsoutput import speak_message

    test_message = "Week 1 integration test complete."
    print("TTS 테스트 메시지:", test_message)
    speak_message(test_message)
    print("✓ ttsoutput 테스트 PASS")
except Exception as e:
    print("✗ ttsoutput 테스트 실패:", e)

# 4. 통합 연결 테스트
print("\n=== 4. 통합 연결 테스트 ===")
try:
    from imureader import read_imu_data, get_accel_z
    from oakreader import get_depth_info
    from ttsoutput import speak_message

    # IMU 데이터
    imu_data = read_imu_data()
    z_list = get_accel_z(imu_data)
    
    # Depth 데이터
    depth_info = get_depth_info()

    # 통합 요약 메시지
    test_summary = (
        f"IMU Z 데이터 {len(z_list)}개, "
        f"최소 거리 {depth_info.get('min_depth', 'N/A')}미터, "
        f"객체 {depth_info.get('object', 'N/A')}"
    )

    print("통합 요약:", test_summary)
    speak_message("Week 1 integration test complete.")
    print("통합 실행 성공")
except Exception as e:
    print("통합 테스트 실패:", e)
print("\n=== Week1 Day1~Day4 통합 테스트 종료 ===")