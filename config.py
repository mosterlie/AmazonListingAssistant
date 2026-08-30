"""
Browser Toolkit - 全局配置模块
"""
import os
import sys

# 确保本地 CDP 调试通信不走系统代理 (Clash/V2Ray 等)
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
os.environ["no_proxy"] = "127.0.0.1,localhost,::1"

# 默认 CDP 调试端口
DEFAULT_CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{DEFAULT_CDP_PORT}"

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 独立持久化浏览器数据目录（保存登录态与 Cookie，不干扰日常个人浏览器）
if sys.platform == "darwin":
    USER_DATA_DIR = os.path.expanduser("~/Library/Application Support/BrowserToolkit/UserData")
elif sys.platform == "win32":
    USER_DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "BrowserToolkit", "UserData")
else:
    USER_DATA_DIR = os.path.expanduser("~/.config/BrowserToolkit/UserData")

# 跨平台浏览器可执行文件探测路径
CHROME_PATHS_MACOS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

CHROME_PATHS_WINDOWS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]

# 默认操作超时（毫秒）
DEFAULT_TIMEOUT_MS = 15000
