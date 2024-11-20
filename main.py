import yaml
import paramiko
import getpass
import time
from user_manager import UserManager
from config_manager import ConfigManager
from ssh_manager import SSHManager
from docker_manager import DockerManager
from log_manager import LogManager
from group_manager import GroupManager
from gpu_manager import GPUManager
from terminal_manager import TerminalManager
from concurrent.futures import ThreadPoolExecutor, as_completed
from status_updater import StatusUpdater
import os
import sys
import json
from registry_manager import RegistryManager

class LabServer:
    def __init__(self):
        self.config_manager = ConfigManager('config.yaml')
        self.log_manager = LogManager('server.log')
        self.ssh_manager = SSHManager()
        self.docker_manager = DockerManager()
        self.config = self.config_manager.load_config()
        self.current_user = None
        self.cached_server_status = None
        self.user_manager = UserManager(self.config)
        self.group_manager = GroupManager(self.config)
        self.gpu_manager = GPUManager(self.config)
        self.last_status_update = 0
        self.status_update_interval = 300  # 5分钟更���一次
        self.max_workers = 10  # 最大并行连接数
        
        # 同步GPU使用情况
        self.gpu_manager.sync_gpu_usage()
        
        # 不在初始化时启动状态更新器
        self.status_updater = None
        self.registry_manager = RegistryManager(self.config)

    def load_config(self):
        with open('config.yaml', 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def login(self):
        while True:  # 添加循环，允许用户重试
            try:
                username = input("请输入用户名: ")
                if username == '0':  # 允许用户输入0返回主菜单
                    return False
                
                # 检查用户是否存在
                if username not in self.config['users']:
                    print(f"错误：用户 {username} 不存在")
                    continue  # 重新开始循环
                
                # 尝试最多3次密码输入
                for attempt in range(3):
                    password = getpass.getpass("请输入密码: ")
                    if password == '0':  # 允许户输入0回用户名入
                        break
                    
                    # 检查密码是否正确
                    user_info = self.config['users'][username]
                    if user_info['password'] == password:
                        self.current_user = username
                        print(f"欢迎, {username}!")
                        print(f"用户角色: {user_info['role']}")
                        return True
                    else:
                        remaining = 2 - attempt
                        if remaining > 0:
                            print(f"错误：密码不正确，还有{remaining}次机会")
                        else:
                            print("错误：密码输入次数过多")
                
                # 如果3次密码都错误，询问用户是否重新输入用户名
                retry = input("\n是否重新输入用户名？(y/n): ").lower().strip()
                if retry != 'y':
                    return False
                
            except Exception as e:
                print(f"登录过程中出错：{str(e)}")
                return False

    def check_gpu_status(self, server_name):
        """获取服务器GPU状态"""
        if server_name not in self.config['servers']:
            print(f"错误：服务器 {server_name} 不存在")
            return None
        
        server = self.config['servers'][server_name]
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            print(f"正在连接到服务器 {server_name} ({server['host']})...")
            ssh.connect(
                hostname=server['host'],
                port=server['port'],
                username=server['username'],
                password=server['password'],
                timeout=10
            )
            
            # 获取GPU详细信息
            cmd = (
                "nvidia-smi --query-gpu=index,gpu_name,memory.total,memory.used,memory.free,utilization.gpu "
                "--format=csv,noheader,nounits"
            )
            stdin, stdout, stderr = ssh.exec_command(cmd)
            output = stdout.read().decode()
            error = stderr.read().decode()
            
            if error:
                print(f"获取GPU状态时出错：{error}")
                return None
            
            gpu_info = []
            for line in output.strip().split('\n'):
                index, name, total_mem, used_mem, free_mem, util = line.split(', ')
                gpu_info.append({
                    'index': int(index),
                    'name': name,
                    'total_memory': float(total_mem),
                    'used_memory': float(used_mem),
                    'free_memory': float(free_mem),
                    'utilization': float(util)
                })
            
            return gpu_info
            
        except Exception as e:
            print(f"连接服务器失败：{str(e)}")
            return None
        finally:
            ssh.close()

    def get_server_docker_images(self, ssh):
        """获取服务器上的Docker镜像列表"""
        try:
            stdin, stdout, stderr = ssh.exec_command('docker images --format "{{.Repository}}:{{.Tag}}\t{{.Size}}"')
            error = stderr.read().decode()
            if error:
                print(f"获取Docker镜像列表失败：{error}")
                return []
            
            images = []
            output = stdout.read().decode()
            for line in output.strip().split('\n'):
                if line:
                    image_info = line.split('\t')
                    if len(image_info) == 2:
                        images.append({
                            'name': image_info[0],
                            'size': image_info[1]
                        })
            return images
        except Exception as e:
            print(f"取Docker镜像列表出错：{str(e)}")
            return []

    def pull_docker_image(self, ssh, image_name, registry_info):
        """从指定仓库拉取Docker镜像"""
        try:
            print(f"正在从 {registry_info['name']} 拉取镜像 {image_name}...")
            
            # 根不同的仓库建不同的镜像名称和命令
            if registry_info['url'] == 'docker.io':
                # Docker Hub镜像保持原始名称
                full_image_name = image_name
                pull_cmd = f"docker pull {full_image_name}"
            else:
                # 私有仓库镜像添加仓库地址前缀
                if image_name.startswith(registry_info['url']):
                    full_image_name = image_name
                else:
                    full_image_name = f"{registry_info['url']}/{image_name}"
                pull_cmd = f"docker pull {full_image_name}"
            
            print(f"构建的镜像名称：{full_image_name}")
            
            # 如果仓库需要认证
            if 'username' in registry_info and 'password' in registry_info:
                login_cmd = (
                    f"echo {registry_info['password']} | "
                    f"docker login {registry_info['url']} "
                    f"--username {registry_info['username']} "
                    f"--password-stdin"
                )
                
                print(f"正在远程��登录Docker仓库 {registry_info['url']}...")
                stdin, stdout, stderr = ssh.exec_command(login_cmd)
                login_output = stdout.read().decode()
                login_error = stderr.read().decode()
                
                if "Login Succeeded" in login_output or "Login Succeeded" in login_error:
                    print("Docker仓库登录成功！")
                else:
                    print(f"登录Docker仓库失败：{login_error}")
                    return False

            # 在远程服务器上拉取镜像
            print(f"开始在远程服务器上拉取镜像：{full_image_name}")
            print(f"执命令：{pull_cmd}")
            
            stdin, stdout, stderr = ssh.exec_command(pull_cmd)
            
            # 实时显示拉取进度
            while True:
                line = stdout.readline()
                if not line:
                    break
                print(line.strip())
            
            error = stderr.read().decode()
            if error:
                if "Error" in error:
                    if "Client.Timeout exceeded" in error:
                        print("拉取超时，可能是网络问题。建议：")
                        print("1. 检查服务器网络连接")
                        print("2. 尝试使用其他像源")
                        print("3. 如果可能，虑使用私有仓库")
                    print(f"拉取像失败：{error}")
                    return False
                else:
                    print(f"警告：{error}")
            
            # 在远程服务器上验证镜像是否成功拉取
            verify_cmd = f"docker images {full_image_name} --format '{{{{.Repository}}}}:{{{{.Tag}}}}'"
            stdin, stdout, stderr = ssh.exec_command(verify_cmd)
            if stdout.read().decode().strip():
                print("镜像拉取成功！")
                return True
            else:
                print("镜像拉取失败：无法在远程服务器上找到拉取的镜像")
                return False
            
        except Exception as e:
            print(f"拉取镜像时出错：{str(e)}")
            return False

    def get_registry_images(self, ssh=None):
        """获取仓库服务器上的镜像列表"""
        try:
            print("正在获取镜像列表...")
            images = self.registry_manager.list_images()
            
            if images:
                print(f"\n找到 {len(images)} 个镜像:")
                for img in images:
                    print(f"- {img['name']} ({img['size']})")
            else:
                print("未找到任何镜像")
            
            return images
        except Exception as e:
            print(f"获取仓库镜像列表时出错：{str(e)}")
            return []

    def create_user_data_dir(self, ssh, username):
        """在仓库服务器上创建用户的数据录和FTP虚拟用"""
        try:
            # 连接到仓库服务器
            registry_ssh = paramiko.SSHClient()
            registry_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            registry_server = self.config['registry_server']
            registry_ssh.connect(
                hostname=registry_server['host'],
                port=registry_server['port'],
                username=registry_server['username'],
                password=registry_server['password']
            )

            # 创建用户目录
            user_dir = f"{registry_server['nfs_path']}/{username}"
            
            # 目录是否存在
            check_cmd = f"[ -d {user_dir} ] && echo 'exists' || echo 'not exists'"
            stdin, stdout, stderr = registry_ssh.exec_command(check_cmd)
            if stdout.read().decode().strip() == 'exists':
                print(f"用户目录已���：{user_dir}")
            else:
                # 创建录并
                cmd = f"sudo mkdir -p {user_dir} && sudo chmod 755 {user_dir}"
                print(f"正在创建用户数据目录：{user_dir}")
                stdin, stdout, stderr = registry_ssh.exec_command(cmd)
                error = stderr.read().decode()
                
                if error:
                    print(f"创用户数据目录失：{error}")
                    return None

            # 创建虚拟用户配置
            virtual_user_config = f"""
local_root={user_dir}
write_enable=YES
anon_upload_enable=NO
anon_mkdir_write_enable=NO
allow_writeable_chroot=YES
"""
            # 创建用户配置文件
            user_config_path = f"/etc/vsftpd/vusers/{username}"
            registry_ssh.exec_command("sudo mkdir -p /etc/vsftpd/vusers")
            registry_ssh.exec_command(f"echo '{virtual_user_config}' | sudo tee {user_config_path}")

            # 确保目录所有权正确
            registry_ssh.exec_command(f"sudo chown -R virtual_ftp:virtual_ftp {user_dir}")
            registry_ssh.exec_command(f"sudo chmod 755 {user_dir}")

            # 更新用户数据库文件
            db_file = "/etc/vsftpd/virtual_users.txt"
            add_user_cmd = f"echo -e '{username}\\n{self.config['users'][username]['password']}' | sudo tee -a {db_file}"
            registry_ssh.exec_command(add_user_cmd)

            # 生成用户数据库
            registry_ssh.exec_command("sudo db_load -T -t hash -f /etc/vsftpd/virtual_users.txt /etc/vsftpd/virtual_users.db")

            # 更新用户配置
            self.config['users'][username]['data_dir'] = user_dir
            self._save_config()

            print(f"\nFTP 虚拟户配完成：")
            print(f"服务器：{registry_server['host']}")
            print(f"端口：21")
            print(f"用户名：{username}")
            print(f"密码：与系统密码相同")
            print(f"目录：{user_dir}")
            
            return user_dir

        except Exception as e:
            print(f"创建用户数据目录时出错：{str(e)}")
            return None
        finally:
            try:
                registry_ssh.close()
            except:
                pass

    def _save_config(self):
        """保存置到文件"""
        with open('config.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, allow_unicode=True)

    def get_server_status(self, server_item):
        """获取单个服务器状态的方法"""
        idx, (server_name, server_info) = server_item
        try:
            print(f"正在连接服务器 {server_name} ({server_info['host']})...")
            ssh = self.ssh_manager.get_connection(server_info)
            if ssh:
                print(f"连接成功，正在获取GPU信息...")
                gpu_info = self.check_gpu_status_with_ssh(ssh, server_name)
                if gpu_info is not None:
                    gpu_usage = self.gpu_manager.get_gpu_usage(server_name)
                    allocated_gpus = len(gpu_usage)
                    total_gpus = len(gpu_info)
                    gpu_model = gpu_info[0]['name'] if gpu_info else "未知"
                    avg_util = sum(gpu['utilization'] for gpu in gpu_info) / total_gpus
                    
                    return str(idx), {
                        'name': server_name,
                        'host': server_info['host'],
                        'gpu_info': gpu_info,
                        'used_gpus': allocated_gpus,
                        'total_gpus': total_gpus,
                        'gpu_model': gpu_model,
                        'avg_util': avg_util
                    }
            return None
        except Exception as e:
            print(f"连接或获取信息失败：{str(e)}")
            return None

    def get_all_servers_status(self):
        """获取所有服的状态息（并行处）"""
        current_time = time.time()
        
        # 如果缓存的状态信息仍然有且不是强制刷新，直接返回
        if (self.cached_server_status is not None and 
            current_time - self.last_status_update < self.status_update_interval and
            self.last_status_update != 0):  # 添加这个条件
            return self.cached_server_status
        
        server_gpu_status = {}
        
        # 使用线程池并行处理连接
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            futures = []
            for idx, (name, info) in enumerate(self.config['servers'].items(), 1):
                futures.append(executor.submit(self.get_server_status, (idx, (name, info))))
            
            # 收集结果
            for future in as_completed(futures):
                result = future.result()
                if result:
                    idx, status = result
                    server_gpu_status[idx] = status
        
        # 更新缓存和时间戳
        self.cached_server_status = server_gpu_status
        self.last_status_update = current_time
        
        return server_gpu_status

    def check_gpu_status_with_ssh(self, ssh, server_name):
        """���用已有的SSH连接获取GPU状态"""
        try:
            cmd = (
                "nvidia-smi --query-gpu=index,gpu_name,memory.total,memory.used,memory.free,utilization.gpu "
                "--format=csv,noheader,nounits"
            )
            stdin, stdout, stderr = ssh.exec_command(cmd)
            output = stdout.read().decode()
            error = stderr.read().decode()
            
            if error:
                print(f"获取GPU状态时出错：{error}")
                return None
            
            gpu_info = []
            for line in output.strip().split('\n'):
                index, name, total_mem, used_mem, free_mem, util = line.split(', ')
                gpu_info.append({
                    'index': int(index),
                    'name': name,
                    'total_memory': float(total_mem),
                    'used_memory': float(used_mem),
                    'free_memory': float(free_mem),
                    'utilization': float(util)
                })
            
            return gpu_info
            
        except Exception as e:
            print(f"获取GPU状态失败：{str(e)}")
            return None

    def display_server_status(self, server_status):
        """显示服务器状态信息"""
        print("\n{:<5} {:<10} {:<15} {:<30} {:<10} {:<15} {:<20}".format(
            "序号", "服务器", "IP地址", "GPU型号", "GPU数量", "已用/总数", "已分配GPU"
        ))
        print("-" * 105)  # 减少分隔线长度
        
        # 按序号序
        sorted_status = sorted(server_status.items(), key=lambda x: int(x[0]))
        
        for idx, info in sorted_status:
            # 获取已分配的GPU
            gpu_usage = self.gpu_manager.get_gpu_usage(info['name'])
            allocated_gpus = [f"{k}({v})" for k, v in gpu_usage.items()]
            allocated_info = ", ".join(allocated_gpus) if allocated_gpus else "无"
            
            print("{:<5} {:<10} {:<15} {:<30} {:<10} {:<15} {:<20}".format(
                idx,
                info['name'],
                info['host'],
                info['gpu_model'],
                info['total_gpus'],
                f"{info['used_gpus']}/{info['total_gpus']}",
                allocated_info
            ))

    def create_dl_task(self):
        ssh_connections = {}
        try:
            # 在创建任务前检查用户数据目录
            user_data_dir = self.config['users'][self.current_user].get('data_dir')
            if not user_data_dir:
                print("正为用户创建数据目录...")
                registry_ssh = None
                try:
                    registry_ssh = paramiko.SSHClient()
                    registry_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    registry_server = self.config['registry_server']
                    registry_ssh.connect(
                        hostname=registry_server['host'],
                        port=registry_server['port'],
                        username=registry_server['username'],
                        password=registry_server['password']
                    )
                    user_data_dir = self.create_user_data_dir(registry_ssh, self.current_user)
                    if not user_data_dir:
                        print("无法创建用户数据目录，请联系管理员")
                        return False
                finally:
                    if registry_ssh:
                        registry_ssh.close()

            if not self.current_user:
                print("请先登录")
                return False

            while True:  # 服务器选择循环
                try:
                    # 获取最新的服务器状态
                    self.cached_server_status = self.get_all_servers_status()
                    
                    print("\n可用的服务器：")
                    self.display_server_status(self.cached_server_status)
                    
                    print("\n选项：")
                    print("0. 返回主菜单")
                    print("r. 刷新服务器信息")
                    server_choice = input("请选择服务器序号: ").strip().lower()
                    
                    if server_choice == '0':
                        return False
                    elif server_choice == 'r':
                        print("正在刷新服务器信息...")
                        self.cached_server_status = None
                        self.last_status_update = 0
                        continue
                    
                    if server_choice not in self.cached_server_status:
                        print("错误：无效的服务序号")
                        continue

                    # 服务器选择成功，建立SSH连接
                    server_info = self.cached_server_status[server_choice]
                    server_name = server_info['name']
                    server = self.config['servers'][server_name]
                    
                    # 创建SSH连接
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(
                        hostname=server['host'],
                        port=server['port'],
                        username=server['username'],
                        password=server['password'],
                        timeout=10
                    )
                    ssh_connections[server_name] = ssh
                    
                    # 检查用户是否有权限访问选择的服务器
                    user_group = self.config['users'][self.current_user].get('group', 'default')
                    group_info = self.config['user_groups'][user_group]
                    if server_name not in group_info['allowed_servers']:
                        print(f"您所在的用户组（{group_info['name']}）没有权限访问该服务器")
                        return False
                    
                    # 检查用户的容器数量限制
                    current_containers = len(self.get_user_tasks(self.current_user))
                    if current_containers >= group_info['max_containers']:
                        print(f"您已达到容器数量限制（最大{group_info['max_containers']}个）")
                        return False

                    # 进入镜像选择流程
                    return self.create_container(ssh, server_name, image_name)

                except Exception as e:
                    print(f"操作失败：{str(e)}")
                    continue

        except Exception as e:
            print(f"创建任务失败：{str(e)}")
            return False

        finally:
            # 确保所有SSH连接都被关闭
            for ssh in ssh_connections.values():
                try:
                    ssh.close()
                except:
                    pass

    def create_container(self, ssh, server_name, image_name):
        """创建容器的具体流程"""
        try:
            while True:  # 添加循环，允许重新选择GPU
                # 获取GPU信息
                gpu_info = self.check_gpu_status(server_name)
                if not gpu_info:
                    print("无法获取GPU信息")
                    return False

                # 显示GPU信息并选择GPU
                print("\n可用的GPU列表：")
                print(f"{'序号':<5} {'GPU型号':<30} {'显存使用':<20} {'使用率':<10} {'状态':<10}")
                print("-" * 75)
                available_gpus = []
                for gpu in gpu_info:
                    usage = f"{gpu['used_memory']:.0f}/{gpu['total_memory']:.0f}MB"
                    util_status = "空闲" if gpu['utilization'] < 5 else f"使用率{gpu['utilization']:.0f}%"
                    
                    # 检查GPU是否已被分配
                    if self.gpu_manager.is_gpu_available(server_name, gpu['index']):
                        alloc_status = "可用"
                        if gpu['utilization'] < 5:
                            available_gpus.append(str(gpu['index']))
                    else:
                        user = self.gpu_manager.get_gpu_usage(server_name).get(str(gpu['index']))
                        alloc_status = f"已分配给{user}"
                    
                    print(f"{gpu['index']:<5} {gpu['name']:<30} {usage:<20} {util_status:<10} {alloc_status:<10}")

                if not available_gpus:
                    print("\n当前没有可用的GPU")
                    return False

                # 让户选择GPU
                print("\n输入要使用的GPU编号（多个GPU用逗号分隔，如：0,1,2）")
                print("输入0返上一步")
                gpu_choice = input().strip()
                if gpu_choice == '0':
                    return False

                # 验证GPU选择
                selected_gpus = [g.strip() for g in gpu_choice.split(',')]
                
                # 检查输入的GPU是否有效且可用
                valid_choice = True
                unavailable_gpus = []
                
                # 首先检查所有GPU是否有效
                for gpu in selected_gpus:
                    if gpu not in [str(g['index']) for g in gpu_info]:
                        print(f"无效的GPU编号{gpu}")
                        valid_choice = False
                        break
                    
                if not valid_choice:
                    continue

                # 尝试分配GPU
                if not self.gpu_manager.allocate_gpus(server_name, selected_gpus, self.current_user):
                    print("GPU分配失败，可能已被其他用户使用")
                    continue

                try:
                    # 检查用户GPU使用限制
                    user_group = self.config['users'][self.current_user].get('group', 'default')
                    group_info = self.config['user_groups'][user_group]
                    if len(selected_gpus) > group_info['max_gpus']:
                        print(f"超出GPU使用限制（您所在的用户组 {group_info['name']} 最大可使用 {group_info['max_gpus']} 个GPU）")
                        # 释放已分配的GPU
                        self.gpu_manager.release_gpus(server_name, selected_gpus)
                        continue

                    # 获取端口映射
                    print("\n请输入主机端口（输入0返回上一步）:")
                    host_port = input().strip()
                    if host_port == '0':
                        return False
                    
                    try:
                        host_port = int(host_port)
                        if host_port < 1024 or host_port > 65535:
                            print("端口号必须在1024-65535之间")
                            return False
                    except ValueError:
                        print("请输入有效的端口号")
                        return False
                    
                    print("\n请输入容器内部端口（默认22，输入0返回上一步）:")
                    container_port = input().strip()
                    if container_port == '0':
                        return False
                    if not container_port:
                        container_port = '22'
                    
                    try:
                        container_port = int(container_port)
                        if container_port < 1 or container_port > 65535:
                            print("端口号必须在1-65535之间")
                            return False
                    except ValueError:
                        print("请输有效的端口号")
                        return False
                    
                    # 检查口是否已被使用
                    cmd = f"netstat -tln | grep ':{host_port}'"
                    stdin, stdout, stderr = ssh.exec_command(cmd)
                    if stdout.read():
                        print(f"端口 {host_port} 已被占用")
                        return False
                    
                    # 构建容器名称
                    container_name = f"{self.current_user}-{server_name}-{int(time.time())}"
                    
                    # 检查并处理同名容器
                    print(f"\n检查是否存在同名容器...")
                    check_cmd = f"docker ps -a --filter name={container_name} --format '{{{{.Names}}}}'"
                    stdin, stdout, stderr = ssh.exec_command(check_cmd)
                    if stdout.read():
                        print(f"发现同名容器存在")
                        print("选项：")
                        print("1. 删除已有容器继续创建")
                        print("2. 取消创建")
                        choice = input("请选择操作 [1/2]: ").strip()
                        
                        if choice == '2':
                            print("取消创建容器")
                            return False
                        elif choice == '1':
                            print(f"正在删除同名容器...")
                            # 先尝试停止容器
                            ssh.exec_command(f"docker stop {container_name}")
                            # 然后删除容器
                            ssh.exec_command(f"docker rm {container_name}")
                            print("同名容器已清理")
                        else:
                            print("无效的选择，取消创建")
                            return False
                    
                    # 获取用户数据目录
                    user_data_dir = self.config['users'][self.current_user].get('data_dir')
                    if not user_data_dir:
                        print("用户数据目录未配置")
                        return False
                    
                    # 修改这部分,处理镜像名称
                    # 检查是否是远程仓库镜像
                    registry_url = f"{self.config['registry_server']['host']}:{self.config['registry_server']['registry_port']}"
                    if not image_name.startswith(registry_url):
                        # 如果不是完整的仓库地址,则添加
                        image_name = f"{registry_url}/{image_name}"

                    # 构建docker run命令
                    device_list = ','.join(selected_gpus)
                    gpu_args = f"--gpus '\"device={device_list}\"'"
                    volume_mount = f"-v {user_data_dir}:/workspace"
                    port_mapping = f"-p {host_port}:{container_port}"
                    
                    docker_cmd = (
                        f"docker run -d --name {container_name} "
                        f"{gpu_args} {volume_mount} {port_mapping} "
                        f"{image_name} "  # 这里使用处理后的image_name
                        f"tail -f /dev/null"
                    )
                    
                    print("\n即将执行命令：")
                    print(docker_cmd)
                    print("\n确认创建容器？(y/n)")
                    if input().lower() != 'y':
                        return False

                    # 先尝试登录远程仓库
                    print("\n正在登录远程仓库...")
                    registry_info = self.config['docker_registries'][0]  # 使用第一个仓库配置
                    login_cmd = (
                        f"echo {registry_info['password']} | "
                        f"docker login {registry_info['url']} "
                        f"--username {registry_info['username']} "
                        f"--password-stdin"
                    )
                    stdin, stdout, stderr = ssh.exec_command(login_cmd)
                    error = stderr.read().decode()
                    if error and "Error" in error:
                        print(f"登录仓库失败：{error}")
                        return False

                    # 执行docker run命令
                    print("\n正在创建容器...")
                    stdin, stdout, stderr = ssh.exec_command(docker_cmd)
                    output = stdout.read().decode().strip()
                    error = stderr.read().decode().strip()

                    if error:
                        # 如果出现GPU相关错误，尝试使用替代语法
                        if "cannot set both Count and DeviceIDs on device request" in error:
                            print("尝试使用替代GPU参数格式...")
                            # 使替代的GPU参数格式
                            device_list = ','.join(selected_gpus)
                            gpu_args = f"--gpus '\"device={device_list}\"'"
                            docker_cmd = (
                                f"docker run -d --name {container_name} "
                                f"{gpu_args} {volume_mount} {port_mapping} "
                                f"{image_name} "
                                f"tail -f /dev/null"
                            )
                            print("\n使用新的命令重试：")
                            print(docker_cmd)
                            stdin, stdout, stderr = ssh.exec_command(docker_cmd)
                            output = stdout.read().decode()
                            error = stderr.read().decode()
                        
                        if error and "Error" in error:
                            print(f"创容器失败：{error}")
                            return False
                    
                    # 验证容器是否成功创建和运行
                    success = False  # 添加成功标志
                    verify_cmd = f"docker ps --filter name={container_name} --format '{{{{.Status}}}}'"
                    stdin, stdout, stderr = ssh.exec_command(verify_cmd)
                    status = stdout.read().decode().strip()
                    error = stderr.read().decode().strip()
                    
                    if error:
                        print(f"验证容器状态时出错：{error}")
                        self.gpu_manager.release_gpus(server_name, selected_gpus)
                        return False
                    
                    if not status:
                        print("容器未在运行状态")
                        self.gpu_manager.release_gpus(server_name, selected_gpus)
                        return False
                    
                    if not status.startswith('Up'):
                        print(f"容器状态异常：{status}")
                        self.gpu_manager.release_gpus(server_name, selected_gpus)
                        return False

                    success = True  # 设置成功标志
                    
                    if success:
                        # 记录任务信息
                        self._record_task(server_name, container_name, selected_gpus)
                        
                        print(f"\n容器创建成功！")
                        print(f"容器名称：{container_name}")
                        print(f"使用GPU：{', '.join(selected_gpus)}")
                        print(f"端口映射：{host_port} -> {container_port}")
                        print(f"数据目录：{user_data_dir} -> /workspace")
                        
                        # 更新状态缓存
                        self.cached_server_status = None
                        self.last_status_update = 0
                        return True
                    else:
                        self.gpu_manager.release_gpus(server_name, selected_gpus)
                        return False

                except Exception as e:
                    # 发生异常时释放GPU
                    self.gpu_manager.release_gpus(server_name, selected_gpus)
                    print(f"创建容器时发生错误：{str(e)}")
                    return False

            # except Exception as e:
            #     # 发生异常时释放GPU
            #     self.gpu_manager.release_gpus(server_name, selected_gpus)
            #     raise e

            # 如果容器创建失败，释放GPU
            if not success:
                self.gpu_manager.release_gpus(server_name, selected_gpus)
                return False

            return True

        except Exception as e:
            print(f"创建容器失败：{str(e)}")
            return False

    def get_user_tasks(self, username=None):
        """获取用户任务信息"""
        try:
            tasks = []
            for server_name, server_info in self.config['servers'].items():
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(
                    hostname=server_info['host'],
                    port=server_info['port'],
                    username=server_info['username'],
                    password=server_info['password']
                )
                
                # 获取所运行中的容器
                if username:
                    cmd = f"docker ps --format '{{{{.ID}}}}\t{{{{.Names}}}}\t{{{{.Status}}}}\t{{{{.RunningFor}}}}' | grep {username}"
                else:
                    cmd = "docker ps --format '{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.RunningFor}}'"
                
                stdin, stdout, stderr = ssh.exec_command(cmd)
                output = stdout.read().decode()
                
                for line in output.strip().split('\n'):
                    if line:
                        container_id, name, status, running_time = line.split('\t')
                        tasks.append({
                            'server': server_name,
                            'container_id': container_id,
                            'name': name,
                            'status': status,
                            'running_time': running_time
                        })
                
                ssh.close()
            return tasks
        except Exception as e:
            print(f"获取任务信息失败{str(e)}")
            return []

    def show_user_info(self):
        """显示用户信息和任务"""
        print(f"\n=== 用户信息 ===")
        print(f"用户名: {self.current_user}")
        print(f"角色: {self.config['users'][self.current_user]['role']}")
        
        # 显示用户组信息
        user_group = self.config['users'][self.current_user].get('group', 'default')
        group_info = self.config['user_groups'][user_group]
        print(f"\n用户组信息：")
        print(f"组名：{group_info['name']}")
        print(f"描述：{group_info['description']}")
        print(f"可用服务器：{', '.join(group_info['allowed_servers'])}")
        print(f"最大容器数：{group_info['max_containers']}")
        print(f"最大GPU数：{group_info['max_gpus']}")
        print(f"时间限制：{group_info['time_limit']}小时")
        
        # 显示FTP信息
        registry_server = self.config['registry_server']
        print(f"\nFTP信息：")
        print(f"服务器地址: {registry_server['host']}")
        print(f"端口: 21")
        print(f"用户名：{self.current_user}")
        print(f"密码：与系统登录密码相同")
        print(f"目录：{self.config['users'][self.current_user].get('data_dir', '未创建')}")
        
        # 显示正在运行的任务
        tasks = self.get_user_tasks(self.current_user)
        if tasks:
            print("\n正在运行的任务：")
            print("\n{:<5} {:<15} {:<20} {:<40} {:<15} {:<20}".format(
                "序号", "服务器", "容器ID", "容器称", "状态", "运行时间"
            ))
            print("-" * 115)
            
            for idx, task in enumerate(tasks, 1):
                print("{:<5} {:<15} {:<20} {:<40} {:<15} {:<20}".format(
                    idx,
                    task['server'],
                    task['container_id'],
                    task['name'],
                    task['status'],
                    task['running_time']
                ))
            
            print("\n选项：")
            print("1. 进入容器终端")
            print("2. 打包容器")
            print("0. 返回")
            
            choice = input("\n请选择操作: ").strip()
            if choice == '1':
                self.enter_container(tasks)
            elif choice == '2':
                self.pack_container(tasks)
        else:
            print("暂无运行中的任务")

    def enter_container(self, tasks):
        """进入容器终端"""
        while True:
            print("\n请选择要进入的容器序号（0返）：")
            choice = input().strip()
            
            if choice == '0':
                return
                
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(tasks):
                    task = tasks[idx]
                    server_name = task['server']
                    container_name = task['name']
                    
                    # 获取服务器连接
                    server = self.config['servers'][server_name]
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    
                    try:
                        ssh.connect(
                            hostname=server['host'],
                            port=server['port'],
                            username=server['username'],
                            password=server['password'],
                            timeout=10
                        )
                        
                        print(f"\n正在连接到容器 {container_name}...")
                        print("提示：")
                        print("1. 按 Ctrl+C 退出终端")
                        print("2. 如果显示异常，尝试调整终端窗口大小")
                        
                        # 创建终端管理器并启动会话
                        terminal = TerminalManager(ssh)
                        terminal.start_terminal_session(container_name)
                        
                    finally:
                        ssh.close()
                    return
                    
                else:
                    print("无效的容器序号")
            except ValueError:
                print("请输入有效的数字")
            except Exception as e:
                print(f"操作失败：{str(e)}")

    def change_password(self):
        """修改用户密码"""
        old_password = getpass.getpass("请输入当前密码: ")
        if old_password != self.config['users'][self.current_user]['password']:
            print("当前密码错误")
            return
        
        new_password = getpass.getpass("请输入新密码: ")
        confirm_password = getpass.getpass("请确认新密码: ")
        
        if new_password != confirm_password:
            print("两次输入的密码不一致")
            return
        
        self.config['users'][self.current_user]['password'] = new_password
        self._save_config()
        print("密码修改成功！")

    def show_all_tasks(self):
        """管理员查看所有用户任务"""
        if not self.user_manager.is_admin(self.current_user):
            print("权限不足")
            return
        
        print("\n=== 所有用户任务信息 ===")
        tasks = self.get_user_tasks()
        if tasks:
            print("\n{:<15} {:<20} {:<40} {:<15} {:<20}".format(
                "服务器", "容器ID", "容器名称", "状态", "运行时间"
            ))
            print("-" * 110)
            for task in tasks:
                print("{:<15} {:<20} {:<40} {:<15} {:<20}".format(
                    task['server'],
                    task['container_id'],
                    task['name'],
                    task['status'],
                    task['running_time']
                ))
        else:
            print("暂无运行中的任务")

    def manage_groups(self):
        """管理用户组"""
        if not self.user_manager.is_admin(self.current_user):
            print("权限不足")
            return

        while True:
            print("\n=== 用户组管理 ===")
            print("1. 查看所有用户组")
            print("2. 创建用户组")
            print("3. 修改用户组")
            print("4. 删除用户组")
            print("5. 返回")

            choice = input("请选择操作: ")

            if choice == '1':
                groups = self.group_manager.list_groups()
                print("\n当前用户组：")
                for group_name, group_info in groups.items():
                    print(f"\n组名：{group_name}")
                    print(f"描述：{group_info['description']}")
                    print(f"可用服务器：{', '.join(group_info['allowed_servers'])}")
                    print(f"最大容器数：{group_info['max_containers']}")
                    print(f"最大GPU数：{group_info['max_gpus']}")
                    print(f"时间限制：{group_info['time_limit']}小时")

            elif choice == '2':
                group_name = input("请输入新用户组名称: ")
                description = input("请输入用户组描述: ")
                print("\n可用服务器（用逗号分隔）:")
                for server in self.config['servers'].keys():
                    print(f"- {server}")
                allowed_servers = input("请选择允许使用的服务器: ").split(',')
                max_containers = int(input("请输入最大容器数: "))
                max_gpus = int(input("请输入最大GPU数: "))
                time_limit = int(input("请输入时间限制(小时): "))

                if self.group_manager.create_group(
                    group_name, description, allowed_servers,
                    max_containers, max_gpus, time_limit
                ):
                    print("用户组创建成功！")
                    self._save_config()

            elif choice == '3':
                group_name = input("请输入要修改的用户组名称: ")
                if group_name in self.config['user_groups']:
                    print("\n当前设置：")
                    group_info = self.group_manager.get_group_info(group_name)
                    print(f"描述：{group_info['description']}")
                    print(f"可用服务器：{', '.join(group_info['allowed_servers'])}")
                    print(f"最大容器数：{group_info['max_containers']}")
                    print(f"最大GPU数：{group_info['max_gpus']}")
                    print(f"时间限制：{group_info['time_limit']}小时")

                    description = input("\n请输入新的描述（直接回车保持不变）: ")
                    allowed_servers = input("请输入新服务器列表逗号分隔，直接回车保不变）: ")
                    max_containers = input("请输入新的最大容器数（直接回车保持不变）: ")
                    max_gpus = input("请输入新最大GPU数（直接回车保持不变）: ")
                    time_limit = input("请输入新的时限制（直接回车保持不变）: ")

                    if self.group_manager.modify_group(
                        group_name,
                        description if description else None,
                        allowed_servers.split(',') if allowed_servers else None,
                        int(max_containers) if max_containers else None,
                        int(max_gpus) if max_gpus else None,
                        int(time_limit) if time_limit else None
                    ):
                        print("用户组修改成功！")
                        self._save_config()

            elif choice == '4':
                group_name = input("请输入要删除的用户组名称: ")
                if self.group_manager.delete_group(group_name):
                    print("用户组删除成功！")
                    self._save_config()

            elif choice == '5':
                break

    def show_menu(self):
        try:
            # 先进行登录验证
            if not self.login():
                print("登录失败，程序退出")
                return

            # 登录成功后启动状态更新器
            print("\n正在初始化系统，请稍候...", end='', flush=True)
            self.status_updater = StatusUpdater(self)
            
            # 静默初始化服务器状态
            original_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            try:
                self.cached_server_status = self.get_all_servers_status()
            finally:
                sys.stdout.close()
                sys.stdout = original_stdout
            
            print("\r" + " " * 50 + "\r", end='', flush=True)  # 清除初始化提示
            
            # 启动后台更新
            self.status_updater.start()

            while True:
                print("\n=== 实验室服务管理系统 ===")
                print(f"当前用户: {self.current_user}")
                print("1. 创建深度学习任务")
                print("2. 用户信息")
                print("3. 修改密码")
                print("4. 停止任务")
                print("5. 退出")
                
                if self.current_user and self.user_manager.is_admin(self.current_user):
                    print("6. 用户管理")
                    print("7. 查看所有任务")
                    print("8. 停止任何用户的任务")
                    print("9. 用户组管理")
                    print("10. 服务管理")
                    print("11. 仓库管理")

                choice = input("\n请选择操作: ")
                print()  # 添加空行增加可读性

                if choice == '1':
                    self.create_dl_task()
                elif choice == '2':
                    self.show_user_info()
                elif choice == '3':
                    self.change_password()
                elif choice == '4':
                    self.stop_user_task()
                elif choice == '5':
                    print("感谢使用，再见！")
                    break
                elif choice == '6' and self.user_manager.is_admin(self.current_user):
                    self.user_manager.manage_users()
                elif choice == '7' and self.user_manager.is_admin(self.current_user):
                    self.show_all_tasks()
                elif choice == '8' and self.user_manager.is_admin(self.current_user):
                    self.stop_any_task()
                elif choice == '9' and self.user_manager.is_admin(self.current_user):
                    self.manage_groups()
                elif choice == '10' and self.user_manager.is_admin(self.current_user):
                    self.manage_servers()
                elif choice == '11' and self.user_manager.is_admin(self.current_user):
                    self.manage_registry()
                else:
                    print("无效的选择，请重试")

        finally:
            if self.status_updater:
                self.status_updater.stop()

    def _record_task(self, server_name, container_name, gpu_indices):
        """记录用户任务信息"""
        if 'task_records' not in self.config:
            self.config['task_records'] = {}
        
        if self.current_user not in self.config['task_records']:
            self.config['task_records'][self.current_user] = []
        
        task_info = {
            'server': server_name,
            'container': container_name,
            'gpus': gpu_indices,
            'timestamp': int(time.time())
        }
        
        self.config['task_records'][self.current_user].append(task_info)
        self._save_config()

    def stop_container(self, ssh, server_name, container_name):
        """停止指定的容器"""
        try:
            # 获取容器使用的GPU
            task_records = self.config['task_records'].get(self.current_user, [])
            for task in task_records:
                if task['container'] == container_name:
                    # 放GPU
                    self.gpu_manager.release_gpus(server_name, task['gpus'])
                    break

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
            
            print("容器成功停止并删除")
            
            # 立即更新服务器状态缓存
            self.cached_server_status = None  # 清除缓存
            self.last_status_update = 0  # 重置更新时间戳
            # 静默更新服务器状态
            original_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            try:
                self.get_all_servers_status()
            finally:
                sys.stdout.close()
                sys.stdout = original_stdout
            
            return True
        except Exception as e:
            print(f"操作失败：{str(e)}")
            return False

    def stop_user_task(self):
        """停止用户的任务"""
        try:
            tasks = self.get_user_tasks(self.current_user)
            if not tasks:
                print("当前没有运行中的任务")
                return
            
            while True:
                print("\n当前运行的任务：")
                print("\n{:<5} {:<15} {:<20} {:<40} {:<15} {:<20}".format(
                    "序号", "服器", "器ID", "器名称", "状态", "运行时间"
                ))
                print("-" * 115)
                
                for idx, task in enumerate(tasks, 1):
                    print("{:<5} {:<15} {:<20} {:<40} {:<15} {:<20}".format(
                        idx,
                        task['server'],
                        task['container_id'],
                        task['name'],
                        task['status'],
                        task['running_time']
                    ))
                
                print("\n请选择要停止的任务序号（多个任务用逗号分隔，如：1,2,3）")
                print("输入 'all' 停止所任务")
                print("输入 '0' 返回")
                choice = input().strip().lower()
                
                if choice == '0':
                    return
                
                selected_indices = []
                if choice == 'all':
                    selected_indices = list(range(len(tasks)))
                else:
                    try:
                        # 解析用户输入的序号
                        for num in choice.split(','):
                            idx = int(num.strip()) - 1
                            if 0 <= idx < len(tasks):
                                selected_indices.append(idx)
                            else:
                                print(f"无效的序号：{idx + 1}")
                                continue
                    except ValueError:
                        print("请输入有效的数字")
                        continue
                
                if not selected_indices:
                    print("未择任何有效的任务")
                    continue
                
                # 显示选中的任务
                print("\n将要停止以下任务：")
                for idx in selected_indices:
                    task = tasks[idx]
                    print(f"- {task['name']} (在 {task['server']} 上)")
                
                # 确认操作
                print("\n确认要停止这些容器吗？(y/n)")
                if input().lower() != 'y':
                    print("操作已取消")
                    continue
                
                # 按服务器分组任务，减少SSH连接次数
                server_tasks = {}
                for idx in selected_indices:
                    task = tasks[idx]
                    if task['server'] not in server_tasks:
                        server_tasks[task['server']] = []
                    server_tasks[task['server']].append(task)
                
                # 处理每个服务器上的任务
                for server_name, server_tasks_list in server_tasks.items():
                    try:
                        # 连接到服务器
                        server = self.config['servers'][server_name]
                        ssh = paramiko.SSHClient()
                        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        ssh.connect(
                            hostname=server['host'],
                            port=server['port'],
                            username=server['username'],
                            password=server['password']
                        )
                        
                        # 停止该服务器上的所有选中容器
                        for task in server_tasks_list:
                            if self.stop_container(ssh, server_name, task['name']):
                                print(f"成功停止容器：{task['name']}")
                            else:
                                print(f"停止容器失败：{task['name']}")
                        
                        ssh.close()
                    except Exception as e:
                        print(f"连接服务器 {server_name} 失败：{str(e)}")
                
                # 更新任务列表
                tasks = self.get_user_tasks(self.current_user)
                if not tasks:
                    print("\n所有任务已止")
                    return
                
                print("\n是否继续停止其他任务？(y/n)")
                if input().lower() != 'y':
                    return
                
        except Exception as e:
            print(f"操作失败：{str(e)}")

    def stop_any_task(self):
        """管理员停止任何用户的任务"""
        if not self.user_manager.is_admin(self.current_user):
            print("权限不足")
            return
        
        try:
            tasks = self.get_user_tasks()  # 获取所有任务
            if not tasks:
                print("当前没有运行中的任务")
                return
            
            while True:
                print("\n所有运行中的任务：")
                print("\n{:<5} {:<15} {:<20} {:<40} {:<15} {:<20}".format(
                    "号", "服务器", "容器ID", "容器名称", "状态", "运行时间"
                ))
                print("-" * 115)
                
                for idx, task in enumerate(tasks, 1):
                    print("{:<5} {:<15} {:<20} {:<40} {:<15} {:<20}".format(
                        idx,
                        task['server'],
                        task['container_id'],
                        task['name'],
                        task['status'],
                        task['running_time']
                    ))
                
                print("\n请选择要停止的任务序号（多个任务用逗号分隔，如：1,2,3）")
                print("输入 'all' 停止所有任务")
                print("输入 '0' 返回")
                choice = input().strip().lower()
                
                if choice == '0':
                    return
                
                selected_indices = []
                if choice == 'all':
                    selected_indices = list(range(len(tasks)))
                else:
                    try:
                        # 解析用户输入的序号
                        for num in choice.split(','):
                            idx = int(num.strip()) - 1
                            if 0 <= idx < len(tasks):
                                selected_indices.append(idx)
                            else:
                                print(f"无效的序号：{idx + 1}")
                                continue
                    except ValueError:
                        print("请输入有效的数字")
                        continue
                
                if not selected_indices:
                    print("未选择任何有效的任务")
                    continue
                
                # 显示选中的任务
                print("\n将要停止以下任务：")
                for idx in selected_indices:
                    task = tasks[idx]
                    print(f"- {task['name']} (在 {task['server']} 上)")
                
                # 确认操作
                print("\n确认要停止这些容器吗？(y/n)")
                if input().lower() != 'y':
                    print("操作已取消")
                    continue
                
                # 按服务器分组任务，减少SSH连接次数
                server_tasks = {}
                for idx in selected_indices:
                    task = tasks[idx]
                    if task['server'] not in server_tasks:
                        server_tasks[task['server']] = []
                    server_tasks[task['server']].append(task)
                
                # 处理每个服务器上的任务
                for server_name, server_tasks_list in server_tasks.items():
                    try:
                        # 连接到服务器
                        server = self.config['servers'][server_name]
                        ssh = paramiko.SSHClient()
                        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        ssh.connect(
                            hostname=server['host'],
                            port=server['port'],
                            username=server['username'],
                            password=server['password']
                        )
                        
                        # 停止该服务器上的所有选中容器
                        for task in server_tasks_list:
                            if self.stop_container(ssh, server_name, task['name']):
                                print(f"成功停止容器：{task['name']}")
                            else:
                                print(f"停止容器失败：{task['name']}")
                        
                        ssh.close()
                    except Exception as e:
                        print(f"连接服务器 {server_name} 失败：{str(e)}")
                
                # 更新任务列表
                tasks = self.get_user_tasks()
                if not tasks:
                    print("\n所有任��已停止")
                    return
                
                print("\n是否继续停止其他任务？(y/n)")
                if input().lower() != 'y':
                    return
                
        except Exception as e:
            print(f"操作失败：{str(e)}")

    def pack_container(self, tasks):
        """打包容器"""
        while True:
            print("\n请选择要打包的容器序号（0返回）：")
            choice = input().strip()
            
            if choice == '0':
                return
            
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(tasks):
                    task = tasks[idx]
                    server_name = task['server']
                    container_name = task['name']
                    
                    # 获取服务器连接
                    server = self.config['servers'][server_name]
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    
                    try:
                        ssh.connect(
                            hostname=server['host'],
                            port=server['port'],
                            username=server['username'],
                            password=server['password'],
                            timeout=10
                        )
                        
                        print(f"\n正在打包容器 {container_name}...")
                        
                        # 让用户输入镜像名称和标签
                        print("\n请输入镜像名称（默认：当前用户名）：")
                        image_name = input().strip()
                        if not image_name:
                            image_name = self.current_user  # 用户名作为默认值
                        
                        print("请输入标签名（默认：当前日期）：")
                        tag = input().strip()
                        if not tag:
                            tag = time.strftime("%Y%m%d")
                        
                        # 提交容器为新镜
                        local_image = f"{image_name}:{tag}"
                        cmd = f"docker commit {container_name} {local_image}"
                        stdin, stdout, stderr = ssh.exec_command(cmd)
                        error = stderr.read().decode()
                        if error:
                            print(f"创建镜像败：{error}")
                            continue
                        
                        print(f"\n本地镜像创建成功：{local_image}")
                        
                        # 询问是否推送到仓库
                        print("\n是否要推送到远程仓库？(y/n)")
                        if input().lower() == 'y':
                            # 获取仓库信息
                            registry = self.config['registry_server']
                            registry_url = f"{registry['host']}:{registry['registry_port']}"
                            
                            # 标记镜像，添加用户目录
                            full_image_name = f"{registry_url}/{self.current_user}/{local_image}"
                            cmd = f"docker tag {local_image} {full_image_name}"
                            stdin, stdout, stderr = ssh.exec_command(cmd)
                            error = stderr.read().decode()
                            if error:
                                print(f"标记镜像失败：{error}")
                                continue
                            
                            # 推送镜像到仓库
                            print(f"正在推送镜像到仓库 {registry_url}...")
                            cmd = f"docker push {full_image_name}"
                            stdin, stdout, stderr = ssh.exec_command(cmd)
                            
                            # 实时显示推送进度
                            while True:
                                line = stdout.readline()
                                if not line:
                                    break
                                print(line.strip())
                            
                            error = stderr.read().decode()
                            if error and "error" in error.lower():
                                print(f"推送镜像失败：{error}")
                                continue
                            
                            print(f"\n镜像已成功推送到仓库")
                            print(f"远程镜像：{full_image_name}")
                            
                            # 询问是否删除远程标记
                            print("\n是否删除远程标记？(y/n)")
                            if input().lower() == 'y':
                                ssh.exec_command(f"docker rmi {full_image_name}")
                        
                        print(f"\n本地镜像：{local_image}")
                        
                    finally:
                        ssh.close()
                    return
                
                else:
                    print("无效的容器序号")
            except ValueError:
                print("请输入有效的数字")
            except Exception as e:
                print(f"操作失败：{str(e)}")

    def manage_servers(self):
        """管理服务器配置"""
        while True:
            print("\n=== 服务器管理 ===")
            print("1. 查看所有服务器")
            print("2. 添加服务器")
            print("3. 修改服务器")
            print("4. 删除服务器")
            print("5. 测试服务器连接")
            print("0. 返回")

            choice = input("\n请选择操作: ")

            if choice == '1':
                print("\n当前服务器列表：")
                for name, info in self.config['servers'].items():
                    print(f"\n服务器名：{name}")
                    print(f"主机地址：{info['host']}")
                    print(f"SSH端口：{info['port']}")
                    print(f"用户名：{info['username']}")
                    
            elif choice == '2':
                name = input("\n请输入服务器名称: ")
                if name in self.config['servers']:
                    print("服务器名称已存在")
                    continue
                    
                host = input("请输入主机地址: ")
                port = input("请输入SSH端口(默认22): ") or "22"
                username = input("请输入用户名: ")
                password = getpass.getpass("请输入密码: ")
                
                # 测试连接
                try:
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(
                        hostname=host,
                        port=int(port),
                        username=username,
                        password=password,
                        timeout=10
                    )
                    ssh.close()
                    
                    self.config['servers'][name] = {
                        'host': host,
                        'port': int(port),
                        'username': username,
                        'password': password
                    }
                    self._save_config()
                    print("服务器添加成功！")
                    
                except Exception as e:
                    print(f"连接测试失败：{str(e)}")
                    
            elif choice == '3':
                name = input("\n请输入要修改的服务器名称: ")
                if name not in self.config['servers']:
                    print("服务器不存在")
                    continue
                    
                print("\n当前配置：")
                info = self.config['servers'][name]
                print(f"主机地址：{info['host']}")
                print(f"SSH端口：{info['port']}")
                print(f"用户名：{info['username']}")
                
                host = input("\n请输入新的主机地址（直接回车保持不变）: ") or info['host']
                port = input("请输入新的SSH端口（直接回车保持不变）: ") or str(info['port'])
                username = input("请输入新的用户名（直接回车保持不变）: ") or info['username']
                password = getpass.getpass("请输入新的密码（直接回车保持不变）: ")
                
                if not password:
                    password = info['password']
                
                # 测试新配置
                try:
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(
                        hostname=host,
                        port=int(port),
                        username=username,
                        password=password,
                        timeout=10
                    )
                    ssh.close()
                    
                    self.config['servers'][name] = {
                        'host': host,
                        'port': int(port),
                        'username': username,
                        'password': password
                    }
                    self._save_config()
                    print("服务器配置已更新！")
                    
                except Exception as e:
                    print(f"连接测试失败：{str(e)}")
                    
            elif choice == '4':
                name = input("\n请输入要删除的服务器名称: ")
                if name not in self.config['servers']:
                    print("服务器不存在")
                    continue
                    
                confirm = input(f"确定要删除服务器 {name} 吗？(y/n): ")
                if confirm.lower() == 'y':
                    del self.config['servers'][name]
                    self._save_config()
                    print("服务器已删除")
                    
            elif choice == '5':
                name = input("\n请输入要测试的服务器名称: ")
                if name not in self.config['servers']:
                    print("服务器不存在")
                    continue
                    
                info = self.config['servers'][name]
                try:
                    print(f"正在测试连接 {name} ({info['host']})...")
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(
                        hostname=info['host'],
                        port=info['port'],
                        username=info['username'],
                        password=info['password'],
                        timeout=10
                    )
                    
                    # 测试GPU可用性
                    print("正在检查GPU...")
                    gpu_info = self.check_gpu_status_with_ssh(ssh, name)
                    if gpu_info:
                        print(f"发现 {len(gpu_info)} 个GPU:")
                        for gpu in gpu_info:
                            print(f"- {gpu['name']}")
                    else:
                        print("未检测到GPU")
                    
                    ssh.close()
                    print("连接测试成功！")
                    
                except Exception as e:
                    print(f"连接测试失败：{str(e)}")
                    
            elif choice == '0':
                break

    def manage_registry(self):
        """管理仓库配置"""
        while True:
            print("\n=== 仓库管理 ===")
            print("1. 查看仓库配置")
            print("2. 修改仓库配置")
            print("3. 测试仓库连接")
            print("4. 查看仓库镜像")
            print("0. 返回")

            choice = input("\n请选择操作: ")

            if choice == '1':
                print("\n当前仓库配置：")
                registry = self.config['registry_server']
                print(f"主机地址：{registry['host']}")
                print(f"仓库端口：{registry['registry_port']}")
                print(f"NFS主机：{registry['nfs_host']}")
                print(f"NFS路径：{registry['nfs_path']}")
                
            elif choice == '2':
                registry = self.config['registry_server']
                print("\n当前配置：")
                print(f"主机地址：{registry['host']}")
                print(f"仓库端口：{registry['registry_port']}")
                print(f"NFS主机：{registry['nfs_host']}")
                print(f"NFS路径：{registry['nfs_path']}")
                
                host = input("\n请输入新的主机地址（直接回车保持不变）: ") or registry['host']
                registry_port = input("请输入新的仓库端口（直接回车保持不变）: ") or str(registry['registry_port'])
                nfs_host = input("请输入新的NFS主机（直接回车保持不变）: ") or registry['nfs_host']
                nfs_path = input("请输入新的NFS路径（直接回车保持不变）: ") or registry['nfs_path']
                
                # 测试连接
                self.config['registry_server'].update({
                    'host': host,
                    'registry_port': int(registry_port),
                    'nfs_host': nfs_host,
                    'nfs_path': nfs_path
                })
                
                # 重新初始化registry manager
                self.registry_manager = RegistryManager(self.config)
                
                if self.registry_manager.test_connection():
                    self._save_config()
                    print("仓库配置已更新！")
                else:
                    print("仓库连接测试失败，配置未保存")
                    
            elif choice == '3':
                if self.registry_manager.test_connection():
                    print("仓库连接测试成功！")
                else:
                    print("仓库连接测试失败")
                    
            elif choice == '4':
                repositories = self.registry_manager.get_catalog()
                if repositories:
                    print("\n仓库中的镜像：")
                    for repo in repositories:
                        print(f"\n镜像：{repo}")
                        tags = self.registry_manager.get_tags(repo)
                        if tags:
                            print("签：")
                            for tag in tags:
                                size = self.registry_manager.get_image_size(repo, tag)
                                print(f"  - {tag} ({size})")
                else:
                    print("仓库中没有镜像")
                    
            elif choice == '0':
                break

if __name__ == "__main__":
    server = LabServer()
    server.show_menu() 