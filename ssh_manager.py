import paramiko
from threading import Lock
import time

class SSHManager:
    _instance = None
    _lock = Lock()
    _connections = {}
    _last_used = {}  # 记录连接最后使用时间
    _max_idle_time = 300  # 空闲连接超时时间（秒）
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_connection(self, server_info):
        """获取或创建SSH连接"""
        key = f"{server_info['host']}:{server_info['port']}"
        current_time = time.time()
        
        with self._lock:
            # 检查是否有可用的连接
            if key in self._connections:
                # 检查连接是否还有效
                try:
                    self._connections[key].exec_command('echo 1', timeout=5)
                    self._last_used[key] = current_time
                    return self._connections[key]
                except:
                    # 连接已断开，删除旧连接
                    del self._connections[key]
                    del self._last_used[key]
            
            # 创建新连接
            try:
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
                self._last_used[key] = current_time
                return ssh
            except Exception as e:
                print(f"SSH连接失败：{str(e)}")
                return None
    
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