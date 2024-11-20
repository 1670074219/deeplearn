import yaml
import threading
from file_lock import FileLock

class GPUManager:
    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()  # 添加线程锁
        self.file_lock = FileLock('config.yaml')  # 添加文件锁
        
        # 初始化时确保所有服务器都有gpu_usage记录
        if 'gpu_usage' not in self.config:
            self.config['gpu_usage'] = {}
        for server in self.config['servers']:
            if server not in self.config['gpu_usage']:
                self.config['gpu_usage'][server] = {}

    def get_gpu_usage(self, server_name):
        """获取服务器的GPU使用情况"""
        return self.config['gpu_usage'].get(server_name, {})

    def is_gpu_available(self, server_name, gpu_index):
        """检查指定的GPU是否可用"""
        with self._lock:
            try:
                if not self.file_lock.acquire():
                    return False

                gpu_usage = self.get_gpu_usage(server_name)
                is_available = str(gpu_index) not in gpu_usage
                self.file_lock.release()
                return is_available

            except Exception as e:
                print(f"检查GPU可用性失败：{str(e)}")
                if self.file_lock.acquired:
                    self.file_lock.release()
                return False

    def allocate_gpus(self, server_name, gpu_indices, username):
        """分配GPU给用户"""
        with self._lock:  # 使用线程锁
            try:
                # 获取文件锁
                if not self.file_lock.acquire():
                    print("无法获取文件锁")
                    return False

                # 检查服务器是否存在
                if server_name not in self.config['gpu_usage']:
                    self.file_lock.release()
                    return False
                    
                # 再次检查GPU是否可用（双重检查）
                for gpu_index in gpu_indices:
                    if str(gpu_index) in self.config['gpu_usage'][server_name]:
                        self.file_lock.release()
                        return False
                
                # 分配GPU
                for gpu_index in gpu_indices:
                    self.config['gpu_usage'][server_name][str(gpu_index)] = username
                
                # 保存配置
                self._save_config()
                self.file_lock.release()
                return True
                
            except Exception as e:
                print(f"分配GPU失败：{str(e)}")
                if self.file_lock.acquired:
                    self.file_lock.release()
                return False

    def release_gpus(self, server_name, gpu_indices):
        """释放用户的GPU"""
        with self._lock:
            try:
                if not self.file_lock.acquire():
                    return False

                if server_name in self.config['gpu_usage']:
                    for gpu_index in gpu_indices:
                        self.config['gpu_usage'][server_name].pop(str(gpu_index), None)
                    
                    self._save_config()
                    self.file_lock.release()
                    return True

            except Exception as e:
                print(f"释放GPU失败：{str(e)}")
                if self.file_lock.acquired:
                    self.file_lock.release()
                return False

    def _save_config(self):
        """保存配置到文件"""
        try:
            with open('config.yaml', 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True)
        except Exception as e:
            print(f"保存配置文件失败：{str(e)}")

    def sync_gpu_usage(self):
        """同步GPU使用情况"""
        try:
            # 创建临时记录
            temp_usage = {server: {} for server in self.config['servers']}
            
            # 从task_records重建GPU使用记录
            if 'task_records' in self.config:
                for username, tasks in self.config['task_records'].items():
                    for task in tasks:
                        server_name = task.get('server')
                        gpu_indices = task.get('gpus', [])
                        if server_name and gpu_indices:
                            for gpu_index in gpu_indices:
                                temp_usage[server_name][str(gpu_index)] = username
            
            # 更新配置
            self.config['gpu_usage'] = temp_usage
            self._save_config()
            return True
            
        except Exception as e:
            print(f"同步GPU使用情况失败：{str(e)}")
            return False