import yaml

class GPUManager:
    def __init__(self, config):
        self.config = config
        if 'gpu_usage' not in self.config:
            self.config['gpu_usage'] = {server: {} for server in self.config['servers']}

    def get_gpu_usage(self, server_name):
        """获取服务器的GPU使用情况"""
        return self.config['gpu_usage'].get(server_name, {})

    def is_gpu_available(self, server_name, gpu_index):
        """检查指定的GPU是否可用"""
        gpu_usage = self.get_gpu_usage(server_name)
        return str(gpu_index) not in gpu_usage

    def allocate_gpus(self, server_name, gpu_indices, username):
        """分配GPU给用户"""
        if server_name not in self.config['gpu_usage']:
            self.config['gpu_usage'][server_name] = {}
            
        for gpu_index in gpu_indices:
            self.config['gpu_usage'][server_name][str(gpu_index)] = username
        
        # 保存配置文件
        self._save_config()
        return True

    def release_gpus(self, server_name, gpu_indices):
        """释放用户的GPU"""
        if server_name in self.config['gpu_usage']:
            for gpu_index in gpu_indices:
                self.config['gpu_usage'][server_name].pop(str(gpu_index), None)
            
            # 保存配置文件
            self._save_config()

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
            # 清理所有GPU使用记录
            for server in self.config['gpu_usage']:
                self.config['gpu_usage'][server] = {}
            
            # 从task_records重建GPU使用记录
            if 'task_records' in self.config:
                for username, tasks in self.config['task_records'].items():
                    for task in tasks:
                        server_name = task['server']
                        gpu_indices = task['gpus']
                        for gpu_index in gpu_indices:
                            if server_name not in self.config['gpu_usage']:
                                self.config['gpu_usage'][server_name] = {}
                            self.config['gpu_usage'][server_name][str(gpu_index)] = username
            
            # 保存更新后的配置
            self._save_config()
            
        except Exception as e:
            print(f"同步GPU使用情况失败：{str(e)}")