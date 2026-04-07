def get_dummy_depth():
    return {
        "min_depth_m": 2.5,
        "object": "chair",
        "confidence": 0.95
    }

if __name__ == "__main__":
    print(get_dummy_depth())