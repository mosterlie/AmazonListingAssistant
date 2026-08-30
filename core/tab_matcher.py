"""
标签页信息模型与智能检索匹配器
"""
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse
from playwright.sync_api import Page


@dataclass
class TabInfo:
    """标签页元数据模型"""
    index: int
    title: str
    url: str
    page: Page
    is_active: bool = False

    def display_text(self) -> str:
        active_mark = " 👁 [当前前台激活]" if self.is_active else ""
        short_title = self.title if len(self.title) <= 35 else self.title[:32] + "..."
        short_url = self.url if len(self.url) <= 45 else self.url[:42] + "..."
        return f"[{self.index}] {short_title} ({short_url}){active_mark}"


class TabMatcher:
    """标签页 URL 与特征匹配器"""

    @staticmethod
    def normalize_url(url: str) -> str:
        """标准化 URL（去除尾部斜杠、默认端口与无效字符）"""
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            if ":" in netloc and (netloc.endswith(":80") or netloc.endswith(":443")):
                netloc = netloc.split(":")[0]
            path = parsed.path.rstrip("/")
            return f"{parsed.scheme}://{netloc}{path}"
        except Exception:
            return url.strip().rstrip("/")

    @classmethod
    def match_by_keyword(cls, page: Page, keywords: List[str]) -> bool:
        """检查页面 URL 或标题是否包含指定关键词列表"""
        try:
            url_lower = page.url.lower()
            title_lower = page.title().lower()
            for kw in keywords:
                k = kw.lower()
                if k in url_lower or k in title_lower:
                    return True
        except Exception:
            pass
        return False
