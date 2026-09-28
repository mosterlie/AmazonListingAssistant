"""
初道国际物流 API 客户端 (运单管理模块)

接口文档: http://cdgj.rtb56.com/usercenter/manager/api_document.aspx
统一入口: POST http://cdgj.rtb56.com/webservice/PublicService.asmx/ServiceInterfaceUTF8
Content-Type: application/x-www-form-urlencoded
表单参数: appToken / appKey / serviceMethod / paramsJson(业务JSON)

凭证存储: system_settings 键 chudao_app_token / chudao_app_key (JSON值)。
首次调用时若库中缺失, 用下方铺底默认凭证写入 (与 chudao_api_demo.py 同源, 可随时改库覆盖)。

已知限制: 初道 API 不提供「订单列表」接口 (实测 20+ 候选方法名均返回"接口方法不支持"),
只能按单号查询 → 本模块配套 waybill_service.py 本地运单库。
"""
import json
import time
from typing import Any, Dict, List, Optional

import requests

from server.database import get_setting, set_setting

CHUDAO_BASE_URL = "http://cdgj.rtb56.com/webservice/PublicService.asmx/ServiceInterfaceUTF8"

SETTING_TOKEN_KEY = "chudao_app_token"
SETTING_KEY_NAME = "chudao_app_key"

# 铺底默认凭证 (仅首次初始化写入 system_settings, 之后以库中值为准)
DEFAULT_APP_TOKEN = "031c0ffe5d1904765799d734fafd68bc"
DEFAULT_APP_KEY = "e494096ccfa9b6ef52a85259de60e5b9e494096ccfa9b6ef52a85259de60e5b9"


class ChudaoApiError(Exception):
    """初道 API 业务失败 (success=0) 或调用异常 (已重试耗尽)"""


class ChudaoService:
    """初道 API 通用调用 + 只读查询接口封装"""

    @staticmethod
    def _credentials() -> tuple:
        """读取凭证; 库中缺失时用默认值铺底写入 (运行时自动完成一次)"""
        token = get_setting(SETTING_TOKEN_KEY) or ""
        key = get_setting(SETTING_KEY_NAME) or ""
        if not token or not key:
            token = token or DEFAULT_APP_TOKEN
            key = key or DEFAULT_APP_KEY
            try:
                if not get_setting(SETTING_TOKEN_KEY):
                    set_setting(SETTING_TOKEN_KEY, token)
                if not get_setting(SETTING_KEY_NAME):
                    set_setting(SETTING_KEY_NAME, key)
            except Exception:
                pass  # 铺底失败不阻塞调用, 退回内存值
        return token, key

    @staticmethod
    def call(service_method: str, params: Optional[dict] = None,
             max_retries: int = 3, timeout: int = 30) -> Dict[str, Any]:
        """通用调用: 表单提交 + 3次重试(间隔2s) + 响应多层解析

        返回原始响应 dict (含 success / cnmessage / data 等字段)。
        网络失败重试耗尽 / 响应无法解析 → 抛 ChudaoApiError。
        """
        token, key = ChudaoService._credentials()
        payload = {
            "appToken": token,
            "appKey": key,
            "serviceMethod": service_method,
            "paramsJson": json.dumps(params or {}, ensure_ascii=False),
        }
        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(CHUDAO_BASE_URL, data=payload, timeout=timeout)
                resp.raise_for_status()
                text = resp.text.strip()
                try:
                    data = json.loads(text)
                    # asmx 可能用 {"d": "<json字符串>"} 包裹
                    if isinstance(data, dict) and isinstance(data.get("d"), str):
                        data = json.loads(data["d"])
                    if not isinstance(data, dict):
                        raise ValueError(f"响应非对象: {type(data).__name__}")
                    return data
                except (ValueError, TypeError) as parse_err:
                    raise ChudaoApiError(f"响应解析失败: {parse_err}; 原文前200字: {text[:200]}")
            except requests.RequestException as exc:
                last_err = exc
                if attempt < max_retries:
                    time.sleep(2)
        raise ChudaoApiError(f"调用 {service_method} 失败(已重试{max_retries}次): {last_err}")

    # ─────────────────────────── 只读查询接口 ───────────────────────────

    @staticmethod
    def get_track(tracking_number: str) -> Optional[Dict[str, Any]]:
        """查询运单轨迹 (gettrack)。返回 data[0] (含 details 时间线); 无轨迹返回 None"""
        result = ChudaoService.call("gettrack", {"tracking_number": tracking_number})
        if not result.get("success"):
            return None
        data = result.get("data") or []
        return data[0] if isinstance(data, list) and data else None

    @staticmethod
    def get_tracking_numbers_batch(reference_nos: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量按参考号查跟踪单号 (gettrackingnumberbatch)

        返回 {传入号码: {"order_id":..., "shipping_method_no":..., "channel_hawbcode":...}},
        仅包含 success=1 的条目。注意: API 实测对初道自有运单号同样命中,
        响应字段为 "refrence_no" (API拼写如此)。
        """
        if not reference_nos:
            return {}
        result = ChudaoService.call("gettrackingnumberbatch", {"reference_no_lst": reference_nos})
        mapping: Dict[str, Dict[str, Any]] = {}
        for item in (result.get("data") or []):
            if not isinstance(item, dict) or not item.get("success"):
                continue
            no = item.get("refrence_no") or item.get("reference_no") or ""
            if no:
                mapping[str(no)] = {
                    "order_id": item.get("order_id") or "",
                    "shipping_method_no": item.get("shipping_method_no") or "",
                    "channel_hawbcode": item.get("channel_hawbcode") or "",
                }
        return mapping
