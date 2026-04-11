from enum import Enum


class NavState(Enum):
    ALL_CLEAR = "ALL_CLEAR"
    GO_FORWARD = "GO_FORWARD"
    AVOID_LEFT = "AVOID_LEFT"
    AVOID_RIGHT = "AVOID_RIGHT"
    STOP_AND_SCAN = "STOP_AND_SCAN"
    RECHECK = "RECHECK"


def calculate_risk(center_depth, confidence):
    if center_depth <= 1.5 and confidence >= 0.8:
        return "HIGH"
    elif center_depth <= 3.0:
        return "MEDIUM"
    else:
        return "LOW"


def evaluate_corridor(depth_value, free_ratio, min_passable_depth=2.0, min_free_ratio=0.35):
    return depth_value >= min_passable_depth and free_ratio >= min_free_ratio


def choose_avoid_direction(left_depth, right_depth, left_free_ratio, right_free_ratio):
    left_ok = evaluate_corridor(left_depth, left_free_ratio)
    right_ok = evaluate_corridor(right_depth, right_free_ratio)

    if right_ok and not left_ok:
        return NavState.AVOID_RIGHT

    if left_ok and not right_ok:
        return NavState.AVOID_LEFT

    if left_ok and right_ok:
        right_score = right_depth + right_free_ratio
        left_score = left_depth + left_free_ratio
        if right_score > left_score:
            return NavState.AVOID_RIGHT
        else:
            return NavState.AVOID_LEFT

    return NavState.STOP_AND_SCAN


def fuse_step_and_depth(step_count, depth_info, stride_length=0.7, previous_state=None):
    # 1) 입력 꺼내기
    left_depth = depth_info["left_roi_depth"]
    center_depth = depth_info["center_roi_depth"]
    right_depth = depth_info["right_roi_depth"]
    obj = depth_info["object"]
    confidence = depth_info["confidence"]
    bbox_left = depth_info.get("bbox_left")
    bbox_right = depth_info.get("bbox_right")

    # ✅ 여기: corridor_hint 입력 받기
    corridor_hint = depth_info.get("corridor_hint")

    # 2) bbox로부터 자유공간 비율 계산
    if bbox_left is None or bbox_right is None:
        left_free_ratio = 0.0
        right_free_ratio = 0.0
    else:
        left_free_ratio = round(bbox_left, 2)
        right_free_ratio = round(1.0 - bbox_right, 2)

    risk = calculate_risk(center_depth, confidence)

    # 3) debug 기본 정보
    debug = {
        "step_count": step_count,
        "stride_length": stride_length,
        "object": obj,
        "confidence": confidence,
        "left_roi_depth": left_depth,
        "center_roi_depth": center_depth,
        "right_roi_depth": right_depth,
        "left_free_ratio": left_free_ratio,
        "right_free_ratio": right_free_ratio,
        "risk": risk,
        "previous_state": previous_state.value if isinstance(previous_state, NavState) else None,
        # ✅ 여기: debug에 corridor_hint 저장
        "corridor_hint": corridor_hint
    }

    # 4) 상태 결정
    # ✅ 여기: corridor_hint가 있으면 우선 사용
    if corridor_hint:
        left_ok = corridor_hint.get("left_passable", False)
        center_ok = corridor_hint.get("center_passable", False)
        right_ok = corridor_hint.get("right_passable", False)

        if center_ok and center_depth >= 3.5:
            state = NavState.GO_FORWARD
        elif right_ok and not left_ok:
            state = NavState.AVOID_RIGHT
        elif left_ok and not right_ok:
            state = NavState.AVOID_LEFT
        elif left_ok and right_ok:
            state = NavState.AVOID_RIGHT if right_depth >= left_depth else NavState.AVOID_LEFT
        else:
            state = NavState.STOP_AND_SCAN

    else:
        if obj == "none" and min(left_depth, center_depth, right_depth) >= 4.0:
            state = NavState.ALL_CLEAR
        elif center_depth >= 3.5:
            state = NavState.GO_FORWARD
        else:
            state = choose_avoid_direction(
                left_depth, right_depth, left_free_ratio, right_free_ratio
            )

    # 5) 이전 상태 반영
    if previous_state in [NavState.AVOID_LEFT, NavState.AVOID_RIGHT]:
        if center_depth >= 3.5:
            state = NavState.GO_FORWARD
        else:
            state = NavState.RECHECK

    debug["state"] = state.value

    # 6) 사용자 안내 문장
    if state == NavState.ALL_CLEAR:
        message = None
    elif state == NavState.GO_FORWARD:
        message = None
    elif state == NavState.AVOID_RIGHT:
        message = f"주의! {obj} {center_depth:.1f}미터 앞. 오른쪽으로 이동."
    elif state == NavState.AVOID_LEFT:
        message = f"주의! {obj} {center_depth:.1f}미터 앞. 왼쪽으로 이동."
    elif state == NavState.STOP_AND_SCAN:
        message = f"주의! {obj} {center_depth:.1f}미터 앞. 정지 후 재탐색."
    else:  # RECHECK
        message = "회피 중입니다. 전방 재확인."

    return state, message, debug


if __name__ == "__main__":
    sample = {
        "left_roi_depth": 1.2,
        "center_roi_depth": 2.8,
        "right_roi_depth": 4.5,
        "object": "wall",
        "bbox_left": 0.1,
        "bbox_right": 0.4,
        "confidence": 0.88,
        "corridor_hint": {
            "left_passable": False,
            "center_passable": False,
            "right_passable": True
        }
    }

    state, message, debug = fuse_step_and_depth(2, sample, 0.7)
    print("state:", state.value)
    print("message:", message)
    print("debug:", debug)