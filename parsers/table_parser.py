"""
表格、数据网格与 SKU 矩阵结构化解析引擎
"""
from typing import Dict, Any, List, Optional
from playwright.sync_api import Page

try:
    from .base_parser import BasePageParser
except (ImportError, ValueError):
    from base_parser import BasePageParser


class TableParser(BasePageParser):
    """
    专门负责解析页面中的标准 HTML 表格 (<table>) 与现代化前端组件网格 (DataGrid / Virtual Table)
    """

    def is_match(self) -> bool:
        return True

    def extract(self) -> List[Dict[str, Any]]:
        """扫描当前页面中所有数据表格并提取结构化行数据"""
        return self.scan_tables()

    def scan_tables(self) -> List[Dict[str, Any]]:
        js_code = """
        () => {
            const tablesResult = [];

            // 1. 扫描标准 <table> 元素
            const tables = document.querySelectorAll('table, .el-table, .ant-table, [class*="virtual-table"], [class*="grid"]');
            tables.forEach((tbl, tblIdx) => {
                // 查找表头
                let headers = [];
                const thElements = tbl.querySelectorAll('th, .el-table__header th, .ant-table-thead th, .grid-header-cell');
                if (thElements.length > 0) {
                    headers = Array.from(thElements).map(th => th.innerText.trim()).filter(h => h);
                }

                // 查找数据行
                const rows = [];
                const trElements = tbl.querySelectorAll('tbody tr, .el-table__row, .ant-table-row, .grid-row, .virtual-row');
                trElements.forEach((tr, rIdx) => {
                    const cells = tr.querySelectorAll('td, .cell, .ant-table-cell, .grid-cell');
                    if (cells.length === 0) return;

                    const rowObj = {};
                    const cellList = [];

                    cells.forEach((td, cIdx) => {
                        const input = td.querySelector('input, select, textarea');
                        let val = '';
                        let isEditable = false;

                        if (input) {
                            val = input.value || '';
                            isEditable = true;
                        } else {
                            val = td.innerText.trim();
                        }

                        const colName = headers[cIdx] || `列_${cIdx + 1}`;
                        rowObj[colName] = val;
                        cellList.push({
                            col_index: cIdx + 1,
                            col_name: colName,
                            text: val,
                            is_editable: isEditable
                        });
                    });

                    rows.push({
                        row_index: rIdx + 1,
                        data_map: rowObj,
                        cells: cellList
                    });
                });

                if (headers.length > 0 || rows.length > 0) {
                    tablesResult.push({
                        table_index: tblIdx + 1,
                        headers: headers,
                        total_rows: rows.length,
                        rows: rows
                    });
                }
            });

            return tablesResult;
        }
        """
        return self.page.evaluate(js_code)
