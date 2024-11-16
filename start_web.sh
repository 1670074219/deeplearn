#!/bin/bash

# 定义颜色代码
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 定义Python路径
PYTHON_PATH="/opt/miniconda/bin/python3"

# 显示标题
echo -e "${GREEN}=== 实验室服务器管理系统 - Web版 ===${NC}"

# 检查Python3是否安装
if [ ! -f "$PYTHON_PATH" ]; then
    echo -e "${RED}错误: 未找到 Python3，路径：$PYTHON_PATH${NC}"
    exit 1
fi

# 检查配置文件
if [ ! -f "config.yaml" ]; then
    echo -e "${RED}错误: 未找到配置文件 config.yaml${NC}"
    exit 1
fi

# 检查模板目录
if [ ! -d "templates" ]; then
    echo -e "${RED}错误: 未找到模板目录 templates${NC}"
    exit 1
fi

# 创建日志目录
if [ ! -d "log_backup" ]; then
    mkdir log_backup
fi

# 设置执行权限
chmod +x app.py

# 启动Web服务器
echo -e "${GREEN}正在启动Web服务器...${NC}"
echo -e "${GREEN}请访问 http://localhost:5000${NC}"
$PYTHON_PATH app.py 