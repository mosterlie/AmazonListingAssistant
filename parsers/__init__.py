"""
Browser Toolkit - Parsers Package
"""
from .base_parser import BasePageParser
from .dom_precision_parser import DOMPrecisionParser
from .table_parser import TableParser
from .data_sniffer import DataSniffer

__all__ = ["BasePageParser", "DOMPrecisionParser", "TableParser", "DataSniffer"]
