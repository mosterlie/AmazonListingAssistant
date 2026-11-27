"""佐川急便 轨迹查询 (SagawaService)

数据来源: 佐川官网お荷物問い合わせ (k2k.sagawa-exp.co.jp)
  - 页面是 JSF, 查询靠 POST 自身表单; 站点对非浏览器 TLS 指纹会跳 congestionguide/sys_sorry,
    因此这里用 headless Chromium 提交, 再解析结果表 (不依赖手工操作)。
  - 返回按时间倒序的 details, 字段与初岛轨迹对齐:
        {track_occur_date: "2026-11-27 10:29", track_description: "配達完了", track_location: "三島営業所"}
    这样可以直接和 Chudao 的 details 合并排序。

仅供「未送达且未人工标记送达」的订单补轨迹用; 单号命中规则见 looks_like_sagawa()。
"""
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

URL = "https://k2k.sagawa-exp.co.jp/p/sagawa/web/okurijoinput.jsp"
CACHE_TTL = 600            # 同一单号 10 分钟内不重复起浏览器

_CACHE: Dict[str, Dict[str, Any]] = {}

# 佐川状态 → 中文
STATUS_ZH = {
    "集荷": "已揽收",
    "保管中": "保管中",
    "配達中": "派送中",
    "配達完了": "已送达",
    "不在": "不在宅",
    "持ち戻り": "退回中",
    "ご依頼受付": "已受理",
    "配達先変更": "改址",
    "中止": "已取消",
}

_PARSE_JS = r"""
() => {
  const out = { status: "", message: "", ship_date: "", rows: [] };
  const dl = document.querySelector('dl.toggle');
  if (!dl) {
    out.message = (document.body.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160);
    return out;
  }
  const st = dl.querySelector("span.state");
  if (st) out.status = st.innerText.trim();
  const msg = dl.querySelector("td[colspan]");
  if (msg) out.message = msg.innerText.replace(/\s+/g, " ").trim().slice(0, 200);
  dl.querySelectorAll("table tr").forEach(tr => {
    const cells = Array.from(tr.querySelectorAll("td,th"))
      .map(c => (c.innerText || "").replace(/\s+/g, " ").trim());
    if (!cells.length) return;
    if (cells[0] === "出荷日" && cells[1]) out.ship_date = cells[1];
    // 履歴行: [↓集荷, 11/24 21:36, りんくう営業所]
    if (cells.length >= 3 && /^\d{1,2}\/\d{1,2}\s+\d{1,2}:\d{2}$/.test(cells[1] || "")) {
      out.rows.push([cells[0], cells[1], cells[2]]);
    }
  });
  return out;
}
"""


def looks_like_sagawa(tracking_no: str, company: str = "", dest_country: str = "") -> bool:
    """是否是佐川单号: 承运商命中佐川, 或 (无承运商时) JP + 12 位纯数字"""
    no = (tracking_no or "").strip()
    if not no:
        return False
    if re.search(r"佐川|sagawa", company or "", re.I):
        return True
    if re.fullmatch(r"\d{12}", no) and (dest_country or "").upper() in ("", "JP", "JPN", "JAPAN"):
        return True
    return False


def _parse_year(ship_date: str, month: int, today: Optional[datetime] = None) -> int:
    """从「出荷日 2026年11月24日」推年份; 跨年时 11/24 → 11/27 仍同年, 12/30 → 1/2 进下一年"""
    now = today or datetime.now()
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", ship_date or "")
    if m:
        year, ship_month = int(m.group(1)), int(m.group(2))
        return year + 1 if month < ship_month - 6 else year
    # 没有出荷日: 以当前年份为准, 月份大于当前月 6 个月视为去年
    return now.year - 1 if month > now.month + 6 else now.year


def _norm_details(parsed: Dict[str, Any]) -> List[Dict[str, str]]:
    """页面行 → 与初岛一致的 details (时间倒序)"""
    out: List[Dict[str, str]] = []
    for label, when, office in parsed.get("rows") or []:
        desc = re.sub(r"^[↓⇒↑→\s]+", "", label or "").strip()
        m = re.match(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", when or "")
        if not m or not desc:
            continue
        month, day, hh, mm = (int(x) for x in m.groups())
        year = _parse_year(parsed.get("ship_date", ""), month)
        out.append({
            "track_occur_date": f"{year:04d}-{month:02d}-{day:02d} {hh:02d}:{mm:02d}:00",
            "track_description": desc,
            "track_location": (office or "").strip(),
            "track_source": "sagawa",
        })
    out.sort(key=lambda x: x["track_occur_date"], reverse=True)
    return out


def _empty(number: str) -> Dict[str, Any]:
    return {"number": number, "found": False, "status": "", "status_zh": "",
            "details": [], "message": "", "error": ""}


def _build_result(number: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
    out = _empty(number)
    status = (parsed.get("status") or "").strip()
    details = _norm_details(parsed)
    out["status"] = status
    out["status_zh"] = STATUS_ZH.get(status, "")
    out["details"] = details
    out["message"] = parsed.get("message") or ""
    out["found"] = bool(details) and status not in ("", "該当なし")
    return out


def _query_page(page, number: str) -> Dict[str, Any]:
    """在已打开的 page 上提交一次查询"""
    page.goto(URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector('input[id="main:no1"]', timeout=20000)
    page.fill('input[id="main:no1"]', number)
    page.click('input[id="main:toiStart"]')
    page.wait_for_load_state("load", timeout=30000)
    page.wait_for_timeout(400)
    return page.evaluate(_PARSE_JS)


def track_many(numbers: List[str], use_cache: bool = True,
               on_progress=None) -> Dict[str, Dict[str, Any]]:
    """批量查询 (一个浏览器实例跑完所有未缓存单号); 返回 {单号: 结果}"""
    want = list(dict.fromkeys([str(n or "").strip() for n in numbers or [] if str(n or "").strip()]))
    out: Dict[str, Dict[str, Any]] = {}
    todo: List[str] = []
    now = time.time()
    for no in want:
        cached = _CACHE.get(no)
        if use_cache and cached and now - cached["at"] < CACHE_TTL:
            out[no] = dict(cached["data"])
        else:
            todo.append(no)
    if not todo:
        return out

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:               # 没装 playwright 时不影响主流程
        for no in todo:
            out[no] = _empty(no)
            out[no]["error"] = f"Playwright 不可用: {exc}"
        return out

    # Playwright 驱动是 Node 进程, 宿主注入的 NODE_OPTIONS 失效会导致驱动起不来
    saved = os.environ.pop("NODE_OPTIONS", None)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                for no in todo:
                    try:
                        result = _build_result(no, _query_page(page, no))
                    except Exception as exc:
                        result = _empty(no)
                        result["error"] = f"{exc.__class__.__name__}: {exc}"
                    out[no] = result
                    _CACHE[no] = {"at": time.time(), "data": dict(result)}
                    if on_progress:
                        try:
                            on_progress(no, result)
                        except Exception:
                            pass
            finally:
                browser.close()
    except Exception as exc:
        for no in todo:
            if no not in out:
                out[no] = _empty(no)
                out[no]["error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        if saved is not None:
            os.environ["NODE_OPTIONS"] = saved
    return out


def track(number: str, use_cache: bool = True) -> Dict[str, Any]:
    """查询佐川轨迹; 失败不抛异常, 返回 {found: False, error: ...}"""
    no = (number or "").strip()
    if not no:
        out = _empty("")
        out["error"] = "空单号"
        return out
    return track_many([no], use_cache=use_cache).get(no) or _empty(no)


def clear_cache() -> None:
    _CACHE.clear()
