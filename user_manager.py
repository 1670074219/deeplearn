import yaml
import getpass
import paramiko

class UserManager:
    def __init__(self, config):
        self.config = config

    def verify_user(self, username, password):
        try:
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
        return (username in self.config['users'] and 
                self.config['users'][username]['role'] == 'admin')

    def add_user(self, username, password, role='user'):
        if not self.config['users'].get(username):
            # 创建用户目录路径（仅用于显示）
            user_dir = f"{self.config['registry_server']['nfs_path']}/{username}"
            
            self.config['users'][username] = {
                'username': username,
                'password': password,
                'role': role,
                'data_dir': user_dir
            }
            
            self._save_config()
            print(f"用户 {username} 添加成功")
            print(f"FTP目录：{user_dir}")
        else:
            print("用户已存在")

    def delete_user(self, username):
        if username in self.config['users']:
            del self.config['users'][username]
            self._save_config()
            print(f"用户 {username} 删除成功")
        else:
            print("用户不存在")

    def _save_config(self):
        with open('config.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, allow_unicode=True)

    def manage_users(self):
        while True:
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
                print("\n当前用户列表：")
                for username, user_info in self.config['users'].items():
                    print(f"用户名: {username}, 角色: {user_info['role']}")
            elif choice == '4':
                break 