import os
import fcntl
import time

class FileLock:
    def __init__(self, file_path):
        self.file_path = file_path
        self.lock_file = f"{file_path}.lock"
        self.lock_fd = None
        self.acquired = False
        
    def acquire(self, timeout=10, retry_interval=0.1):
        """获取文件锁"""
        if self.acquired:
            return True
            
        start_time = time.time()
        while True:
            try:
                self.lock_fd = open(self.lock_file, 'w')
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return True
            except (IOError, OSError):
                if time.time() - start_time > timeout:
                    return False
                time.sleep(retry_interval)
                
    def release(self):
        """释放文件锁"""
        if self.acquired and self.lock_fd:
            try:
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
                self.lock_fd.close()
                os.remove(self.lock_file)
            except:
                pass
            finally:
                self.acquired = False
                self.lock_fd = None
                
    def __enter__(self):
        self.acquire()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release() 