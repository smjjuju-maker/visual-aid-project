from imureader import read_imu_data
from oakreader import get_depth_info
from stepdetector import detect_steps
from fusion import fuse_step_and_depth
from ttsoutput import speak_message


def main():
    print("=== Day7 main.py 전체 파이프라인 시작 ===")

    # 1. IMU 데이터 읽기
    df = read_imu_data()
    accel_z_list = df["accel_z"].tolist()
    print("IMU 데이터 로드 완료")
    print("accel_z:", accel_z_list)

    # 2. 스텝 감지
    step_count, peaks = detect_steps(accel_z_list)
    print("스텝 감지 완료")
    print("step_count:", step_count)
    print("peaks:", peaks)

    # 3. Depth 정보 읽기
    depth_info = get_depth_info()
    print("Depth 정보 로드 완료")
    print("depth_info:", depth_info)

    # 4. 융합
    result_message = fuse_step_and_depth(step_count, depth_info)
    print("융합 결과:", result_message)

    # 5. TTS 출력
    speak_message(result_message)
    print("TTS 출력 완료")

    print("=== Day7 main.py 전체 파이프라인 종료 ===")


if __name__ == "__main__":
    main()