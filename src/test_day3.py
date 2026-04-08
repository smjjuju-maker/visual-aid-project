from imureader import read_imu_data, get_accel_z
from oakreader import get_depth_info
from ttsoutput import speak_message

# IMU 읽기
df = read_imu_data()
z_accel = get_accel_z(df)
print(f"IMU Z 데이터 길이: {len(z_accel)}")

# Depth 읽기
depth = get_depth_info()
print(f"Depth: {depth}")

# TTS로 결과 말하기
steps = len(z_accel) // 2  # 임시 step 수
msg = f"걸음 {steps}개, 앞 {depth['min_depth']}미터 {depth['object']}."
speak_message(msg)