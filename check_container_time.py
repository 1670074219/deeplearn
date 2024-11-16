import yaml
import paramiko
import time
from datetime import datetime, timedelta

class ContainerTimeChecker:
    def __init__(self):
        self.config = self.load_config()
        self.ssh_connections = {}

    def load_config(self):
        """加载配置文件"""
        try:
            with open('config.yaml', 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
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
                # 修改Docker命令以获取Unix时间戳格式的创建时间
                cmd = "docker ps --format '{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.CreatedAt}}'"
                stdin, stdout, stderr = ssh.exec_command(cmd)
                output = stdout.read().decode()

                for line in output.strip().split('\n'):
                    if line and not line == '':
                        try:
                            container_id, name, status, created_at = line.split('\t')
                            
                            # 检查容器名称是否符合用户容器的命名规则（用户名-服务器名-时间戳）
                            name_parts = name.split('-')
                            if len(name_parts) != 3:  # 不是用户创建的容器，跳过
                                continue
                            
                            # 检查用户名是否在配置文件中
                            user = name_parts[0]
                            if user not in self.config['users']:
                                continue
                            
                            # 处理创建时间字符串
                            created_at = created_at.split('+')[0].strip()
                            try:
                                created_time = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                                running_time = datetime.now() - created_time
                                
                                container_info.append({
                                    'server': server_name,
                                    'container_id': container_id,
                                    'name': name,
                                    'user': user,
                                    'created_at': created_time,
                                    'running_time': running_time
                                })
                            except ValueError as e:
                                print(f"解析容器 {name} 的创建时间失败：{str(e)}")
                                continue
                                
                        except Exception as e:
                            print(f"处理容器信息失败：{str(e)}")
                            continue
                            
            except Exception as e:
                print(f"获取服务器 {server_name} 的容器信息失败：{str(e)}")

        return container_info

    def stop_container(self, server_name, container_name):
        """停止指定的容器"""
        try:
            ssh = self.connect_to_server(server_name)
            if not ssh:
                return False

            print(f"正在停止容器 {container_name}...")
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

            print(f"容器 {container_name} 已成功停止并删除")
            return True
        except Exception as e:
            print(f"操作失败：{str(e)}")
            return False

    def check_and_stop_overtime_containers(self):
        """检查并停止超时的容器"""
        try:
            print(f"\n=== 开始检查容器运行时间 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
            containers = self.get_container_info()
            
            if not containers:
                print("未发现正在运行的容器")
                return
            
            for container in containers:
                user = container['user']
                # 获取用户的时间限制
                time_limit = self.config['tasks']['user_limits'].get(
                    user, 
                    self.config['tasks']['user_limits']['default']
                )['time_limit']
                
                # 将时间限制转换为小时
                running_hours = container['running_time'].total_seconds() / 3600
                
                print(f"\n检查容器：{container['name']}")
                print(f"运行时间：{running_hours:.1f}小时")
                print(f"时间限制：{time_limit}小时")
                
                if running_hours > time_limit:
                    print(f"容器 {container['name']} 已超过运行时间限制")
                    print(f"用户：{user}")
                    print(f"服务器：{container['server']}")
                    print(f"已运行：{running_hours:.1f}小时")
                    print(f"限制时间：{time_limit}小时")
                    
                    if self.stop_container(container['server'], container['name']):
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
    checker.check_and_stop_overtime_containers()

if __name__ == "__main__":
    main() 