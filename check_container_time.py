import yaml
import paramiko
import time
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from log_manager import LogManager

class ContainerTimeChecker:
    def __init__(self):
        self.config = self.load_config()
        self.ssh_connections = {}

    def load_config(self):
        """加载配置文件"""
        try:
            # 获取脚本所在目录的绝对路径
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, 'config.yaml')
            
            print(f"尝试加载配置文件：{config_path}")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config is None:
                    raise ValueError("配置文件为空")
                return config
        except Exception as e:
            print(f"加载配置文件失败：{str(e)}")
            return None

    def connect_to_server(self, server_name):
        """连接到服务器"""
        try:
            if server_name in self.ssh_connections:
                return self.ssh_connections[server_name]

            server = self.config['servers'][server_name]
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=server['host'],
                port=server['port'],
                username=server['username'],
                password=server['password'],
                timeout=10
            )
            self.ssh_connections[server_name] = ssh
            return ssh
        except Exception as e:
            print(f"连接服务器 {server_name} 失败：{str(e)}")
            return None

    def get_container_info(self):
        """获取所有服务器上的容器信息"""
        container_info = []
        for server_name in self.config['servers']:
            ssh = self.connect_to_server(server_name)
            if not ssh:
                continue

            try:
                # 使用不同的格式获取容器信息，包括启动时间
                cmd = "docker ps --format '{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.RunningFor}}'"
                stdin, stdout, stderr = ssh.exec_command(cmd)
                output = stdout.read().decode()

                for line in output.strip().split('\n'):
                    if line and not line == '':
                        try:
                            container_id, name, status, running_for = line.split('\t')
                            
                            # 检查容器名称是否符合用户容器的命名规则
                            name_parts = name.split('-')
                            if len(name_parts) != 3:  # 不是用户创建的容器，跳过
                                continue
                            
                            # 检查用户名是否在配置文件中
                            user = name_parts[0]
                            if user not in self.config['users']:
                                continue
                            
                            # 解析运行时间
                            running_hours = 0
                            if 'hours' in running_for:
                                hours = running_for.split('hours')[0].strip()
                                try:
                                    running_hours = float(hours)
                                except ValueError:
                                    print(f"解析容器 {name} 的运行时间失败")
                                    continue
                            elif 'minutes' in running_for:
                                minutes = running_for.split('minutes')[0].strip()
                                try:
                                    running_hours = float(minutes) / 60
                                except ValueError:
                                    print(f"解析容器 {name} 的运行时间失败")
                                    continue
                                
                            container_info.append({
                                'server': server_name,
                                'container_id': container_id,
                                'name': name,
                                'user': user,
                                'status': status,
                                'running_hours': running_hours
                            })
                            
                        except Exception as e:
                            print(f"处理容器信息失败：{str(e)}")
                            continue
                            
            except Exception as e:
                print(f"获取服务器 {server_name} 的容器信息失败：{str(e)}")

        return container_info

    def stop_container(self, ssh, server_name, container_name):
        """停止指定的容器"""
        try:
            print(f"\n正在停止容器 {container_name}...")
            stop_cmd = f"docker stop {container_name}"
            stdin, stdout, stderr = ssh.exec_command(stop_cmd)
            error = stderr.read().decode()
            if error:
                print(f"停止容器失败：{error}")
                return False

            print("正在删除容器...")
            rm_cmd = f"docker rm {container_name}"
            stdin, stdout, stderr = ssh.exec_command(rm_cmd)
            error = stderr.read().decode()
            if error:
                print(f"删除容器失败：{error}")
                return False

            # 从配置文件中删除相关记录
            self._remove_task_record(container_name)
            
            print(f"容器 {container_name} 已成功停止并删除")
            return True
        except Exception as e:
            print(f"操作失败：{str(e)}")
            return False

    def _remove_task_record(self, container_name):
        """从配置文件中删除任务记录"""
        try:
            if 'task_records' not in self.config:
                return
            
            # 遍历所有用户的任务记录
            for username, tasks in self.config['task_records'].items():
                # 使用列表推导式过滤掉要删除的容器记录
                self.config['task_records'][username] = [
                    task for task in tasks 
                    if task['container'] != container_name
                ]
            
            # 保存更新后的配置
            self._save_config()
        except Exception as e:
            print(f"更新任务记录失败：{str(e)}")

    def _save_config(self):
        """保存配置到文件"""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, 'config.yaml')
            
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True)
        except Exception as e:
            print(f"保存配置文件失败：{str(e)}")

    def send_email(self, to_email, subject, body):
        """发送邮件"""
        try:
            # 创建邮件
            msg = MIMEMultipart()
            msg['From'] = self.config['email_settings']['sender_email']
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # 添加正文
            msg.attach(MIMEText(body, 'plain'))
            
            # 连接SMTP服务器
            server = smtplib.SMTP(
                self.config['email_settings']['smtp_server'],
                self.config['email_settings']['smtp_port']
            )
            server.starttls()
            
            # 登录
            server.login(
                self.config['email_settings']['sender_email'],
                self.config['email_settings']['sender_password']
            )
            
            # 发送邮件
            server.send_message(msg)
            server.quit()
            
            print(f"成功发送提醒邮件到 {to_email}")
            return True
        except Exception as e:
            print(f"发送邮件失败：{str(e)}")
            return False

    def clean_task_records(self):
        """清理不存在的容器记录"""
        try:
            if 'task_records' not in self.config:
                return
            
            # 获取所有正在运行的容器名称
            running_containers = set()
            for server_name in self.config['servers']:
                ssh = self.connect_to_server(server_name)
                if not ssh:
                    continue
                
                cmd = "docker ps --format '{{.Names}}'"
                stdin, stdout, stderr = ssh.exec_command(cmd)
                containers = stdout.read().decode().strip().split('\n')
                running_containers.update(containers)
            
            # 清理每个用户的任务记录
            cleaned = False
            for username in list(self.config['task_records'].keys()):
                if not self.config['task_records'][username]:
                    continue
                
                # 过滤出仍在运行的容器记录
                valid_tasks = [
                    task for task in self.config['task_records'][username]
                    if task['container'] in running_containers
                ]
                
                # 如果有记录被清理
                if len(valid_tasks) != len(self.config['task_records'][username]):
                    cleaned = True
                    if valid_tasks:
                        self.config['task_records'][username] = valid_tasks
                    else:
                        # 如果用户没有有效记录，删除整个用户记录
                        del self.config['task_records'][username]
            
            # 如果有记录被清理，保存配置文件
            if cleaned:
                self._save_config()
                print("已清理过期的任务记录")
            
        except Exception as e:
            print(f"清理任务记录失败：{str(e)}")

    def check_and_stop_overtime_containers(self):
        """检查并停止超时的容器"""
        try:
            print(f"\n=== 开始检查容器运行时间 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
            
            # 先清理过期的任务记录
            self.clean_task_records()
            
            containers = self.get_container_info()
            if not containers:
                print("未发现正在运行的容器")
                return
            
            warning_threshold = self.config.get('notification_settings', {}).get('warning_threshold', 0.8)
            
            for container in containers:
                try:
                    user = container['user']
                    if user not in self.config['users']:
                        print(f"跳过未知用户的容器：{container['name']}")
                        continue
                    
                    # 获取用户组的时间限制
                    user_group = self.config['users'][user].get('group', 'default')
                    if user_group not in self.config['user_groups']:
                        print(f"用户 {user} 的用户组 {user_group} 不存在，使用默认组")
                        user_group = 'default'
                    
                    time_limit = self.config['user_groups'][user_group]['time_limit']
                    running_hours = container['running_hours']
                    
                    print(f"\n检查容器：{container['name']}")
                    print(f"运行时间：{running_hours:.1f}小时")
                    print(f"时间限制：{time_limit}小时")
                    
                    # 发送提醒邮件
                    if running_hours >= (time_limit * warning_threshold) and running_hours < time_limit:
                        self.send_warning_email(user, container, time_limit, running_hours)
                    
                    # 停止超时容器
                    if running_hours > time_limit:
                        self.stop_overtime_container(container, user)
                    else:
                        print("容器运行时间正常，继续运行")
                    
                except Exception as e:
                    print(f"处理容器 {container.get('name', '未知')} 时出错：{str(e)}")
                    continue
                
        except Exception as e:
            print(f"检查容器运行时间失败：{str(e)}")
        finally:
            # 清理SSH连接
            for ssh in self.ssh_connections.values():
                try:
                    ssh.close()
                except:
                    pass

def main():
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(script_dir, 'container_check.log')
    
    # 创建日志管理器并进行轮转
    log_manager = LogManager(log_file)
    log_manager.rotate_log()
    
    checker = ContainerTimeChecker()
    if checker.config is None:
        print("无法加载配置文件，程序退出")
        return
    checker.check_and_stop_overtime_containers()

if __name__ == "__main__":
    main() 