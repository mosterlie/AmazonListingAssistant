"""
WorkBuddy 大模型服务 (OpenAI 兼容网关)

用途: 订单管理「商品标识」识别 —— 由商品标题判断这是什么东西 (商品品类/品名) 并落库。

接口约束 (实测):
    POST https://copilot.tencent.com/v2/chat/completions
    Authorization: Bearer ck_xxx
    仅支持 Stream (stream=true), 非流式直接返回 400 code=11101
    SSE: data: {...delta.content...} ... data: [DONE], 末帧携带 usage

配置优先级: 系统设置 (workbuddy_base_url / workbuddy_api_key / workbuddy_model)
            > server/config.py 默认值
"""
import base64
import json
import re
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

from server.config import WORKBUDDY_BASE_URL, WORKBUDDY_API_KEY, WORKBUDDY_MODEL

BATCH_SIZE = 15          # 单次请求最多识别的标题数 (控制耗时与失败影响面)
REQUEST_TIMEOUT = 180    # 单次请求超时 (秒); 模型思考较慢时留足余量
BATCH_INTERVAL = 0.3     # 批次间隔, 降低触发限频概率

PRODUCT_SYSTEM_PROMPT = (
    "你是跨境电商选品与商品分类专家，只输出 JSON，不输出任何解释。"
)

PRODUCT_PROMPT_TMPL = """请逐条判断下列商品标题描述的是「什么商品」，并为每条给出完整版与简版两个名称。

完整版 product 规则：
1. 输出该商品的通用中文名称（品类/品名），如「玻璃楼梯扶手立柱」「鱼缸过滤滤材」「厨房收纳置物架」。
2. 6~14 个汉字，名词短语；不带品牌名、店铺名、型号、材质堆砌、颜色/尺寸、促销词。
3. 多件组合或套装，只输出主体商品名称（如「不锈钢晾衣架」）。
4. 只看标题，信息不足时按最可能的品类归纳，不要臆造细节。
5. 标题完全无法判断（乱码、纯编号）时，product 与 short 均输出「未知」。

简版 short 规则：
1. 必须是完整版的更短概括，2~5 个汉字，绝不超过 5 个汉字。
2. 保留最核心的品类词，可省略修饰语，如「玻璃楼梯扶手立柱」→「玻璃扶手」、「鱼缸过滤滤材」→「鱼缸滤材」、「桌面置物收纳书架」→「收纳书架」。
3. 不加标点、空格、数量词。

严格返回如下 JSON（序号从 1 开始，条数与输入一致）：
{{"results":[{{"i":1,"product":"完整名称","short":"简版"}}]}}

商品标题：
{titles}"""


class WorkBuddyError(Exception):
    """WorkBuddy 调用异常"""


def _cfg() -> Tuple[str, str, str]:
    """读取运行时配置: (base_url, api_key, model), 系统设置优先"""
    try:
        from server.database import get_setting
        base = str(get_setting("workbuddy_base_url", "") or "").strip()
        key = str(get_setting("workbuddy_api_key", "") or "").strip()
        model = str(get_setting("workbuddy_model", "") or "").strip()
    except Exception:
        base = key = model = ""
    return (base or WORKBUDDY_BASE_URL).rstrip("/"), (key or WORKBUDDY_API_KEY), (model or WORKBUDDY_MODEL)


def _stream_chat(messages: List[dict], temperature: float = 0.2,
                 timeout: int = REQUEST_TIMEOUT) -> Tuple[str, Dict[str, int]]:
    """向 WorkBuddy 发起流式对话并聚合结果 (纯文本/多模态共用)"""
    base_url, api_key, model = _cfg()
    if not api_key:
        raise WorkBuddyError("未配置 WorkBuddy API Key")

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/event-stream",
        },
    )

    chunks: List[str] = []
    usage: Dict[str, int] = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                if obj.get("usage"):
                    u = obj["usage"] or {}
                    usage = {
                        "prompt_tokens": int(u.get("prompt_tokens") or 0),
                        "completion_tokens": int(u.get("completion_tokens") or 0),
                        "total_tokens": int(u.get("total_tokens") or 0),
                    }
                for choice in obj.get("choices") or []:
                    piece = ((choice.get("delta") or {}).get("content"))
                    if piece:
                        chunks.append(piece)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:500]
        except Exception:
            pass
        raise WorkBuddyError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise WorkBuddyError(f"网络异常: {exc.reason}") from exc

    text = "".join(chunks).strip()
    if not text:
        raise WorkBuddyError("模型未返回内容")
    return text, usage


def chat(prompt: str, system: str = "", temperature: float = 0.2,
         timeout: int = REQUEST_TIMEOUT) -> Tuple[str, Dict[str, int]]:
    """调用 WorkBuddy 对话接口 (流式聚合), 返回 (完整回复文本, token 用量)"""
    messages: List[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _stream_chat(messages, temperature=temperature, timeout=timeout)


def chat_with_images(prompt: str, images: List[bytes], mime: str = "image/jpeg",
                     system: str = "", temperature: float = 0.1,
                     timeout: int = REQUEST_TIMEOUT) -> Tuple[str, Dict[str, int]]:
    """多模态调用: 文本 + 若干张图片 (按顺序以 image_url data URI 传入)"""
    if not images:
        raise WorkBuddyError("没有可识别的图片内容")
    content: List[dict] = [{"type": "text", "text": prompt}]
    for raw in images:
        b64 = base64.b64encode(raw).decode("ascii")
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"}})
    messages: List[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    return _stream_chat(messages, temperature=temperature, timeout=timeout)


def _extract_json(text: str) -> Optional[dict]:
    """从回复中提取首个 JSON 对象 (容错 markdown 代码块/前后废话)"""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        candidate = text[start:end + 1]
    try:
        obj = json.loads(candidate)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _log_call(prompt: str, response: str, model: str, status: str, error: str,
              usage: Dict[str, int], duration_ms: int) -> None:
    """记录调用日志 (llm_call_logs, 失败也记录; 日志异常不影响主流程)"""
    try:
        from server.database import get_db_connection
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO llm_call_logs (scene, source, model, title, prompt, response, status, error_detail,
                                           prompt_tokens, completion_tokens, total_tokens, duration_ms, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "order_product", "workbuddy", model, "订单商品标识识别",
                prompt[:20000], (response or "")[:20000], status, error[:2000],
                usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0), duration_ms, "system",
            ))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


SHORT_LABEL_MAX = 5      # 简版商品标识最大汉字数


def identify_products(titles: List[str]) -> Dict[str, Dict[str, str]]:
    """批量识别商品标题"是什么商品", 返回 {标题原文: {"product": 完整, "short": 简版}}

    失败的标题不出现在结果中; 同一批内自动去重; 分批调用, 单批失败仅影响该批。
    """
    uniq: List[str] = []
    seen = set()
    for t in titles or []:
        key = (t or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(key)
    if not uniq:
        return {}

    result: Dict[str, Dict[str, str]] = {}
    for start in range(0, len(uniq), BATCH_SIZE):
        batch = uniq[start:start + BATCH_SIZE]
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(batch))
        prompt = PRODUCT_PROMPT_TMPL.format(titles=numbered)
        model = _cfg()[2]
        started = time.monotonic()
        status, err, raw, usage = "success", "", "", {}
        try:
            raw, usage = chat(prompt, system=PRODUCT_SYSTEM_PROMPT, temperature=0.1)
            obj = _extract_json(raw) or {}
            rows = obj.get("results")
            if not isinstance(rows, list):
                raise WorkBuddyError("返回结构不符合预期")
            for item in rows:
                if not isinstance(item, dict):
                    continue
                try:
                    idx = int(item.get("i"))
                except (TypeError, ValueError):
                    continue
                label = re.sub(r"\s+", "", str(item.get("product") or "").strip())[:20]
                short = re.sub(r"\s+", "", str(item.get("short") or "").strip())
                if not label:
                    continue
                # 简版缺失/超长时兜底: 取完整版前 5 个字
                short = short[:SHORT_LABEL_MAX] or label[:SHORT_LABEL_MAX]
                if 1 <= idx <= len(batch):
                    result[batch[idx - 1]] = {"product": label, "short": short}
        except Exception as exc:  # 单批失败不影响其余批次
            status, err = "error", str(exc)
        finally:
            _log_call(prompt, raw, model, status, err, usage,
                      int((time.monotonic() - started) * 1000))
        if start + BATCH_SIZE < len(uniq):
            time.sleep(BATCH_INTERVAL)
    return result


def identify_product(title: str) -> Optional[Dict[str, str]]:
    """单条标题识别 (便于调试/单测)"""
    return identify_products([title]).get((title or "").strip())
