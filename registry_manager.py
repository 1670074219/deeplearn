import requests
import json

class RegistryManager:
    def __init__(self, config):
        self.config = config
        self.registry_url = f"http://{config['registry_server']['host']}:{config['registry_server']['registry_port']}"

    def get_catalog(self):
        """获取仓库中的所有镜像列表"""
        try:
            response = requests.get(f"{self.registry_url}/v2/_catalog")
            if response.status_code == 200:
                return response.json().get('repositories', [])
            return []
        except Exception as e:
            print(f"获取镜像列表失败：{str(e)}")
            return []

    def get_tags(self, repository):
        """获取指定镜像的所有标签"""
        try:
            response = requests.get(f"{self.registry_url}/v2/{repository}/tags/list")
            if response.status_code == 200:
                return response.json().get('tags', [])
            return []
        except Exception as e:
            print(f"获取标签列表失败：{str(e)}")
            return []

    def get_manifest(self, repository, tag):
        """获取镜像的详细信息"""
        try:
            headers = {'Accept': 'application/vnd.docker.distribution.manifest.v2+json'}
            response = requests.get(
                f"{self.registry_url}/v2/{repository}/manifests/{tag}",
                headers=headers
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"获取镜像信息失败：{str(e)}")
            return None

    def get_image_size(self, repository, tag):
        """获取镜像大小"""
        manifest = self.get_manifest(repository, tag)
        if manifest:
            try:
                config = manifest.get('config', {})
                size = config.get('size', 0)
                return f"{size/(1024*1024):.2f}MB"
            except:
                pass
        return "大小未知"

    def test_connection(self):
        """测试仓库连接"""
        try:
            response = requests.get(f"{self.registry_url}/v2/")
            return response.status_code == 200
        except:
            return False

    def list_images(self):
        """列出所有镜像及其标签"""
        images = []
        repositories = self.get_catalog()
        
        for repo in repositories:
            tags = self.get_tags(repo)
            for tag in tags:
                size = self.get_image_size(repo, tag)
                images.append({
                    'name': f"{repo}:{tag}",
                    'size': size,
                    'source': '仓库镜像'
                })
        
        return images 