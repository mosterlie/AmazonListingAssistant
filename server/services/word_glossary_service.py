"""英文标识逐词翻译 (本地词表 + 数据库缓存)

用途: 订单列表「商品标识」英文行悬停时, 展示每个单词的中文含义。
数据: word_glossary 表 (word 小写主键, zh 中文), 首次运行自动灌入内置词表;
      未收录的词返回空中文, 前端展示原词, 可随时在表里补充。
"""
import re
import threading
from typing import Any, Dict, List

from server.database import get_db_connection

# 内置基础词表 (跨境电商高频词, 可继续扩充)
SEED: Dict[str, str] = {
    # 材质 / 工艺
    "stainless": "不锈钢", "steel": "钢", "aluminum": "铝", "alloy": "合金",
    "plastic": "塑料", "wood": "木质", "wooden": "木制", "metal": "金属",
    "iron": "铁", "copper": "铜", "brass": "黄铜", "silicone": "硅胶",
    "canvas": "帆布", "fabric": "布料", "leather": "皮革", "glass": "玻璃",
    "ceramic": "陶瓷", "acrylic": "亚克力", "abs": "ABS", "pp": "PP",
    "carbon": "碳", "fiber": "纤维", "fiberglass": "玻璃纤维", "foam": "海绵",
    "rubber": "橡胶", "nylon": "尼龙", "polyester": "聚酯", "cotton": "棉",
    "galvanized": "镀锌", "plated": "镀层", "rustproof": "防锈", "waterproof": "防水",
    # 家居 / 收纳
    "storage": "收纳", "shelf": "置物架", "rack": "架子", "holder": "支架",
    "organizer": "整理盒", "box": "盒子", "basket": "篮子", "bag": "袋",
    "bucket": "桶", "bin": "储物箱", "cart": "推车", "stand": "支架",
    "hanger": "挂钩", "hook": "挂钩", "clip": "夹子", "tray": "托盘",
    "board": "板", "panel": "面板", "cabinet": "柜子", "drawer": "抽屉",
    "desk": "桌面", "table": "桌子", "chair": "椅子", "stool": "凳子",
    # 厨房 / 餐厨
    "kitchen": "厨房", "cutting": "切菜", "knife": "刀",
    "plate": "盘子", "bowl": "碗", "cup": "杯子", "mug": "马克杯",
    "bottle": "瓶子", "jar": "罐", "pot": "锅", "pan": "平底锅",
    "grill": "烤网", "net": "网", "oven": "烤箱", "stove": "炉灶",
    "drainer": "沥水架", "dish": "餐具", "food": "食物", "seal": "密封",
    # 排水 / 建材
    "drainage": "排水", "trench": "沟槽", "drain": "排水沟", "gutter": "檐沟",
    "cover": "盖板", "grating": "格栅", "pipe": "管道", "hose": "软管",
    "faucet": "水龙头", "valve": "阀门", "pump": "泵", "filter": "过滤器",
    "mesh": "网", "wire": "铁丝", "fence": "围栏", "fencing": "围栏",
    "tube": "管", "connector": "接头", "fitting": "配件", "bracket": "支架",
    # 楼梯 / 建筑
    "stair": "楼梯", "stairs": "楼梯", "staircase": "楼梯", "handrail": "扶手",
    "railing": "栏杆", "rail": "横杆", "post": "立柱", "pillar": "柱子",
    "balcony": "阳台", "garden": "庭院", "outdoor": "户外", "indoor": "室内",
    "wall": "墙", "floor": "地面", "ceiling": "天花板", "door": "门",
    "window": "窗", "flooring": "地板", "roof": "屋顶", "patio": "露台",
    # 尺寸 / 规格
    "size": "尺寸", "length": "长度", "width": "宽度", "height": "高度",
    "depth": "深度", "thickness": "厚度", "diameter": "直径", "large": "大号",
    "small": "小号", "mini": "迷你", "big": "大", "long": "长",
    "short": "短", "wide": "宽", "narrow": "窄", "set": "套装",
    "pack": "装", "piece": "个", "pcs": "件", "cm": "厘米",
    "mm": "毫米", "inch": "英寸", "layer": "层", "tier": "层",
    # 功能 / 特性
    "foldable": "可折叠", "folding": "折叠", "adjustable": "可调节",
    "portable": "便携", "multifunctional": "多功能", "universal": "通用",
    "durable": "耐用", "heavy": "重型", "duty": "负载", "lightweight": "轻量",
    "non": "非", "slip": "滑", "antislip": "防滑", "heat": "耐热",
    "resistant": "耐", "proof": "防护", "easy": "简便", "clean": "清洁",
    "installation": "安装", "assembly": "组装", "free": "免", "tool": "工具",
    "reusable": "可重复使用", "washable": "可水洗", "breathable": "透气",
    # 其他常见
    "home": "家用", "office": "办公", "car": "汽车", "auto": "自动",
    "bike": "自行车", "pet": "宠物", "dog": "狗", "cat": "猫",
    "baby": "婴儿", "kids": "儿童", "toy": "玩具", "sport": "运动",
    "fishing": "钓鱼", "camping": "露营", "travel": "旅行", "beach": "沙滩",
    "pool": "泳池", "light": "灯", "led": "LED", "lamp": "台灯",
    "fan": "风扇", "heater": "加热器", "cooler": "冷却器", "humidifier": "加湿器",
    "brush": "刷子", "cleaner": "清洁器", "mop": "拖把", "broom": "扫把",
    "mat": "垫子", "cushion": "坐垫", "pillow": "枕头", "blanket": "毯子",
    "curtain": "窗帘", "carpet": "地毯", "rug": "小地毯",
    "aquarium": "鱼缸", "tank": "水槽",
    "wax": "蜡", "candle": "蜡烛", "cone": "锥形", "taper": "锥形", "beeswax": "蜜蜡",
    "fireproof": "防火", "flame": "阻燃", "retardant": "阻燃",
    "film": "膜", "insulation": "隔热", "thermal": "保温", "sun": "遮阳",
    "shade": "遮阳", "screen": "纱窗", "privacy": "隐私",
    "pickleball": "匹克球", "racket": "球拍", "ball": "球",
    "globe": "地球仪", "decor": "装饰", "ornament": "摆件",
    "shift": "换挡", "knob": "旋钮", "gear": "齿轮", "handle": "手柄",
    "lock": "锁", "hinge": "合页", "screw": "螺丝", "bolt": "螺栓",
    "tape": "胶带", "glue": "胶水", "adhesive": "粘合剂",
    "medical": "医疗", "culture": "培养", "ring": "环", "loop": "环",
}

_LOCK = threading.Lock()
_SEEDED = {"done": False}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']*")

# 停用词: 无实际含义, 不做翻译展示
_STOP = {"a", "an", "the", "for", "of", "with", "and", "or", "to", "in", "on",
         "at", "by", "per", "from", "is", "are", "be", "your", "our", "this", "that"}


class WordGlossaryService:

    @staticmethod
    def _ensure_seed() -> None:
        """首次调用时把内置词表写入数据库 (已存在的不覆盖)"""
        if _SEEDED["done"]:
            return
        with _LOCK:
            if _SEEDED["done"]:
                return
            conn = get_db_connection()
            try:
                # 兜底建表 (脚本/测试环境未跑 init_db 时也能用)
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS word_glossary ("
                    " word TEXT PRIMARY KEY, zh TEXT DEFAULT '',"
                    " updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
                for word, zh in SEED.items():
                    conn.execute(
                        "INSERT INTO word_glossary (word, zh) VALUES (?, ?) "
                        "ON CONFLICT(word) DO NOTHING", (word, zh))
                conn.commit()
                _SEEDED["done"] = True
            finally:
                conn.close()

    @staticmethod
    def split_words(text: str) -> List[str]:
        """拆词: 去重保序, 只保留字母词 (>=2 字符)"""
        out: List[str] = []
        seen = set()
        for m in _WORD_RE.finditer(str(text or "")):
            w = m.group(0).strip("-'")
            if len(w) < 2:
                continue
            if w.lower() in _STOP:
                continue
            key = w.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(w)
        return out

    @staticmethod
    def _candidates(word: str) -> List[str]:
        """词形候选: 原词 + 去复数/去词尾 (candles→candle, boxes→box, caring→care)"""
        w = word.lower()
        out = [w]
        if w.endswith("ies") and len(w) > 4:
            out.append(w[:-3] + "y")
        if w.endswith("es") and len(w) > 3:
            out.append(w[:-2])
        if w.endswith("s") and len(w) > 3:
            out.append(w[:-1])
        if w.endswith("ing") and len(w) > 5:
            out.append(w[:-3])
        if w.endswith("ed") and len(w) > 4:
            out.append(w[:-2])
        return out

    @staticmethod
    def translate(text: str) -> List[Dict[str, Any]]:
        """返回 [{word, zh}] (未收录的词 zh 为空串)"""
        words = WordGlossaryService.split_words(text)
        if not words:
            return []
        WordGlossaryService._ensure_seed()
        keys = sorted({k for w in words for k in WordGlossaryService._candidates(w)})
        conn = get_db_connection()
        try:
            marks = ",".join("?" * len(keys))
            rows = conn.execute(
                f"SELECT word, zh FROM word_glossary WHERE word IN ({marks})",
                keys).fetchall()
        finally:
            conn.close()
        zh_map = {r["word"]: (r["zh"] or "") for r in rows}
        out: List[Dict[str, Any]] = []
        for w in words:
            zh = ""
            for cand in WordGlossaryService._candidates(w):
                if zh_map.get(cand):
                    zh = zh_map[cand]
                    break
            out.append({"word": w, "zh": zh})
        return out

    @staticmethod
    def add_words(pairs: Dict[str, str]) -> int:
        """补充词表 (人工/接口用): {word: zh}"""
        items = {str(k).strip().lower(): str(v).strip()
                 for k, v in (pairs or {}).items() if str(k).strip()}
        if not items:
            return 0
        conn = get_db_connection()
        try:
            for word, zh in items.items():
                conn.execute(
                    "INSERT INTO word_glossary (word, zh, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(word) DO UPDATE SET zh = excluded.zh, "
                    "updated_at = CURRENT_TIMESTAMP", (word, zh))
            conn.commit()
            return len(items)
        finally:
            conn.close()
