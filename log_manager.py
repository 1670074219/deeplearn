import os
from datetime import datetime

class LogManager:
    def __init__(self, log_file, max_lines=100):
        self.log_file = log_file
        self.max_lines = max_lines
        self.backup_dir = os.path.join(os.path.dirname(log_file), 'log_backup')
        
        # 创建备份目录
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)
    
    def rotate_log(self):
        """检查并轮转日志文件"""
        try:
            # 如果日志文件不存在，直接返回
            if not os.path.exists(self.log_file):
                return
            
            # 读取当前日志文件
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 如果行数超过限制
            if len(lines) > self.max_lines:
                # 创建备份文件名
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_file = os.path.join(
                    self.backup_dir, 
                    f'container_check_{timestamp}.log'
                )
                
                # 将旧日志移动到备份文件
                with open(backup_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines[:-self.max_lines])
                
                # 保留最新的日志
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines[-self.max_lines:])
                
                # 清理旧的备份文件（只保留最近的10个备份）
                self._cleanup_old_backups()
                
        except Exception as e:
            print(f"日志轮转失败：{str(e)}")
    
    def _cleanup_old_backups(self):
        """清理旧的备份文件，只保留最近的10个"""
        try:
            backup_files = [
                os.path.join(self.backup_dir, f) 
                for f in os.listdir(self.backup_dir) 
                if f.startswith('container_check_')
            ]
            
            # 按修改时间排序
            backup_files.sort(
                key=lambda x: os.path.getmtime(x),
                reverse=True
            )
            
            # 删除旧的备份文件
            for old_file in backup_files[10:]:
                os.remove(old_file)
                
        except Exception as e:
            print(f"清理旧备份文件失败：{str(e)}") 