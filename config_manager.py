import yaml
from file_lock import FileLock

class ConfigManager:
    def __init__(self, config_file):
        self.config_file = config_file
        self.lock = FileLock(config_file)
        
    def load_config(self):
        """线程安全的配置加载"""
        try:
            if self.lock.acquire():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                self.lock.release()
                return config
        except Exception as e:
            print(f"加载配置失败：{str(e)}")
            return None
            
    def save_config(self, config):
        """线程安全的配置保存"""
        try:
            if self.lock.acquire():
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    yaml.dump(config, f, allow_unicode=True)
                self.lock.release()
                return True
        except Exception as e:
            print(f"保存配置失败：{str(e)}")
            return False 