import yaml
import paramiko
import time
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

    def check_and_stop_overtime_containers(self):
        """检查并停止超时的容器"""
        try:
            print(f"\n=== 开始检查容器运行时间 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
            containers = self.get_container_info()
            
            if not containers:
                print("未发现正在运行的容器")
                return
            
            warning_threshold = self.config['notification_settings']['warning_threshold']
            
            for container in containers:
                user = container['user']
                # 获取用户的时间限制
                time_limit = self.config['tasks']['user_limits'].get(
                    user, 
                    self.config['tasks']['user_limits']['default']
                )['time_limit']
                
                running_hours = container['running_hours']
                
                print(f"\n检查容器：{container['name']}")
                print(f"运行时间：{running_hours:.1f}小时")
                print(f"时间限制：{time_limit}小时")
                
                # 检查是否需要发送提醒邮件
                if running_hours >= (time_limit * warning_threshold) and running_hours < time_limit:
                    user_email = self.config['users'][user].get('email')
                    if user_email:
                        remaining_hours = time_limit - running_hours
                        subject = "容器运行时间提醒"
                        body = f"""
您好，{user}：

您的容器 {container['name']} 即将达到运行时间限制。

当前状态：
- 已运行时间：{running_hours:.1f}小时
- 时间限制：{time_limit}小时
- 剩余时间：{remaining_hours:.1f}小时
- 运行服务器：{container['server']}

请注意保存您的工作，容器将在达到时间限制后自动停止。

此邮件为系统自动发送，请勿回复。
"""
                        self.send_email(user_email, subject, body)
                
                if running_hours > time_limit:
                    print(f"容器 {container['name']} 已超过运行时间限制")
                    print(f"用户：{user}")
                    print(f"服务器：{container['server']}")
                    print(f"已运行：{running_hours:.1f}小时")
                    print(f"限制时间：{time_limit}小时")
                    
                    # 发送停止通知邮件
                    user_email = self.config['users'][user].get('email')
                    if user_email:
                        subject = "容器已自动停止通知"
                        body = f"""
您好，{user}：

您的容器 {container['name']} 已达到运行时间限制，系统已自动停止。

容器信息：
- 运行时间：{running_hours:.1f}小时
- 时间限制：{time_limit}小时
- 运行服务器：{container['server']}

如需继续使用，请重新创建容器。

此邮件为系统自动发送，请勿回复。
"""
                        self.send_email(user_email, subject, body)
                    
                    if self.stop_container(self.connect_to_server(container['server']), container['server'], container['name']):
                        print(f"已停止超时容器：{container['name']}")
                    else:
                        print(f"停止容器失败：{container['name']}")
                else:
                    print(f"容器运行时间正常，继续运行")
            
            print("\n=== 检查完成 ===")
            
        except Exception as e:
            print(f"检查过程中出错：{str(e)}")
        finally:
            # 清理SSH连接
            for ssh in self.ssh_connections.values():
                try:
                    ssh.close()
                except:
                    pass

def main():
    checker = ContainerTimeChecker()
    if checker.config is None:
        print("无法加载配置文件，程序退出")
        return
    checker.check_and_stop_overtime_containers()

if __name__ == "__main__":
    main() 