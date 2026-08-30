"""
Browser Toolkit - Standalone Browser Automation and Precision DOM Parser
"""
from .browser_engine import BrowserEngine
from .parsers.dom_precision_parser import DOMPrecisionParser
from .parsers.table_parser import TableParser
from .parsers.data_sniffer import DataSniffer
from .core.browser_manager import BrowserManager
from .core.tab_matcher import TabInfo, TabMatcher

__all__ = [
    "BrowserEngine",
    "DOMPrecisionParser",
    "TableParser",
    "DataSniffer",
    "BrowserManager",
    "TabInfo",
    "TabMatcher"
]
