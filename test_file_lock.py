import multiprocessing
import time
from file_lock import FileLock

def worker(worker_id):
    """模拟工作进程"""
    lock_file = "test.txt"
    
    with FileLock(lock_file) as lock:
        if not lock.acquired:
            print(f"工作进程 {worker_id}: 无法获取锁")
            return
            
        print(f"工作进程 {worker_id}: 获得锁")
        # 模拟进行一些文件操作
        with open(lock_file, "a") as f:
            f.write(f"进程 {worker_id} 正在写入\n")
            time.sleep(2)  # 模拟耗时操作
        print(f"工作进程 {worker_id}: 释放锁")

def main():
    # 创建测试文件
    with open("test.txt", "w") as f:
        f.write("初始内容\n")
    
    # 创建多个进程同时访问文件
    processes = []
    for i in range(3):
        p = multiprocessing.Process(target=worker, args=(i,))
        processes.append(p)
        p.start()
    
    # 等待所有进程完成
    for p in processes:
        p.join()
    
    # 显示最终文件内容
    print("\n最终文件内容:")
    with open("test.txt", "r") as f:
        print(f.read())

if __name__ == "__main__":
    main()