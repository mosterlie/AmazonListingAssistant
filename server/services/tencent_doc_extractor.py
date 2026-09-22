"""
腾讯文档在线表格无头直读提取器 (TencentDocExtractor)

采集方式: headless Chromium 打开文档页 → 等待内核初始化 → 页内直读 SpreadsheetApp
内核结构 (2026-09 探明, 见 定时任务.md):
  - SpreadsheetApp.workbook.worksheetManager.sheetList  → sheet 对象数组
  - sheet 原型方法(稳定): getSheetName()/getSheetId()/getIsInitialized()/getCellDataAtPosition(r,c)
  - sheet.cellDataGrid.usedRange = {startRowIndex, startColIndex, endRowIndex, endColIndex}
    (空 sheet 哨兵值 2147483647 / -1)
  - 单元格对象: {value, style, formattedValue, extendedValue?}, 取 value (空则 formattedValue)
  - 未激活 sheet initialized=false 数据未加载 → 逐 sheet 以 ?tab=<sheetId> 重载后提取
仅支持公开分享的 docs.qq.com/sheet/ 链接 (匿名可访问, 无需登录)。
"""
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urlencode

from playwright.sync_api import sync_playwright

_READY_JS = """
() => {
  try {
    const app = window.SpreadsheetApp;
    if (!app || !app.workbook) return false;
    const wm = app.workbook.worksheetManager;
    if (!wm) return false;
    const sheets = wm.sheetList || [];
    return sheets.some(s => { try { return s.getIsInitialized && s.getIsInitialized(); } catch (e) { return false; } });
  } catch (e) { return false; }
}
"""

# 单次 evaluate 内拉取当前已初始化的 sheet 数据 (避免逐单元格跨桥调用)
_EXTRACT_JS = """
() => {
  const wm = SpreadsheetApp.workbook.worksheetManager;
  const sheets = wm.sheetList || [];
  const EMPTY_R = 2147483647, EMPTY_C = 2147483647;
  const out = [];
  for (const s of sheets) {
    let initialized = false, name = null, sid = null;
    try { initialized = !!(s.getIsInitialized && s.getIsInitialized()); } catch (e) {}
    try { name = s.getSheetName(); } catch (e) {}
    try { sid = s.getSheetId(); } catch (e) {}
    const item = {sheet_id: sid, sheet_name: name, initialized};
    if (!initialized) { out.push(item); continue; }
    const g = s.cellDataGrid;
    const ur = g && g.usedRange;
    if (!ur) { item.rows = []; item.nrows = 0; item.ncols = 0; out.push(item); continue; }
    let r0 = ur.startRowIndex, c0 = ur.startColIndex, r1 = ur.endRowIndex, c1 = ur.endColIndex;
    if (r0 >= EMPTY_R || c0 >= EMPTY_C || r1 < 0 || c1 < 0 || r1 < r0 || c1 < c0) {
      item.rows = []; item.nrows = 0; item.ncols = 0; out.push(item); continue;
    }
    if (r1 - r0 + 1 > 5000) r1 = r0 + 4999;   // 安全上限
    if (c1 - c0 + 1 > 100) c1 = c0 + 99;
    const rows = [];
    for (let r = r0; r <= r1; r++) {
      const row = [];
      for (let c = c0; c <= c1; c++) {
        let cell = null;
        try { cell = s.getCellDataAtPosition(r, c); } catch (e) { cell = null; }
        if (cell == null || typeof cell !== 'object') { row.push(cell == null ? null : cell); continue; }
        let v = cell.value;
        if (v != null && typeof v === 'object' && Array.isArray(v.r)) {
          // 富文本单元格: {r: [{t: 文本段, rPr...}]} → 拍平拼接
          v = v.r.map(seg => (seg && seg.t != null) ? seg.t : '').join('');
        }
        if (v == null || v === '') v = cell.formattedValue;
        row.push(v == null ? null : v);
      }
      rows.push(row);
    }
    item.rows = rows;
    item.nrows = rows.length;
    item.ncols = rows.length ? rows[0].length : 0;
    out.push(item);
  }
  return {title: document.title || '', sheets: out};
}
"""


def parse_doc_url(url: str) -> Dict[str, Optional[str]]:
    """解析腾讯文档链接 → {doc_id, tab}; 非 docs.qq.com/sheet/ 链接抛 ValueError"""
    url = (url or "").strip()
    m = re.match(r"^https?://docs\.qq\.com/sheet/([A-Za-z0-9]+)", url)
    if not m:
        raise ValueError(f"仅支持腾讯文档在线表格链接 (docs.qq.com/sheet/...): {url[:80]}")
    doc_id = m.group(1)
    tab = None
    try:
        qs = parse_qs(urlparse(url).query)
        tab = (qs.get("tab") or [None])[0]
    except Exception:
        pass
    return {"doc_id": doc_id, "tab": tab}


def _page_url(doc_id: str, tab: Optional[str] = None) -> str:
    base = f"https://docs.qq.com/sheet/{doc_id}"
    return f"{base}?{urlencode({'tab': tab})}" if tab else base


class TencentDocExtractor:
    """按批次复用一个 headless 浏览器实例逐文档提取; with 语句结束即销毁"""

    def __init__(self, page_timeout_ms: int = 60000, goto_retries: int = 3, settle_ms: int = 4000):
        self.page_timeout_ms = page_timeout_ms
        self.goto_retries = goto_retries
        self.settle_ms = settle_ms
        self._pw = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "TencentDocExtractor":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._page = self._browser.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def _goto(self, url: str) -> None:
        last_err: Optional[Exception] = None
        for i in range(self.goto_retries):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=self.page_timeout_ms)
                return
            except Exception as e:  # goto 偶发网络超时, 重试
                last_err = e
                time.sleep(2 * (i + 1))
        raise RuntimeError(f"打开文档失败 (重试{self.goto_retries}次): {url[:80]} — {last_err}")

    def _wait_ready(self) -> None:
        try:
            self._page.wait_for_function(_READY_JS, timeout=self.page_timeout_ms)
        except Exception:
            # 偶发慢加载: wait_for_function 超时后再手工轮询 30s
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    if self._page.evaluate(_READY_JS):
                        break
                except Exception:
                    pass
                time.sleep(1)
            else:
                title = ""
                try:
                    title = self._page.title()
                except Exception:
                    pass
                raise RuntimeError(f"文档内核初始化超时 (title={title[:50]})")
        self._page.wait_for_timeout(self.settle_ms)  # 等数据块落载

    def extract_doc(self, url: str) -> Dict[str, Any]:
        """提取一个文档: 返回 {title, doc_id, sheets: [{sheet_id, sheet_name, initialized, rows}]}
        未初始化的 sheet 会逐个以 ?tab=<sheetId> 重载页面后补齐数据。"""
        parsed = parse_doc_url(url)
        doc_id, tab = parsed["doc_id"], parsed["tab"]
        last_err: Optional[Exception] = None
        for _attempt in range(2):  # 整页加载+就绪等待整体重试一次
            try:
                self._goto(_page_url(doc_id, tab))
                self._wait_ready()
                last_err = None
                break
            except Exception as e:
                last_err = e
        if last_err is not None:
            raise last_err

        data = self._page.evaluate(_EXTRACT_JS)
        sheets: List[Dict[str, Any]] = data.get("sheets", [])

        # 未加载的 sheet: 逐个 ?tab= 重载提取
        pending = [s for s in sheets if not s.get("initialized") and s.get("sheet_id")]
        for s in pending:
            self._goto(_page_url(doc_id, s["sheet_id"]))
            self._wait_ready()
            sub = self._page.evaluate(_EXTRACT_JS)
            for sub_sheet in sub.get("sheets", []):
                if sub_sheet.get("sheet_id") == s["sheet_id"] and sub_sheet.get("initialized"):
                    s.update(sub_sheet)
                    break

        for s in sheets:
            s.pop("initialized", None)
        return {"title": data.get("title", ""), "doc_id": doc_id, "sheets": sheets}
