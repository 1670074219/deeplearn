class GroupManager:
    def __init__(self, config):
        self.config = config
        self.config_manager = None  # 将在set_config_manager中设置

    def set_config_manager(self, config_manager):
        """设置配置管理器实例"""
        self.config_manager = config_manager

    def create_group(self, group_name, description, allowed_servers, max_containers, max_gpus, time_limit):
        """创建新的用户组"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
            
        if group_name in self.config['user_groups']:
            print(f"用户组 {group_name} 已存在")
            return False

        self.config['user_groups'][group_name] = {
            'name': group_name,
            'description': description,
            'allowed_servers': allowed_servers,
            'max_containers': max_containers,
            'max_gpus': max_gpus,
            'time_limit': time_limit
        }
        
        # 保存配置
        if self.config_manager:
            return self.config_manager.save_config(self.config)
        return True

    def delete_group(self, group_name):
        """删除用户组"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
            
        if group_name not in self.config['user_groups']:
            print(f"用户组 {group_name} 不存在")
            return False

        # 检查是否有用户在使用该组
        for username, user_info in self.config['users'].items():
            if user_info.get('group') == group_name:
                print(f"无法删除：用户组 {group_name} 正在被用户 {username} 使用")
                return False

        del self.config['user_groups'][group_name]
        
        # 保存配置
        if self.config_manager:
            return self.config_manager.save_config(self.config)
        return True

    def modify_group(self, group_name, description=None, allowed_servers=None, 
                    max_containers=None, max_gpus=None, time_limit=None):
        """修改用户组设置"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
            
        if group_name not in self.config['user_groups']:
            print(f"用户组 {group_name} 不存在")
            return False

        group = self.config['user_groups'][group_name]
        if description is not None:
            group['description'] = description
        if allowed_servers is not None:
            group['allowed_servers'] = allowed_servers
        if max_containers is not None:
            group['max_containers'] = max_containers
        if max_gpus is not None:
            group['max_gpus'] = max_gpus
        if time_limit is not None:
            group['time_limit'] = time_limit
            
        # 保存配置
        if self.config_manager:
            return self.config_manager.save_config(self.config)
        return True

    def get_group_info(self, group_name):
        """获取用户组信息"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
        return self.config['user_groups'].get(group_name)

    def list_groups(self):
        """列出所有用户组"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
        return self.config['user_groups']

    def get_user_group(self, username):
        """获取用户所属的组"""
        # 重新加载配置以获取最新状态
        if self.config_manager:
            self.config = self.config_manager.load_config()
            
        user = self.config['users'].get(username)
        if user and 'group' in user:
            return self.get_group_info(user['group'])
        return self.get_group_info('default')

    def check_server_access(self, username, server_name):
        """检查用户是否有权限访问服务器"""
        group = self.get_user_group(username)
        return server_name in group['allowed_servers'] 