import threading
import time
import traceback
import sys
import os

class StatusUpdater:
    def __init__(self, lab_server, update_interval=300):
        self.lab_server = lab_server
        self.update_interval = update_interval
        self.stop_event = threading.Event()
        self.update_thread = None
        self.first_update = True  # 标记是否是首次更新
    
    def start(self):
        """启动后台更新线程"""
        if self.update_thread is None:
            self.update_thread = threading.Thread(target=self._update_loop)
            self.update_thread.daemon = True
            self.update_thread.start()
    
    def stop(self):
        """停止后台更新"""
        if self.update_thread:
            self.stop_event.set()
            try:
                self.update_thread.join(timeout=5)  # 等待最多5秒
            except:
                pass
            self.update_thread = None
    
    def _update_loop(self):
        """更新循环"""
        while not self.stop_event.is_set():
            try:
                # 如果是首次更新，等待主程序完成初始化
                if self.first_update:
                    time.sleep(2)
                    self.first_update = False
                
                # 静默执行更新
                original_stdout = sys.stdout
                sys.stdout = open(os.devnull, 'w')
                try:
                    self.lab_server.get_all_servers_status()
                finally:
                    sys.stdout.close()
                    sys.stdout = original_stdout
                
            except Exception as e:
                # 记录详细的错误信息
                error_msg = f"后台更新出错：{str(e)}\n{traceback.format_exc()}"
                try:
                    if hasattr(self.lab_server, 'log_manager'):
                        self.lab_server.log_manager.log_error(error_msg)
                except:
                    pass  # 静默处理错误
            
            # 等待下一次更新
            for _ in range(self.update_interval):
                if self.stop_event.is_set():
                    break
                time.sleep(1)