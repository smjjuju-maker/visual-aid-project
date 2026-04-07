def fuse_step_and_depth(step_count, depth_info):
    return {
        "steps": step_count,
        "depth": depth_info
    }

if __name__ == "__main__":
    print(fuse_step_and_depth(3, {"min_depth_m": 2.5}))