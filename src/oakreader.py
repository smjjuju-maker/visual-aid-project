import numpy as np
import random

def get_depth_info():
    """OAK-D-Lite 더미 depth 정보 반환. min_depth(m), object, confidence."""
    min_depth = round(random.uniform(1.0, 5.0), 2)  # 1~5m 랜덤
    objects = random.choice(['chair', 'wall', 'none'])
    confidence = round(random.uniform(0.8, 1.0), 2)
    return {'min_depth': min_depth, 'object': objects, 'confidence': confidence}

if __name__ == "__main__":
    depth_info = get_depth_info()
    print("Depth 정보:", depth_info)