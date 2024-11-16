import time
from check_container_time import ContainerTimeChecker

def test_checker():
    print("=== 开始测试容器时间检查器 ===")
    
    # 第一次检查
    print("\n第一次检查（初始状态）:")
    checker = ContainerTimeChecker()
    checker.check_and_stop_overtime_containers()
    
    # 等待一段时间后再次检查
    wait_time = 60  # 等待60秒
    print(f"\n等待 {wait_time} 秒后进行第二次检查...")
    time.sleep(wait_time)
    
    # 第二次检查
    print("\n第二次检查（等待后）:")
    checker = ContainerTimeChecker()
    checker.check_and_stop_overtime_containers()
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_checker() 