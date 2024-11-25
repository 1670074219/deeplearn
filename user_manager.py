import getpass

class UserManager:
    def __init__(self, config):
        """
        初始化用户管理器
        Args:
            config: 从主程序传入的配置字典
        """
        self.config = config
        self.config_manager = None  # 将在set_config_manager中设置

    def set_config_manager(self, config_manager):
        """设置配置管理器实例"""
        self.config_manager = config_manager

    def verify_user(self, username, password):
        """验证用户登录"""
        try:
            # 重新加载配置以获取最新状态
            if self.config_manager:
                self.config = self.config_manager.load_config()
                
            users = self.config['users']
            if username not in users:
                print(f"错误：用户 {username} 不存在")
                return False
            
            if users[username]['password'] == password:
                return True
            
            print("错误：密码不正确")
            return False
        except Exception as e:
            print(f"验证用户时出错：{str(e)}")
            return False

    def is_admin(self, username):
        """检查用户是否是管理员"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
            
        return (username in self.config['users'] and 
                self.config['users'][username]['role'] == 'admin')

    def add_user(self, username, password, role='user'):
        """添加新用户"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
            
        if not self.config['users'].get(username):
            # 创建用户目录路径（仅用于显示）
            user_dir = f"{self.config['registry_server']['nfs_path']}/{username}"
            
            self.config['users'][username] = {
                'username': username,
                'password': password,
                'role': role,
                'data_dir': user_dir
            }
            
            # 保存配置
            if self.config_manager:
                if self.config_manager.save_config(self.config):
                    print(f"用户 {username} 添加成功")
                    print(f"FTP目录：{user_dir}")
                else:
                    print("保存配置失败")
        else:
            print("用户已存在")

    def delete_user(self, username):
        """删除用户"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
            
        if username in self.config['users']:
            del self.config['users'][username]
            # 保存配置
            if self.config_manager:
                if self.config_manager.save_config(self.config):
                    print(f"用户 {username} 删除成功")
                else:
                    print("保存配置失败")
        else:
            print("用户不存在")

    def manage_users(self):
        """用户管理界面"""
        while True:
            # 重新加载配置以获取最新状态
            if self.config_manager:
                self.config = self.config_manager.load_config()
                
            print("\n=== 用户管理 ===")
            print("1. 添加用户")
            print("2. 删除用户")
            print("3. 查看所有用户")
            print("4. 返回主菜单")

            choice = input("请选择操作: ")

            if choice == '1':
                username = input("输入新用户名: ")
                password = getpass.getpass("输入密码: ")
                role = input("输入角色 (admin/user): ")
                self.add_user(username, password, role)
            elif choice == '2':
                username = input("输入要删除的用户名: ")
                self.delete_user(username)
            elif choice == '3':
                # 重新加载配置以显示最新用户列表
                if self.config_manager:
                    self.config = self.config_manager.load_config()
                print("\n当前用户列表：")
                for username, user_info in self.config['users'].items():
                    print(f"用户名: {username}, 角色: {user_info['role']}")
            elif choice == '4':
                break