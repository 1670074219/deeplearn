import os
import logging
from datetime import datetime

class LogManager:
    def __init__(self, log_file):
        self.log_file = log_file
        
        # 配置日志记录器
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
        self.logger = logging.getLogger('LabServer')
    
    def log_error(self, message):
        """记录错误信息"""
        self.logger.error(message)
    
    def log_info(self, message):
        """记录普通信息"""
        self.logger.info(message)
    
    def rotate_log(self):
        """日志文件轮转"""
        try:
            if os.path.exists(self.log_file):
                # 获取当前时间戳
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                # 创建备份文件名
                backup_file = f"{self.log_file}.{timestamp}"
                # 如果文件大于1MB，进行轮转
                if os.path.getsize(self.log_file) > 1024 * 1024:
                    os.rename(self.log_file, backup_file)
        except Exception as e:
            print(f"日志轮转失败：{str(e)}")