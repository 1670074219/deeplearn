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
        """在仓库服务器上创建用户的数据目录"""
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

            # 建用户目录
            user_dir = f"{registry_server['nfs_path']}/{username}"
            
            # 先检查目录是否存在
            check_cmd = f"[ -d {user_dir} ] && echo 'exists' || echo 'not exists'"
            stdin, stdout, stderr = registry_ssh.exec_command(check_cmd)
            if stdout.read().decode().strip() == 'exists':
                print(f"用户目录已存在：{user_dir}")
            else:
                # 创建目录并设置权限
                cmd = f"sudo mkdir -p {user_dir} && sudo chmod 777 {user_dir}"
                print(f"正在创建用户数据目录：{user_dir}")
                stdin, stdout, stderr = registry_ssh.exec_command(cmd)
                error = stderr.read().decode()
                
                if error:
                    print(f"创建用户数据目录失败：{error}")
                    return None
            
            # 更新用户配置
            self.config['users'][username]['data_dir'] = user_dir
            self._save_config()
            
            print(f"用户数据目录创建/确认成功：{user_dir}")
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

        while True:  # 外层循环，用于服务器选择
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

            server_info = self.cached_server_status[server_choice]
            server_name = server_info['name']
            gpu_info = server_info['gpu_info']
            
            # 显示选中服务器的详细GPU信息
            print(f"\n服务器 {server_name} 的GPU详细信息：")
            print("\n{:<5} {:<30} {:<12} {:<12} {:<12} {:<10}".format(
                "GPU", "型号", "总内存(MB)", "已用(MB)", "可用(MB)", "使用率(%)"
            ))
            print("-" * 85)
            
            for gpu in gpu_info:
                print("{:<5} {:<30} {:<12.0f} {:<12.0f} {:<12.0f} {:<10.1f}".format(
                    gpu['index'],
                    gpu['name'],
                    gpu['total_memory'],
                    gpu['used_memory'],
                    gpu['free_memory'],
                    gpu['utilization']
                ))

            available_gpus = sum(1 for gpu in gpu_info if gpu['utilization'] < 5)
            print(f"\n可用GPU数量: {available_gpus}")

            try:
                server = self.config['servers'][server_name]
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(
                    hostname=server['host'],
                    port=server['port'],
                    username=server['username'],
                    password=server['password']
                )

                while True:  # 内层循环，用于镜像选择
                    print("\n获取本地Docker镜像列表...")
                    local_images = self.get_server_docker_images(ssh)
                    
                    print("\n本地可用的Docker镜像：")
                    for idx, image in enumerate(local_images, 1):
                        print(f"{idx}. {image['name']} [本地] ({image['size']})")
                    
                    choice = input("\n是否使用本地镜像？(y/n/0返回): ").lower().strip()
                    if choice == '0':
                        break  # 跳出内层循环，返回服务器选择
                    if choice not in ['y', 'n']:
                        print("请输入 'y' 或 'n' 或 '0'返回")
                        continue

                    if choice == 'y':
                        while True:
                            print("\n输入0返回上一步")
                            choice = input("\n请选择本地镜像编号: ")
                            if choice == '0':
                                continue  # 继续外层循环，重新选择是否使用本地镜像
                            try:
                                idx = int(choice) - 1
                                if 0 <= idx < len(local_images):
                                    selected_image = local_images[idx]
                                    image_name = selected_image['name']
                                    break  # 成功选择镜像，跳出内层循环
                                else:
                                    print("无效的选择，请重试")
                            except ValueError:
                                print("请输入有效的数字")
                        break  # 成功选择镜像后，跳出外层循环
                    else:
                        print("\n获取远程仓库镜像列表...")
                        registry_images = self.get_registry_images(ssh)
                        
                        print("\n远程仓库可用的Docker镜像：")
                        for idx, image in enumerate(registry_images, 1):
                            # 检查该镜像是否已在本地存在
                            is_local = any(local_img['name'] == image['name'] for local_img in local_images)
                            status = "[本地已存在]" if is_local else "[远程仓库]"
                            print(f"{idx}. {image['name']} {status} (大小: {image['size']})")
                        
                        while True:
                            print("\n输入0返回上一步")
                            choice = input("\n请选择镜像编号: ")
                            if choice == '0':
                                continue  # 继续外层循环，重新选择是否使用本地镜像
                            try:
                                idx = int(choice) - 1
                                if 0 <= idx < len(registry_images):
                                    selected_image = registry_images[idx]
                                    image_name = selected_image['name']
                                    
                                    # 检查是否需要拉取
                                    if any(local_img['name'] == image_name for local_img in local_images):
                                        print(f"\n提示：镜像 {image_name} 已在本地存在，无需从远程仓库拉取")
                                    else:
                                        # 判断镜像来源
                                        if 'docker.io' in image_name or '/' in image_name:
                                            # Docker Hub镜像
                                            registry_info = next(reg for reg in self.config['docker_registries'] 
                                                      if reg['url'] == 'docker.io')
                                        else:
                                            # 私有仓库镜像
                                            registry_info = next(reg for reg in self.config['docker_registries'] 
                                                      if reg['url'] != 'docker.io')
                                        
                                        if not self.pull_docker_image(ssh, image_name, registry_info):
                                            print("拉取镜像失败，操作终止")
                                            return
                                    break  # 成功选择镜像，跳出内层循环
                                else:
                                    print("无效的选择，请重试")
                            except ValueError:
                                print("请输入有效的数字")
                        break  # 成功选择镜像后，跳出外层循环

                # 成功选择镜像后的处理
                # 获取用户的工作目录
                print("\n输入0返回上一步")
                work_dir = input("请输入工作目录路径（回车使用默认 /home/workspace）: ").strip()
                if work_dir == '0':
                    continue  # 返回镜像选择
                if not work_dir:
                    work_dir = "/home/workspace"

                # 获取要使用的GPU数量
                while True:
                    print("\n输入0返回上一步")
                    gpu_num = input(f"请输入要使用的GPU数量（最多 {available_gpus} 个，回车使用默认值1）: ").strip()
                    if gpu_num == '0':
                        continue  # 返回工作目录选择
                    if not gpu_num:
                        gpu_num = "1"
                    
                    try:
                        gpu_num = int(gpu_num)
                        if 1 <= gpu_num <= available_gpus:
                            break
                        else:
                            print(f"错误：GPU数量必须在1到{available_gpus}之间")
                    except ValueError:
                        print("错误：请输入有效的GPU数量")

                # 获取用户输入的端口映射
                print("\n输入0返回上一步")
                host_port = input("请输入主机端口（回车使用默认8080）: ").strip()
                if host_port == '0':
                    continue  # 返回GPU数量选择
                if not host_port:
                    host_port = "8080"

                container_port = input("请输入容器端口（回车使用默认8080）: ").strip()
                if container_port == '0':
                    continue  # 返回主机端口选择
                if not container_port:
                    container_port = "8080"

                try:
                    # 检查用户是否已有数据目录，如果没有则创建
                    if not self.config['users'][self.current_user].get('data_dir'):
                        user_data_dir = self.create_user_data_dir(ssh, self.current_user)
                        if not user_data_dir:
                            print("创建用户数据目录失败，操作终止")
                            return
                    else:
                        user_data_dir = self.config['users'][self.current_user]['data_dir']

                    # 生成容器名称
                    safe_image_name = image_name.replace('/', '_').replace(':', '_')
                    container_name = f"{self.current_user}_{server_name}_{safe_image_name}"

                    # 构建Docker运行命令，移除工作目录挂载
                    docker_cmd = (
                        f"docker run -d --gpus '\"device={','.join(str(i) for i in range(gpu_num))}\"' "
                        f"-v {user_data_dir}:/data "  # 只保留数据目录挂载
                        f"-p {host_port}:{container_port} "
                        f"--name {container_name} "
                        f"{image_name} "
                        f"tail -f /dev/null"
                    )

                    print(f"\n执行命令：{docker_cmd}")
                    stdin, stdout, stderr = ssh.exec_command(docker_cmd)
                    error = stderr.read().decode()
                    if error:
                        print(f"创建Docker容器时出错：{error}")
                        return

                    container_id = stdout.read().decode().strip()
                    print(f"\n成功创建Docker容器！")
                    print(f"容器ID: {container_id}")
                    print(f"工作目录: {work_dir}")
                    print(f"使用GPU数量: {gpu_num}")
                    return  # 成功创建容器后退出

                except Exception as e:
                    print(f"创建任务失败：{str(e)}")
                    return

            except Exception as e:
                print(f"创建任务失败：{str(e)}")
            finally:
                ssh.close()

    def show_menu(self):
        # 先进行登录验证
        if not self.login():
            print("登录失败，程序退出")
            return

        while True:
            print("\n=== 实验室服务器管理系统 ===")
            print(f"当前用户: {self.current_user}")
            print("1. 创建深度学习任务")
            print("2. 退出")
            
            if self.current_user and self.user_manager.is_admin(self.current_user):
                print("3. 用户管理")

            choice = input("请选择操作: ")

            if choice == '1':
                self.create_dl_task()
            elif choice == '2':
                print("感谢使用，再见！")
                break
            elif choice == '3' and self.current_user and self.user_manager.is_admin(self.current_user):
                self.user_manager.manage_users()
            else:
                print("无效的选择，请重试")

if __name__ == "__main__":
    server = LabServer()
    server.show_menu() 