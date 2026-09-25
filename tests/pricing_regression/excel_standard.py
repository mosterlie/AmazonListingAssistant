"""
Excel《巨富挂件计价表0819(采购用)》公式逐字移植 —— 回归测试的"标准"实现
来源: .trae/documents/巨富挂件计价表0819（采购用.xlsx 运费计算 sheet 第3/8行公式
列映射: C=长 D=宽 E=高 F=实重 G=6000泡重 H=8000泡重 I=川日计费重 J=初岛计费重
        K=初岛160计费重 L=黑猫计费重 M=顺丰小包计费重 N=国际大件计费重 O=三边和
        P=顺丰小包 Q=国际大件 R=普货小包(日川普货) S=带电小包 T=川日大包
        U=佐川大件 V=义乌小包 W=初岛160免泡 X=初岛黑猫 Y=航空大包
状态: 数值=可用报价, "拒收", "询价"(超尺单询/超3倍泡单询), "不适用"(R/S, 实重>912.5)
"""
import math
from typing import Dict, Any, Optional

# Excel 列名 -> 渠道名
CHANNEL_MAP = [
    ("P", "顺丰小包"), ("Q", "顺丰国际大件"), ("R", "日川普货"), ("S", "日川带电"),
    ("T", "川日大包"), ("U", "佐川大件"), ("V", "义乌小包"), ("W", "初岛160免泡"),
    ("X", "初岛黑猫"), ("Y", "航空邮政大包"),
]


def _roundup(x: float, n: int = 0) -> float:
    """Excel ROUNDUP: 正数向上远离零"""
    f = 10 ** n
    return math.ceil(round(x * f, 6)) / f


def _ceil_half(x: float) -> float:
    """Excel CEILING(x, 0.5)"""
    return math.ceil(round(x / 0.5, 6)) * 0.5


def _ceil_int(x: float) -> float:
    """Excel CEILING(x, 1)"""
    return math.ceil(round(x, 6))


def excel_standard(length: float, width: float, height: float, weight: float,
                   purchase: float) -> Dict[str, Any]:
    C, D, E, F = float(length), float(width), float(height), float(weight)
    O = C + D + E                                    # O3
    G = _roundup(C * D * E / 6000, 3)                # G3
    H = _roundup(C * D * E / 8000, 3)                # H3
    mx = max(C, D, E)
    mn = min(C, D, E)
    md = O - mx - mn                                 # MEDIAN

    # ---- 计费重列 ----
    if O > 960:
        I = None                                     # 川日计费重 "拒收"
    else:
        raw = F if O < 100 else (F if F > G else (F + G) / 2)
        I = _roundup(raw / 0.5, 0) * 0.5
    J = F if O <= 140 else ((F + G) / 2 if O <= 160 else max(F, G))          # J3
    K = F if O <= 160 else (F + G) / 2                                        # K3
    L = None if O > 159 else (F if O <= 120 else (F + G) / 2)                 # L3 黑猫
    if (C > 120 or D > 120 or E > 120 or O > 160):
        M = None                                     # 顺丰小包计费重 "拒收"
    else:
        M = _roundup(max(F, H), 3)
    if mx > 200 or (md > 80 and mn > 80) or (md > 70 and mn > 70):
        N = None                                     # 国际大件计费重 "拒收"
    else:
        N = _roundup(max(F, G), 3)

    out: Dict[str, Any] = {"O": O, "G": G, "H": H, "I": I, "channels": {}}
    ch = out["channels"]

    # P 顺丰小包 =IF(OR(M="拒收",M>30,M=0),"拒收",ROUNDUP(...*0.8,3))
    if M is None or M > 30 or M == 0:
        ch["顺丰小包"] = "拒收"
    else:
        if M <= 2:
            b = 38 + (( _ceil_half(M) - 0.5) / 0.5) * 8
        elif M <= 5:
            b = 40 + (( _ceil_half(M) - 0.5) / 0.5) * 9
        elif M <= 10:
            b = 41 + (( _ceil_half(M) - 0.5) / 0.5) * 11
        else:
            b = 42 + (( _ceil_half(M) - 0.5) / 0.5) * 12
        ch["顺丰小包"] = _roundup(b * 0.8, 3)

    # Q 国际大件
    if N is None:
        ch["顺丰国际大件"] = "拒收"
    elif N < 100:
        ch["顺丰国际大件"] = _roundup(max(N, 20) * 15, 2)
    elif N < 500:
        ch["顺丰国际大件"] = _roundup(N * 14, 2)
    elif N < 1000:
        ch["顺丰国际大件"] = _roundup(N * 13, 2)
    else:
        ch["顺丰国际大件"] = "询价"

    # R/S 尺寸附加费阶梯 (共用)
    def _size_extra(o: float) -> float:
        if o > 259: return 260.0
        if o > 239: return 260.0
        if o > 220: return 200.0
        if o > 200: return 150.0
        if o > 179: return 100.0
        if o > 159: return 80.0
        return 0.0

    # R 普货小包(日川普货)
    if I is None:
        ch["日川普货"] = "拒收"
    elif F > 912.5:
        ch["日川普货"] = "不适用"
    else:
        if I <= 2:   b = 32 + 6.5 * (_ceil_int(I / 0.5) - 1)
        elif I <= 5: b = 33 + 7 * (_ceil_int(I / 0.5) - 1)
        elif I <= 10: b = 34 + 7.5 * (_ceil_int(I / 0.5) - 1)
        else:        b = 35 + 8 * (_ceil_int(I / 0.5) - 1)
        ch["日川普货"] = _roundup(b + _size_extra(O) + (50.0 if F > 9.9 else 0.0), 0)

    # S 带电小包(日川带电)
    if I is None:
        ch["日川带电"] = "拒收"
    elif F > 912.5:
        ch["日川带电"] = "不适用"
    else:
        if I <= 2:   b = 38 + 9 * (_ceil_int(I / 0.5) - 1)
        elif I <= 5: b = 39 + 9.5 * (_ceil_int(I / 0.5) - 1)
        elif I <= 10: b = 40 + 10 * (_ceil_int(I / 0.5) - 1)
        else:        b = 41 + 11 * (_ceil_int(I / 0.5) - 1)
        ch["日川带电"] = _roundup(b + _size_extra(O) + (50.0 if F > 9.9 else 0.0), 0)

    # T 川日大包 (无 ROUNDUP, 无计费重上限)
    if C > 305 or D > 175 or E > 155:
        ch["川日大包"] = "询价"                      # 超尺单询
    elif I is None or I > F * 3:
        ch["川日大包"] = "询价"                      # 超3倍泡单询 (I="拒收"文本比较恒真)
    else:
        if I < 21:
            v = 60 + 18 * (_ceil_int(I / 0.5) - 1)
        else:
            if I < 51: r = 19.0
            elif I < 101: r = 18.5
            elif I < 301: r = 17.5
            elif I < 501: r = 17.0
            elif I < 1000: r = 16.5
            else: r = 16.0
            v = I * r
        if mx > 159 and I < 300:
            v += 200.0
        ch["川日大包"] = v

    # U 佐川大件 ("拒收">30 在 Excel 中为 TRUE)
    if I is None or I > 30 or O > 250 or mx > 150:
        ch["佐川大件"] = "拒收"
    else:
        ch["佐川大件"] = 40 + 10 * (_ceil_int(I / 0.5) - 1)

    # V 义乌小包 (J 永不为"拒收", 实际只受尺寸限制)
    if F > 912.5 or mx > 9100 or O > 9160:
        ch["义乌小包"] = "拒收"
    else:
        if J <= 2:   b = 34 + 6 * (_ceil_int(J / 0.5) - 1)
        elif J <= 5: b = 35 + 7 * (_ceil_int(J / 0.5) - 1)
        else:        b = 36 + 8 * (_ceil_int(J / 0.5) - 1)
        extra = max(35.0 if mx > 99 else 0.0,
                    120.0 if O > 200 else (80.0 if O > 160 else 0.0))
        ch["义乌小包"] = _roundup(b + extra, 0)

    # W 初岛160免泡
    if F > 912.5 or mx > 9100 or O > 260:
        ch["初岛160免泡"] = "拒收"
    else:
        if K <= 2:   b = 34 + 6 * (_ceil_int(K / 0.5) - 1)
        elif K <= 5: b = 35 + 7 * (_ceil_int(K / 0.5) - 1)
        else:        b = 36 + 8 * (_ceil_int(K / 0.5) - 1)
        extra = (100.0 if O > 200 else (50.0 if O > 160 else 0.0)) + \
                (20.0 if O > 200 else (30.0 if O > 160 else 0.0))
        ch["初岛160免泡"] = _roundup(b + extra, 0) + 20.0

    # X 初岛黑猫
    if L is None or F > 912.5 or mx > 160 or O > 160:
        ch["初岛黑猫"] = "拒收"
    else:
        if L <= 2:   b = 36 + 6 * (_ceil_int(L / 0.5) - 1)
        elif L <= 5: b = 37 + 7 * (_ceil_int(L / 0.5) - 1)
        elif L <= 10: b = 38 + 8 * (_ceil_int(L / 0.5) - 1)
        else:        b = 39 + 10 * (_ceil_int(L / 0.5) - 1)
        ch["初岛黑猫"] = _roundup(b, 0)

    # Y 航空邮政大包 (正常围长打9折, 超330不打折也不拒收)
    if F > 30 or mx > 150:
        ch["航空邮政大包"] = "拒收"
    else:
        girth = (O - mx) * 2 + mx
        v = (124.2 + (_ceil_int(F) - 1) * 29.6) * (1.0 if girth > 330 else 0.9) + 8
        ch["航空邮政大包"] = _roundup(v, 2)

    # ---- Excel 售价推导 (AE=采购+普货小包运费, AF=AE*0.9, AG=(AE+AF)*28) ----
    r_val = ch["日川普货"]
    if isinstance(r_val, (int, float)):
        ae = purchase + r_val
        af = ae * 0.9
        out["price_jpy"] = (ae + af) * 28
    else:
        out["price_jpy"] = None
    return out


def quotable(v: Any) -> bool:
    return isinstance(v, (int, float))
