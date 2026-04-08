import pandas as pd
import os

def read_imu_data(csv_path='C:\\Users\\ymj\\visual-aid-project\\data\\dummyimu.csv'):
    """IMU 데이터를 CSV에서 읽어 DataFrame 반환. 나중에 BNO085 센서 데이터로 교체 가능."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"{csv_path} 파일이 없습니다.")
    df = pd.read_csv(csv_path)
    return df

def get_accel_z(df):
    """DataFrame에서 Z축 가속도 리스트 반환. step detection에서 사용할 형태."""
    return df['accel_z'].tolist()

if __name__ == "__main__":
    df = read_imu_data()
    print("IMU 데이터 (처음 5행):")
    print(df.head())
    print("Z축 가속도:", get_accel_z(df))