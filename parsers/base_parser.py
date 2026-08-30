"""
页面解析抽象基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from playwright.sync_api import Page


class BasePageParser(ABC):
    """页面解析器抽象基类"""

    def __init__(self, page: Page):
        self.page = page

    @abstractmethod
    def is_match(self) -> bool:
        """检查当前页面是否匹配目标网站/页面类型"""
        pass

    @abstractmethod
    def extract(self) -> Dict[str, Any]:
        """执行页面数据解析并返回结构化字典"""
        pass

    def wait_until_ready(self, selector: str, timeout: float = 10.0) -> bool:
        """等待关键 DOM 节点加载完成"""
        try:
            self.page.wait_for_selector(selector, timeout=int(timeout * 1000), state="visible")
            return True
        except Exception:
            return False

    def evaluate_js(self, script: str, arg: Any = None) -> Any:
        """在页面上下文中安全执行 JavaScript 脚本"""
        return self.page.evaluate(script, arg)
