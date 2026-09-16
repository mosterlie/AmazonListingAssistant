"""
商品录入与维护服务 - 全局配置模块
"""
import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据存储目录
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
# 数据库文件路径 (可用环境变量 DB_PATH 覆盖)
DB_PATH = os.path.abspath(os.environ.get("DB_PATH", os.path.join(DATA_DIR, "products.db")))

# 服务配置 (默认监听 0.0.0.0 以支持局域网访问，也可通过环境变量重设)
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", 8000))

# 内嵌「图片服务 / DB Agent」访问令牌: 供异地桌面上件助手通过 X-DB-Token 调用
# /ping、/file、/query、/execute (原独立进程 db_agent.py:8765 已合并进本服务)。
# 运行期以系统设置 system_settings.db_agent_token 为准, 此处仅为初始化默认值与兜底。
DB_AGENT_TOKEN = os.environ.get("DB_AGENT_TOKEN", "erp2024").strip()

# 默认 DeepSeek 对话会话链接
DEFAULT_DEEPSEEK_URL = "https://chat.deepseek.com/a/chat/s/7d257fd5-a7f7-482f-bec5-ba53f94f6725"

# 确保必要的目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
