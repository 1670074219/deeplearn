import paramiko
from threading import Lock

class SSHManager:
    _instance = None
    _lock = Lock()
    _connections = {}
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_connection(self, server_info):
        """获取或创建SSH连接"""
        key = f"{server_info['host']}:{server_info['port']}"
        with self._lock:
            if key not in self._connections:
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
                except Exception as e:
                    print(f"SSH连接失败：{str(e)}")
                    return None
            return self._connections[key]
    
    def close_all(self):
        """关闭所有连接"""
        with self._lock:
            for ssh in self._connections.values():
                try:
                    ssh.close()
                except:
                    pass
            self._connections.clear() 