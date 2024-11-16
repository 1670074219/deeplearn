import os
import fcntl
import time

class FileLock:
    def __init__(self, file_path):
        self.file_path = file_path
        self.lock_file = f"{file_path}.lock"
        self.lock_fd = None
        
    def acquire(self, timeout=10):
        """获取文件锁"""
        start_time = time.time()
        while True:
            try:
                self.lock_fd = open(self.lock_file, 'w')
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except (IOError, OSError):
                if time.time() - start_time > timeout:
                    return False
                time.sleep(0.1)
                
    def release(self):
        """释放文件锁"""
        if self.lock_fd:
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
            self.lock_fd.close()
            try:
                os.remove(self.lock_file)
            except OSError:
                pass 