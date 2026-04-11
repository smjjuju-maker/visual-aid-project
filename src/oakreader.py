import random


def get_depth_info():
    min_depth = round(random.uniform(1.0, 5.0), 2)
    objects = random.choice(["chair", "wall", "box", "none"])
    confidence = round(random.uniform(0.8, 1.0), 2)
    return {
        "min_depth": min_depth,
        "object": objects,
        "confidence": confidence
    }


def get_demo_depth_info():
    """
    실센서 연결 전 테스트용 공간 해석 입력.
    나중에 OAK-D Lite 실데이터가 들어오면 같은 키 구조를 유지하면 됨.
    """

    scenarios = [
        {
            "name": "narrow_center_blocked",
            "left_roi_depth": 1.8,
            "center_roi_depth": 1.6,
            "right_roi_depth": 1.9,
            "object": "chair",
            "bbox_left": 0.35,
            "bbox_right": 0.65,
            "confidence": 0.92,
            "corridor_hint": {
                "left_passable": False,
                "center_passable": False,
                "right_passable": False
            }
        },
        {
            "name": "right_open",
            "left_roi_depth": 1.2,
            "center_roi_depth": 2.8,
            "right_roi_depth": 4.5,
            "object": "wall",
            "bbox_left": 0.10,
            "bbox_right": 0.40,
            "confidence": 0.88,
            "corridor_hint": {
                "left_passable": False,
                "center_passable": False,
                "right_passable": True
            }
        },
        {
            "name": "left_open",
            "left_roi_depth": 4.2,
            "center_roi_depth": 2.1,
            "right_roi_depth": 1.3,
            "object": "box",
            "bbox_left": 0.55,
            "bbox_right": 0.85,
            "confidence": 0.91,
            "corridor_hint": {
                "left_passable": True,
                "center_passable": False,
                "right_passable": False
            }
        },
        {
            "name": "all_clear",
            "left_roi_depth": 5.1,
            "center_roi_depth": 6.8,
            "right_roi_depth": 4.9,
            "object": "none",
            "bbox_left": None,
            "bbox_right": None,
            "confidence": 1.0,
            "corridor_hint": {
                "left_passable": True,
                "center_passable": True,
                "right_passable": True
            }
        },
        {
            "name": "forward_clear_midrange",
            "left_roi_depth": 3.2,
            "center_roi_depth": 4.0,
            "right_roi_depth": 3.4,
            "object": "none",
            "bbox_left": None,
            "bbox_right": None,
            "confidence": 0.97,
            "corridor_hint": {
                "left_passable": True,
                "center_passable": True,
                "right_passable": True
            }
        }
    ]

    return random.choice(scenarios)


if __name__ == "__main__":
    info = get_demo_depth_info()
    print("demo depth info:", info)