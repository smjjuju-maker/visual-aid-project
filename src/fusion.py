def fuse_step_and_depth(step_count, depth_info):
    """
    스텝 수 + depth 정보 결합하여 상황 판단
    """
    steps = step_count
    min_depth = depth_info.get('min_depth', float('inf'))
    obj = depth_info.get('object', 'none')
    
    if min_depth < 2.0:
        alert = f"장애물 {obj} {min_depth:.1f}미터 앞!"
    elif steps > 0:
        alert = f"{steps}걸음 진행 중"
    else:
        alert = "안전"
    
    return alert

if __name__ == "__main__":
    # Week1 테스트에서 나온 값들
    steps = 2  # 방금 stepdetector 결과
    depth = {'min_depth': 1.8, 'object': 'chair', 'confidence': 0.8}
    
    message = fuse_step_and_depth(steps, depth)
    print("융합 결과:", message)