import paramiko
from threading import Lock
import time
import threading

class SSHManager:
    _instance = None
    _lock = Lock()
    _connections = {}
    _locks = {}
    _last_used = {}  # 记录连接最后使用时间
    _max_idle_time = 300  # 空闲连接超时时间（秒）
    _cleanup_interval = 60
    _cleanup_thread = None
    _stop_cleanup = False
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_connection(self, server_info):
        """获取SSH连接"""
        key = f"{server_info['host']}:{server_info['port']}"
        
        # 创建服务器专用锁
        if key not in self._locks:
            self._locks[key] = threading.Lock()
            
        with self._locks[key]:
            try:
                # 检查现有连接
                if key in self._connections:
                    ssh = self._connections[key]
                    try:
                        ssh.exec_command('echo 1', timeout=5)
                        self._last_used[key] = time.time()
                        return ssh
                    except:
                        # 连接已断开，删除并重新创建
                        self._remove_connection(key)
                
                # 创建新连接
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(
                    hostname=server_info['host'],
                    port=server_info['port'],
                    username=server_info['username'],
                    password=server_info['password'],
                    timeout=10
                )
                
                self._connections[key] = ssh
                self._last_used[key] = time.time()
                
                # 启动清理线程
                self._start_cleanup_thread()
                
                return ssh
                
            except Exception as e:
                print(f"创建SSH连接失败：{str(e)}")
                return None
    
    def _start_cleanup_thread(self):
        """启动清理线程"""
        if not self._cleanup_thread:
            self._cleanup_thread = threading.Thread(target=self._cleanup_loop)
            self._cleanup_thread.daemon = True
            self._cleanup_thread.start()
    
    def _cleanup_loop(self):
        """定期清理空闲连接"""
        while not self._stop_cleanup:
            time.sleep(self._cleanup_interval)
            self.cleanup_idle_connections()
    
    def cleanup_idle_connections(self):
        """清理空闲连接"""
        current_time = time.time()
        with self._lock:
            for key in list(self._connections.keys()):
                if current_time - self._last_used[key] > self._max_idle_time:
                    try:
                        self._connections[key].close()
                    except:
                        pass
                    del self._connections[key]
                    del self._last_used[key]
    
    def close_all(self):
        """关闭所有连接"""
        with self._lock:
            for ssh in self._connections.values():
                try:
                    ssh.close()
                except:
                    pass
            self._connections.clear()
            self._last_used.clear() 