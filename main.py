import yaml
import paramiko
import getpass
from user_manager import UserManager

class LabServer:
    def __init__(self):
        self.config = self.load_config()
        self.user_manager = UserManager(self.config)
        self.current_user = None

    def load_config(self):
        with open('config.yaml', 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def login(self):
        try:
            username = input("请输入用户名: ")
            password = getpass.getpass("请输入密码: ")
            
            # 检查用户是否存在
            if username not in self.config['users']:
                print(f"错误：用户 {username} 不存在")
                return False
            
            # 检查密码是否正确
            user_info = self.config['users'][username]
            if user_info['password'] == password:
                self.current_user = username
                print(f"欢迎, {username}!")
                print(f"用户角色: {user_info['role']}")
                return True
            else:
                print("误：密码不正确")
                return False
            
        except Exception as e:
            print(f"登录过程中出错：{str(e)}")
            return False

    def check_gpu_status(self, server_name):
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
            
            # 获取GPU状态
            stdin, stdout, stderr = ssh.exec_command('nvidia-smi --query-gpu=index,utilization.gpu --format=csv,noheader,nounits')
            output = stdout.read().decode()
            error = stderr.read().decode()
            
            if error:
                print(f"获取GPU状态时出错：{error}")
                return None
            
            gpu_status = []
            for line in output.strip().split('\n'):
                index, utilization = line.split(',')
                gpu_status.append((int(index), int(utilization)))
            
            return gpu_status
            
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

            # 创建用户目录
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
        """保存配置到文件"""
        with open('config.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, allow_unicode=True)

    def create_dl_task(self):
        if not self.current_user:
            print("请先登")
            return

        print("\n可用的服务器：")
        server_gpu_status = {}
        for server_name, server_info in self.config['servers'].items():
            gpu_status = self.check_gpu_status(server_name)
            if gpu_status is not None:
                used_gpus = sum(1 for _, utilization in gpu_status if utilization > 0)
                total_gpus = len(gpu_status)
                server_gpu_status[server_name] = (used_gpus, total_gpus)
                print(f"- {server_name} ({server_info['host']}): {used_gpus}/{total_gpus} GPUs in use")
        
        server_name = input("请选择服务器: ")
        if server_name not in server_gpu_status:
            print("错误：无效的服务器名称")
            return
        
        used_gpus, total_gpus = server_gpu_status[server_name]
        available_gpus = total_gpus - used_gpus
        print(f"\n服务器 {server_name} 有 {available_gpus} 个未使用的GPU")

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

            print("\n获取本地Docker镜像列表...")
            local_images = self.get_server_docker_images(ssh)
            
            print("\n本地可用的Docker镜像：")
            for idx, image in enumerate(local_images, 1):
                print(f"{idx}. {image['name']} [本地] ({image['size']})")
            
            while True:
                choice = input("\n是否使用本地镜像？(y/n): ").lower().strip()
                if choice in ['y', 'n']:
                    break
                print("请输入 'y' 或 'n'")

            if choice == 'y':
                while True:
                    try:
                        choice = input("\n请选择本地镜像编号: ")
                        idx = int(choice) - 1
                        if 0 <= idx < len(local_images):
                            selected_image = local_images[idx]
                            image_name = selected_image['name']
                            break
                        else:
                            print("无效的选择，请重试")
                    except ValueError:
                        print("请输入有效的数字")
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
                    try:
                        choice = input("\n请选择镜像编号: ")
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
                            break
                        else:
                            print("无效的选择，请重试")
                    except ValueError:
                        print("请输入有效的数字")

            # 获取用户的工作目录
            work_dir = input("请输入工作目录路径（回车使用默认 /home/workspace）: ").strip()
            if not work_dir:
                work_dir = "/home/workspace"

            # 获取要使用的GPU数量
            while True:
                gpu_num = input(f"请输入要使用的GPU数量（最多 {available_gpus} 个，回车使用默认值1）: ").strip()
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

            # 创建工作目录
            stdin, stdout, stderr = ssh.exec_command(f'mkdir -p {work_dir}')
            if stderr.read():
                print(f"创建工作目录失败：{stderr.read().decode()}")
                return

            # 处理镜像名称，将 / 替换为 _ 
            safe_image_name = image_name.replace('/', '_').replace(':', '_')
            container_name = f"{self.current_user}_task_{safe_image_name}"

            # 检查是否有同名容器
            stdin, stdout, stderr = ssh.exec_command(f'docker ps -a --filter "name={container_name}" --format "{{{{.ID}}}}"')
            existing_container_id = stdout.read().decode().strip()
            if existing_container_id:
                print(f"发现同名容器 {container_name}，正在删除...")
                ssh.exec_command(f'docker rm -f {existing_container_id}')

            # 获取用户输入的端口映射
            host_port = input("请输入主机端口（回车使用默认8080）: ").strip()
            container_port = input("请输入容器端口（回车使用默认8080）: ").strip()

            if not host_port:
                host_port = "8080"
            if not container_port:
                container_port = "8080"

            # 检查用户是否已有数据目录，如果没有则创建
            if not self.config['users'][self.current_user].get('data_dir'):
                user_data_dir = self.create_user_data_dir(ssh, self.current_user)
                if not user_data_dir:
                    print("创建用户数据目录失败，操作终止")
                    return
            else:
                user_data_dir = self.config['users'][self.current_user]['data_dir']

            # 构建Docker运行命令，直接使用本地挂载点
            docker_cmd = (
                f"docker run -d --gpus '\"device={','.join(str(i) for i in range(gpu_num))}\"' "
                f"-v {work_dir}:/workspace "
                f"-v {user_data_dir}:/data "  # 直接使用本地挂载点
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

        except Exception as e:
            print(f"创建任务失败：{str(e)}")
        finally:
            ssh.close()

    def show_menu(self):
        while True:
            print("\n=== 实验室服务器管理系统 ===")
            print("1. 登录")
            print("2. 创建深度学习任务")
            print("3. 退出")
            
            if self.current_user and self.user_manager.is_admin(self.current_user):
                print("4. 用户管理")

            choice = input("请选择操作: ")

            if choice == '1':
                self.login()
            elif choice == '2':
                self.create_dl_task()
            elif choice == '3':
                break
            elif choice == '4' and self.current_user and self.user_manager.is_admin(self.current_user):
                self.user_manager.manage_users()

if __name__ == "__main__":
    server = LabServer()
    server.show_menu() 