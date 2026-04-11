import random
import time
from oakreader import get_demo_depth_info
from fusion import fuse_step_and_depth, NavState
from ttsoutput import speak_message


def estimate_demo_stride_length():
    return round(random.uniform(0.62, 0.78), 2)


def estimate_demo_step_count():
    return random.randint(1, 4)


def main():
    print("=== Day8 상태기계 기반 데모 시작 (3초 간격 x 8회) ===")

    previous_state = None

    for i in range(8):
        print(f"\n===== 데모 {i+1}/8 =====")

        stride_length = estimate_demo_stride_length()
        step_count = estimate_demo_step_count()
        depth_info = get_demo_depth_info()

        state, result_message, debug = fuse_step_and_depth(
            step_count=step_count,
            depth_info=depth_info,
            stride_length=stride_length,
            previous_state=previous_state
        )

        print(f"[Scenario] 이름: {depth_info.get('name', 'unknown')}")
        print(f"[BNO085] 추정 보폭: {stride_length} m/걸음")
        print(f"[BNO085] 현재 감지된 걸음 수: {step_count} 걸음")

        print(f"[OAK-D-Lite] 왼쪽 거리: {debug['left_roi_depth']} m")
        print(f"[OAK-D-Lite] 중앙 거리: {debug['center_roi_depth']} m")
        print(f"[OAK-D-Lite] 오른쪽 거리: {debug['right_roi_depth']} m")
        print(f"[OAK-D-Lite] 감지 물체: {debug['object']}")
        print(f"[OAK-D-Lite] confidence: {debug['confidence']}")

        print(f"[Fusion] 이전 상태: {debug['previous_state']}")
        print(f"[Fusion] 현재 상태: {debug['state']}")
        print(f"[Fusion] 위험도: {debug['risk']}")
        print(f"[Fusion] 왼쪽 여유 비율: {debug['left_free_ratio']}")
        print(f"[Fusion] 오른쪽 여유 비율: {debug['right_free_ratio']}")
        print(f"[Fusion] corridor_hint: {debug['corridor_hint']}")

        if state in [NavState.ALL_CLEAR, NavState.GO_FORWARD]:
            print("[Fusion] 전방 안전 또는 직진 가능. TTS 생략.")
        elif state == NavState.RECHECK:
            print("[Fusion] 회피 동작 이후 재평가 중.")
            if result_message:
                print(f"[최종 안내] {result_message}")
                speak_message(result_message)
        else:
            print(f"[최종 안내] {result_message}")
            speak_message(result_message)

        previous_state = state
        time.sleep(3)

    print("\n=== Day8 상태기계 기반 데모 종료 ===")


if __name__ == "__main__":
    main()