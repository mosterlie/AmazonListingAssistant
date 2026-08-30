"""
商品录入与维护服务 - 全局配置模块
"""
import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据存储目录
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "products.db")

# 服务配置
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000

# 默认 DeepSeek 对话会话链接
DEFAULT_DEEPSEEK_URL = "https://chat.deepseek.com/a/chat/s/7d257fd5-a7f7-482f-bec5-ba53f94f6725"

# 确保必要的目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
