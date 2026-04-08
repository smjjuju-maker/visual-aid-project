import numpy as np
import pandas as pd

def detect_steps(accel_z_list, threshold=0.3):
    """
    IMU Z축 데이터에서 스텝 감지 (peak detection)
    """
    # threshold만으로 peak detection (moving average 제거)
    peaks = []
    mean_z = np.mean(accel_z_list)
    
    for i in range(1, len(accel_z_list)-1):
        # 로컬 최대 + 평균보다 threshold만큼 큼
        if (accel_z_list[i] > accel_z_list[i-1] and 
            accel_z_list[i] > accel_z_list[i+1] and 
            accel_z_list[i] > mean_z + threshold):
            peaks.append(i)
    
    return len(peaks), peaks

if __name__ == "__main__":
    # 더 강한 스텝 데이터
    test_z = [9.8, 10.5, 9.7, 10.6, 9.6, 10.7, 9.8, 10.8, 9.9, 10.4, 9.7]
    print("테스트 데이터:", test_z)
    steps, peaks = detect_steps(test_z, threshold=0.5)
    print(f"감지된 스텝 수: {steps}")
    print(f"피크 위치: {peaks}")
    print(f"평균: {np.mean(test_z):.2f}")