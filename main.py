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
        username = input("请输入用户名: ")
        password = getpass.getpass("请输入密码: ")
        
        if self.user_manager.verify_user(username, password):
            self.current_user = username
            print(f"欢迎, {username}!")
            return True
        print("用户名或密码错误")
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
            print(f"获取Docker镜像列表时出错：{str(e)}")
            return []

    def create_dl_task(self):
        if not self.current_user:
            print("请先登录")
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

        # 连接服务器获取实际的Docker镜像
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

            print("\n获取服务器上的Docker镜像列表...")
            available_images = self.get_server_docker_images(ssh)
            
            if not available_images:
                print("错误：未找到可用的Docker镜像")
                return

            print("\n可用的Docker镜像：")
            for idx, image in enumerate(available_images, 1):
                print(f"{idx}. {image['name']} (大小: {image['size']})")
            
            while True:
                try:
                    choice = input("\n请选择镜像编号: ")
                    idx = int(choice) - 1
                    if 0 <= idx < len(available_images):
                        image_name = available_images[idx]['name']
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

            # 构建Docker运行命令
            docker_cmd = (
                f"docker run -d --gpus '\"device={','.join(str(i) for i in range(gpu_num))}\"' "
                f"-v {work_dir}:/workspace "
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