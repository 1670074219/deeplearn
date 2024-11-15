import yaml
import paramiko
import getpass
from user_manager import UserManager

class LabServer:
    def __init__(self):
        self.config = self.load_config()
        self.user_manager = UserManager(self.config)
        self.current_user = None
        self.cached_server_status = None

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
                    if password == '0':  # 允许用户输入0回用户名输入
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
            
            # 根据不同的仓库构建不同的镜像名称和命令
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
                
                print(f"正在远程服务器上登录Docker仓库 {registry_info['url']}...")
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
            print(f"执行命令：{pull_cmd}")
            
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
                        print("2. 尝试使用其他镜像源")
                        print("3. 如果可能，考虑使用私有仓库")
                    print(f"拉取镜像失败：{error}")
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

    def get_registry_images(self, ssh):
        """获取仓库服务器上的镜像列表"""
        try:
            # 先连接到仓库服务器
            registry_ssh = paramiko.SSHClient()
            registry_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            registry_server = self.config['registry_server']
            print(f"正在连务器 {registry_server['host']}...")
            print(f"使用用户名: {registry_server['username']}")
            
            try:
                registry_ssh.connect(
                    hostname=registry_server['host'],
                    port=registry_server['port'],
                    username=registry_server['username'],
                    password=registry_server['password'],
                    timeout=10
                )
                print("仓库服务器连接成功！")
            except paramiko.AuthenticationException:
                print(f"认证失败：请检查用户名和密码是否正确")
                return []
            except paramiko.SSHException as e:
                print(f"SSH连接错误：{str(e)}")
                return []
            except Exception as e:
                print(f"连接错误：{str(e)}")
                return []

            # 获取仓库中的镜像列表（包含大小信息）
            print("正在获取镜像列表...")
            cmd = "docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}'"
            stdin, stdout, stderr = registry_ssh.exec_command(cmd)
            output = stdout.read().decode()
            error = stderr.read().decode()
            
            if error:
                print(f"获取仓库镜像列表失败：{error}")
                return []
            
            images = []
            for line in output.strip().split('\n'):
                if line and not line.startswith("REPOSITORY"):
                    image_info = line.split('\t')
                    if len(image_info) == 2:
                        images.append({
                            'name': image_info[0],
                            'size': image_info[1],
                            'source': '远程仓库'
                        })
            
            if not images:
                print("未找到任何镜像")
            else:
                print(f"找到 {len(images)} 个镜像")
            
            registry_ssh.close()
            return images
            
        except Exception as e:
            print(f"获取仓库镜像列表时出错：{str(e)}")
            return []
        finally:
            try:
                registry_ssh.close()
            except:
                pass

    def create_user_data_dir(self, ssh, username):
        """在仓库服务器上创建用户的数据目录和FTP虚拟用户"""
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
            
            # 先检查目录是否存在
            check_cmd = f"[ -d {user_dir} ] && echo 'exists' || echo 'not exists'"
            stdin, stdout, stderr = registry_ssh.exec_command(check_cmd)
            if stdout.read().decode().strip() == 'exists':
                print(f"用户目录已存在：{user_dir}")
            else:
                # 创建目录并设置权限
                cmd = f"sudo mkdir -p {user_dir} && sudo chmod 755 {user_dir}"
                print(f"正在创建用户数据目录：{user_dir}")
                stdin, stdout, stderr = registry_ssh.exec_command(cmd)
                error = stderr.read().decode()
                
                if error:
                    print(f"创建用户数据目录失败：{error}")
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

            print(f"\nFTP 虚拟用户配置完成：")
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

    def get_all_servers_status(self):
        """获取所有服务器的状态信息"""
        server_gpu_status = {}
        valid_servers = []
        
        for idx, (server_name, server_info) in enumerate(self.config['servers'].items(), 1):
            gpu_info = self.check_gpu_status(server_name)
            if gpu_info is not None:
                used_gpus = sum(1 for gpu in gpu_info if gpu['utilization'] > 0)
                total_gpus = len(gpu_info)
                gpu_model = gpu_info[0]['name'] if gpu_info else "未知"
                avg_util = sum(gpu['utilization'] for gpu in gpu_info) / total_gpus
                
                server_gpu_status[str(idx)] = {
                    'name': server_name,
                    'host': server_info['host'],
                    'gpu_info': gpu_info,
                    'used_gpus': used_gpus,
                    'total_gpus': total_gpus,
                    'gpu_model': gpu_model,
                    'avg_util': avg_util
                }
                valid_servers.append(server_name)
        
        return server_gpu_status

    def display_server_status(self, server_status):
        """显示服务器状态信息"""
        print("\n{:<5} {:<10} {:<15} {:<30} {:<10} {:<15} {:<10}".format(
            "序号", "服务器", "IP地址", "GPU型号", "GPU数量", "已用/总数", "使用率"
        ))
        print("-" * 95)
        
        for idx, info in server_status.items():
            print("{:<5} {:<10} {:<15} {:<30} {:<10} {:<15} {:<10.1f}%".format(
                idx,
                info['name'],
                info['host'],
                info['gpu_model'],
                info['total_gpus'],
                f"{info['used_gpus']}/{info['total_gpus']}",
                info['avg_util']
            ))

    def create_dl_task(self):
        if not self.current_user:
            print("请先登录")
            return

        while True:  # 服务器选择循环
            if self.cached_server_status is None:
                print("正在获取服务器信息...")
                self.cached_server_status = self.get_all_servers_status()
            
            print("\n可用的服务器：")
            self.display_server_status(self.cached_server_status)
            
            print("\n选项：")
            print("0. 返回主菜单")
            print("r. 刷新服务器信息")
            server_choice = input("请选择服务器序号: ").strip().lower()
            
            if server_choice == '0':
                return
            elif server_choice == 'r':
                print("正在刷新服务器信息...")
                self.cached_server_status = self.get_all_servers_status()
                continue
            
            if server_choice not in self.cached_server_status:
                print("错误：无效的服务器序号")
                continue

            # 服务器选择成功，进入镜像选择流程
            while True:  # 镜像选择循环
                try:
                    server_info = self.cached_server_status[server_choice]
                    server_name = server_info['name']
                    server = self.config['servers'][server_name]
                    
                    # 显示GPU信息
                    print(f"\n服务器 {server_name} 的GPU详细信息：")
                    # ... (GPU信息显示代码保持不变)

                    # 连接服务器
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(
                        hostname=server['host'],
                        port=server['port'],
                        username=server['username'],
                        password=server['password']
                    )

                    # 获取本地镜像列表
                    print("\n获取本地Docker镜像列表...")
                    local_images = self.get_server_docker_images(ssh)
                    
                    print("\n本地可用的Docker镜像：")
                    for idx, image in enumerate(local_images, 1):
                        print(f"{idx}. {image['name']} [本地] ({image['size']})")
                    
                    print("\n选项：")
                    print("1. 使用本地镜像")
                    print("2. 使用远程仓库镜像")
                    print("0. 返回服务器选择")
                    
                    choice = input("请选择: ").strip()
                    
                    if choice == '0':
                        ssh.close()
                        break  # 返回服务器选择
                    
                    if choice == '1':  # 使用本地镜像
                        while True:
                            print("\n请选择本地镜像编号（0返回上一步）:")
                            choice = input().strip()
                            if choice == '0':
                                break
                            try:
                                idx = int(choice) - 1
                                if 0 <= idx < len(local_images):
                                    image_name = local_images[idx]['name']
                                    # 进入容器创建流程
                                    if self.create_container(ssh, server_name, image_name):
                                        return  # 创建成功，退出整个函数
                                else:
                                    print("无效的选择，请重试")
                            except ValueError:
                                print("请输入有效的数字")
                    
                    elif choice == '2':  # 使用远程仓库镜像
                        print("\n获取远程仓库镜像列表...")
                        registry_images = self.get_registry_images(ssh)
                        
                        while True:
                            print("\n远程仓库可用的Docker镜像：")
                            for idx, image in enumerate(registry_images, 1):
                                is_local = any(local_img['name'] == image['name'] for local_img in local_images)
                                status = "[本地已存在]" if is_local else "[远程仓库]"
                                print(f"{idx}. {image['name']} {status} (大小: {image['size']})")
                            
                            print("\n请选择镜像编号（0返回上一步）:")
                            choice = input().strip()
                            if choice == '0':
                                break
                            
                            try:
                                idx = int(choice) - 1
                                if 0 <= idx < len(registry_images):
                                    image_name = registry_images[idx]['name']
                                    # 检查是否需要拉取
                                    if not any(local_img['name'] == image_name for local_img in local_images):
                                        if not self.pull_docker_image(ssh, image_name, self.config['docker_registries'][0]):
                                            continue
                                    # 进入容器创建流程
                                    if self.create_container(ssh, server_name, image_name):
                                        return  # 创建成功，退出整个函数
                                else:
                                    print("无效的选择，请重试")
                            except ValueError:
                                print("请输入有效的数字")
                
                except Exception as e:
                    print(f"操作失败：{str(e)}")
                finally:
                    try:
                        ssh.close()
                    except:
                        pass

    def create_container(self, ssh, server_name, image_name):
        """创建容器的具体流程"""
        try:
            # 获取GPU数量
            print("\n请输入要使用的GPU数量（0返回上一步）:")
            gpu_num = input().strip()
            if gpu_num == '0':
                return False
            
            # 获取端口映射
            print("\n请输入主机端口（0返回上一步）:")
            host_port = input().strip()
            if host_port == '0':
                return False
            
            # 创建容器
            # ... (容器创建代码)
            
            return True  # 创建成功
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
                
                # 获取所有运行中的容器
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
        
        # 显示FTP信息
        registry_server = self.config['registry_server']
        print(f"\nFTP信息：")
        print(f"服务器地址: {registry_server['host']}")
        print(f"端口: 21")
        print(f"用户名: {self.current_user}")
        print(f"密码: 与系统登录密码相同")
        print(f"目录: {self.config['users'][self.current_user].get('data_dir', '未创建')}")
        
        # 显示用户限制信息
        user_limits = self.config['tasks']['user_limits'].get(
            self.current_user,
            self.config['tasks']['user_limits']['default']
        )
        print(f"\n使用限制：")
        print(f"最大容器数: {user_limits['max_containers']}")
        print(f"最大GPU数: {user_limits['max_gpus']}")
        print(f"时间限制: {user_limits['time_limit']}小时")
        
        # 显示正在运行的任务
        print("\n正在运行的任务：")
        tasks = self.get_user_tasks(self.current_user)
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

    def manage_user_limits(self):
        """管理用户使用限制"""
        if not self.user_manager.is_admin(self.current_user):
            print("权限不足")
            return
        
        while True:
            print("\n=== 管理用户限制 ===")
            print("1. 查看所有用户限制")
            print("2. 设置用户限制")
            print("3. 返回")
            
            choice = input("请选择操作: ")
            
            if choice == '1':
                print("\n当前用户限制：")
                for username in self.config['users']:
                    limits = self.config['tasks']['user_limits'].get(
                        username,
                        self.config['tasks']['user_limits']['default']
                    )
                    print(f"\n用户: {username}")
                    print(f"最大容器数: {limits['max_containers']}")
                    print(f"最大GPU数: {limits['max_gpus']}")
                    print(f"时间限制: {limits['time_limit']}小时")
            
            elif choice == '2':
                username = input("请输入用户名: ")
                if username not in self.config['users']:
                    print("用户不存在")
                    continue
                
                try:
                    max_containers = int(input("请输入最大容器数: "))
                    max_gpus = int(input("请输入最大GPU数: "))
                    time_limit = int(input("请输入时间限制(小时): "))
                    
                    self.config['tasks']['user_limits'][username] = {
                        'max_containers': max_containers,
                        'max_gpus': max_gpus,
                        'time_limit': time_limit
                    }
                    self._save_config()
                    print("设置成功！")
                except ValueError:
                    print("输入无效，请输入数字")
            
            elif choice == '3':
                break

    def show_menu(self):
        # 先进行登录验证
        if not self.login():
            print("登录失败，程序退出")
            return

        while True:
            print("\n=== 实验室服务器管理系统 ===")
            print(f"当前用户: {self.current_user}")
            print("1. 创建深度学习任务")
            print("2. 用户信息")
            print("3. 修改密码")
            print("4. 退出")
            
            if self.current_user and self.user_manager.is_admin(self.current_user):
                print("5. 用户管理")
                print("6. 查看所有任��")
                print("7. 管理用户限制")

            choice = input("请选择操作: ")

            if choice == '1':
                self.create_dl_task()
            elif choice == '2':
                self.show_user_info()
            elif choice == '3':
                self.change_password()
            elif choice == '4':
                print("感谢使用，再见！")
                break
            elif choice == '5' and self.user_manager.is_admin(self.current_user):
                self.user_manager.manage_users()
            elif choice == '6' and self.user_manager.is_admin(self.current_user):
                self.show_all_tasks()
            elif choice == '7' and self.user_manager.is_admin(self.current_user):
                self.manage_user_limits()
            else:
                print("无效的选择，请重试")

if __name__ == "__main__":
    server = LabServer()
    server.show_menu() 