"""
妙手 ERP 开放平台 API 客户端 (运单管理模块: 运单号数据源)

接口文档: https://s.apifox.cn/fd54e57e-9b98-4c34-bada-306221c39e68 (妙手开放平台)
正式域名: https://openapi-erp.91miaoshou.com

鉴权: 每次请求 Header 携带
    x-app-key    应用Key (ak_xxx)
    x-timestamp  秒级Unix时间戳 (偏差<300s)
    x-sign       HmacSHA256(appSecret, appSecret + path + timestamp + appKey + bodyJson + appSecret) 小写hex
    注: path 只含接口路径不含域名/Query; bodyJson 为 JSON 字符串, 无 body 拼空串

用途: 分页拉取已发货/已完成包裹 → 提取运单号(logisticsNo, 初岛尾程单号)
    → 运单管理·运单查询面板一键同步入库 (waybill_service.sync_from_miaoshou)
"""
import hmac
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import requests

from server.database import get_setting, set_setting

MIAOSHOU_BASE_URL = "https://openapi-erp.91miaoshou.com"

SETTING_APP_ID = "miaoshou_app_id"
SETTING_APP_SECRET = "miaoshou_app_secret"

# 铺底默认凭证 (仅首次初始化写入 system_settings, 之后以库中值为准)
DEFAULT_APP_ID = "ak_fda130b4c811472386644e3e6a3fea73"
DEFAULT_APP_SECRET = "645c5760933c47e997bb01d4155f0b9ac8501179fcfb45bc92e179171630b1ee"

PAGE_SIZE = 100          # 妙手分页大小 (实测要求 >=10)
MAX_PAGES = 50           # 分页保护上限 (50页×100 = 5000 包裹)


class MiaoshouApiError(Exception):
    """妙手 API 调用失败 (result=fail 或网络异常已重试耗尽)"""


class MiaoshouService:
    """妙手开放平台: 签名调用 + 包裹列表拉取"""

    @staticmethod
    def _credentials() -> tuple:
        """读取凭证; 库中缺失时用默认值铺底写入"""
        app_id = get_setting(SETTING_APP_ID) or ""
        app_secret = get_setting(SETTING_APP_SECRET) or ""
        if not app_id or not app_secret:
            app_id = app_id or DEFAULT_APP_ID
            app_secret = app_secret or DEFAULT_APP_SECRET
            try:
                if not get_setting(SETTING_APP_ID):
                    set_setting(SETTING_APP_ID, app_id)
                if not get_setting(SETTING_APP_SECRET):
                    set_setting(SETTING_APP_SECRET, app_secret)
            except Exception:
                pass
        return app_id, app_secret

    @staticmethod
    def call(path: str, body: Optional[dict] = None,
             max_retries: int = 3, timeout: int = 30) -> Dict[str, Any]:
        """签名调用妙手开放平台 (POST JSON + 3次重试间隔2s)"""
        app_key, app_secret = MiaoshouService._credentials()
        body_json = json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body else ""
        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                ts = str(int(time.time()))
                content = app_secret + path + ts + app_key + body_json + app_secret
                sign = hmac.new(app_secret.encode(), content.encode(), hashlib.sha256).hexdigest()
                headers = {
                    "x-app-key": app_key,
                    "x-timestamp": ts,
                    "x-sign": sign,
                    "Content-Type": "application/json",
                }
                resp = requests.post(MIAOSHOU_BASE_URL + path,
                                     data=body_json.encode() if body_json else None,
                                     headers=headers, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise MiaoshouApiError(f"响应非对象: {type(data).__name__}")
                if data.get("result") != "success":
                    msg = str(data.get("message") or data.get("code") or "")
                    # 限频/流控属瞬时错误: 退避后重试 (实测"账户接口每秒请求频率超限")
                    if ("频率" in msg or "频繁" in msg or "流控" in msg or "限流" in msg) and attempt < max_retries:
                        last_err = MiaoshouApiError(f"限频: {msg}")
                        time.sleep(2 * attempt)
                        continue
                    raise MiaoshouApiError(f"业务失败: {msg}")
                return data
            except requests.RequestException as exc:
                last_err = exc
                if attempt < max_retries:
                    time.sleep(2)
        raise MiaoshouApiError(f"调用 {path} 失败(已重试{max_retries}次): {last_err}")

    @staticmethod
    def _normalize_package(p: dict) -> Optional[Dict[str, Any]]:
        """妙手包裹 → 运单库字段摘要; 无跟踪号的包裹返回 None"""
        logi = p.get("logisticsAgentProductInfo") or {}
        tracking_no = (p.get("logisticsNo") or logi.get("logisticsNo") or "").strip()
        if not tracking_no:
            return None
        order = p.get("orderInfo") or {}
        consignee = p.get("consigneeInfo") or {}
        channel = (logi.get("productName") or "").strip()
        shop_name = (p.get("shopName") or p.get("shopNick") or "").strip()
        note_parts = [x for x in ["妙手同步", f"渠道:{channel}" if channel else "",
                                  f"店铺:{shop_name}" if shop_name else ""] if x]
        return {
            "tracking_no": tracking_no,
            "platform_package_no": (logi.get("platformPackageNo") or "").strip(),
            "platform_order_sn": (order.get("platformOrderSn") or "").strip(),
            "dest_country": (consignee.get("country") or "").strip(),
            "gmt_delivery": (order.get("gmtDelivery") or "").strip(),
            "status_text": (p.get("appPackageStatusText") or "").strip(),
            "package_id": str(p.get("opOrderPackageId") or ""),
            "note": " ".join(note_parts),
        }

    @staticmethod
    def fetch_shipped_packages(max_packages: int = 1000) -> List[Dict[str, Any]]:
        """分页拉取 已发货(wait_receiver_confirm) + 已完成(finished) 包裹并归一化

        只保留带运单号的包裹 (无运单号的未发货单不进运单库)。
        """
        out: List[Dict[str, Any]] = []
        seen_ids = set()
        for status in ("wait_receiver_confirm", "finished"):
            page = 1
            while page <= MAX_PAGES:
                if len(out) >= max_packages:
                    return out[:max_packages]
                if page > 1 or out:
                    time.sleep(1.1)  # 妙手限频: 每秒1次调用间隔
                try:
                    data = MiaoshouService.call(
                        "/open/v1/order/package/fetch/search_package_list",
                        {"page": page, "pageSize": PAGE_SIZE, "appPackageStatus": status})
                except MiaoshouApiError as exc:
                    if "没有符合条件" in str(exc):
                        break  # 该筛选条件下无数据 → 视为空结果
                    raise
                body = data.get("data") or {}
                packages = body.get("orderPackageList") or []
                if not packages:
                    break
                for p in packages:
                    norm = MiaoshouService._normalize_package(p)
                    if norm and norm["package_id"] not in seen_ids:
                        seen_ids.add(norm["package_id"])
                        out.append(norm)
                        if len(out) >= max_packages:
                            return out
                total = int(body.get("total") or 0)
                if page * PAGE_SIZE >= total:
                    break
                page += 1
        return out
