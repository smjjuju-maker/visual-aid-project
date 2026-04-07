import pandas as pd

def load_dummy_imu(csv_path="data/dummyimu.csv"):
    df = pd.read_csv(csv_path)
    return df

if __name__ == "__main__":
    df = load_dummy_imu()
    print(df.head())