"""
计费回归测试主程序: 14万样本, 以 Excel《巨富挂件计价表0819》公式移植为标准
对比对象:
  A. 后端试算  PricingService.calculate_sku_pricing (server/services/pricing_service.py)
  B. 前端子SKU  PricingToolEngine.calculate (server/static/js/pricing_tool.js, Node 运行真实代码)
用法: python3 run_regression.py [样本数, 默认140000]
输出: report.md + mismatches.csv
"""
import csv
import json
import math
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))          # 项目根

from server.services.pricing_service import PricingService          # noqa: E402
from excel_standard import excel_standard, CHANNEL_MAP, quotable    # noqa: E402

TOL = 0.02            # 运费容差 (舍入路径差异)
N_RANDOM = 120000
N_BOUNDARY = 20000


# ---------------------------------------------------------------- 样本生成
def gen_samples(seed=42, random_only=False, n_random=N_RANDOM, n_boundary=N_BOUNDARY):
    rng = random.Random(seed)
    samples = []
    # 1) 随机域: 覆盖业务常见大件/挂件范围
    for _ in range(n_random):
        samples.append({
            "L": round(rng.uniform(5, 215), 1),
            "W": round(rng.uniform(3, 100), 1),
            "H": round(rng.uniform(3, 100), 1),
            "F": round(rng.uniform(0.1, 35), 1),
            "purchase": round(rng.uniform(5, 600), 1),
        })
    if random_only:
        return samples
    # 2) 边界网格: 全部阈值 ±1 交叉
    dim_vals = [119, 120, 121, 159, 160, 161, 179, 180, 200, 201, 220, 221,
                239, 240, 241, 259, 260, 261, 305, 306, 69, 70, 71, 79, 80, 81,
                99, 100, 150, 151, 175, 176, 155, 156, 250, 251]
    wt_vals = [0.5, 2, 2.1, 5, 5.1, 9.9, 10, 10.1, 20, 20.1, 21, 30, 30.1]
    i = 0
    while len(samples) < n_random + n_boundary:
        L = dim_vals[(i * 7) % len(dim_vals)] + 0.0
        W = dim_vals[(i * 11 + 3) % len(dim_vals)] + 0.0
        H = dim_vals[(i * 13 + 7) % len(dim_vals)] + 0.0
        if L + W + H > 1100:                          # 控制在三边和量级内
            H = max(3.0, 1100 - L - W)
        F = wt_vals[i % len(wt_vals)]
        samples.append({"L": L, "W": W, "H": H, "F": F,
                        "purchase": 100 + (i % 50)})
        i += 1
    return samples


# ---------------------------------------------------------------- 单渠道比对
def state_of(v):
    """归一状态: '可用'(数值) / '拒收' / '询价' / '不适用'"""
    if quotable(v):
        return "可用"
    if v in ("超尺单询", "超3倍泡单询", "询价"):
        return "询价"
    if v == "不适用":
        return "不适用"
    return "拒收"


def compare_channel(excel_v, engine_v):
    """返回 (category, cost_diff)  category: match(双方一致: 均可报价且价差≤容差,
    或双方均不报价[拒收/询价/不适用任意组合]) / missing(误拒) / extra(多报) /
    price_diff"""
    es, vs = state_of(excel_v), state_of(engine_v)
    if es == "可用" and vs == "可用":
        d = float(engine_v) - float(excel_v)
        return ("match" if abs(d) <= TOL else "price_diff"), d
    if es == "可用" and vs != "可用":
        return "missing", None                        # Excel 有报价, 系统没有 (误拒/漏报)
    if es != "可用" and vs == "可用":
        return "extra", None                          # Excel 不报价, 系统反而报价
    return "match", None                              # 双方均不报价 = 一致


def main():
    args = sys.argv[1:]
    seed = 42
    random_only = False
    n_target = None
    i = 0
    while i < len(args):
        if args[i] == "--seed":
            i += 1; seed = int(args[i])
        elif args[i] == "--random-only":
            random_only = True
        elif args[i].isdigit():
            n_target = int(args[i])
        i += 1
    samples = gen_samples(seed=seed, random_only=random_only)
    if n_target:
        samples = samples[:n_target]
    mode = f"纯随机(seed={seed})" if random_only else f"随机+边界网格(seed={seed})"
    print(f"样本量: {len(samples)}  模式: {mode}")

    # 1) 跑真实前端引擎 (Node)
    (HERE / "samples.json").write_text(json.dumps(samples))
    subprocess.run(["node", str(HERE / "run_node.js"),
                    str(HERE / "samples.json"), str(HERE / "js_results.json")],
                   check=True, cwd=HERE)
    js_results = json.loads((HERE / "js_results.json").read_text())

    # 2) 逐样本: Excel 标准 / 后端试算 / 前端引擎
    stats = {name: {"eng": defaultdict(int), "py": defaultdict(int),
                    "eng_diffs": [], "py_diffs": [], "n": 0} for _, name in CHANNEL_MAP}
    optimal = {"js": {"match": 0, "diff": 0, "none": 0},
               "py": {"match": 0, "diff": 0, "none": 0}}
    price_rows = []
    csv_rows = []                                     # 缓存异常明细, 避免二次重算

    for idx, (s, jr) in enumerate(zip(samples, js_results)):
        ex = excel_standard(s["L"], s["W"], s["H"], s["F"], s["purchase"])
        py = PricingService.calculate_sku_pricing(s["L"], s["W"], s["H"], s["F"], s["purchase"])
        py_f = {f["channel"]: f for f in py["freights"]}

        for col, name in CHANNEL_MAP:
            ev = ex["channels"][name]
            st = stats[name]
            st["n"] += 1
            if state_of(ev) == "可用":
                st["eng"]["_excel_quotable"] += 1
                st["py"]["_excel_quotable"] += 1
            # A. 前端引擎
            jv = jr["freights"].get(name, {}).get("cost", "拒收")
            cat, d = compare_channel(ev, jv)
            st["eng"][cat] += 1
            if cat == "price_diff":
                st["eng_diffs"].append((idx, float(ev), float(jv)))
                csv_rows.append([idx, s["L"], s["W"], s["H"], s["F"], name, ev, jv, ""])
            elif cat in ("missing", "extra"):
                csv_rows.append([idx, s["L"], s["W"], s["H"], s["F"], name, ev, jv, ""])
            # B. 后端试算
            pv = py_f[name]["cost"] if name in py_f and py_f[name].get("status") == "可用" \
                else (py_f[name].get("status") if name in py_f else "拒收")
            cat2, d2 = compare_channel(ev, pv)
            st["py"][cat2] += 1
            if cat2 == "price_diff":
                st["py_diffs"].append((idx, float(ev), float(pv)))
                csv_rows.append([idx, s["L"], s["W"], s["H"], s["F"], name, ev, "", pv])
            elif cat2 in ("missing", "extra"):
                csv_rows.append([idx, s["L"], s["W"], s["H"], s["F"], name, ev, "", pv])

        # 最优渠道比对
        ex_quot = {name: ex["channels"][name] for _, name in CHANNEL_MAP
                   if quotable(ex["channels"][name])}
        ex_best = min(ex_quot, key=ex_quot.get) if ex_quot else None
        for tag, best, freight in (("js", jr["optimalChannel"], jr["optimalFreight"]),
                                   ("py", py["optimal_channel"], py["optimal_freight"])):
            if not best or best == "暂无可用渠道":
                # 系统无可用渠道: Excel 有报价 → 计入不一致
                optimal[tag]["diff" if ex_best else "none"] += 1
            elif ex_best is None:
                optimal[tag]["none"] += 1
            elif best == ex_best and abs(freight - ex_quot[ex_best]) <= TOL:
                optimal[tag]["match"] += 1
            else:
                optimal[tag]["diff"] += 1

        # 售价 (Excel 标准只对普货可报时有值)
        if ex["price_jpy"] is not None:
            price_rows.append((ex["price_jpy"], jr["priceJpy"] or 0, py["final_price_jpy"]))

    # ---------------------------------------------------------------- 报告
    lines = ["# 计费回归测试报告 (标准=Excel巨富计价表0819)", "",
             f"- 样本量: **{len(samples)}**  模式: {mode}",
             "- 引擎A = 前端子SKU/试算工具 (pricing_tool.js, Node 真实运行)",
             "- 引擎B = 后端试算 (pricing_service.py)",
             "- 术语: 误拒=Excel可报价但系统不报价; 多报=Excel不报价但系统报价; "
             "价差=双方均可报价但金额差>0.02元; 双方均不报价(拒收/询价/不适用)视为一致", "",
             "| 渠道 | Excel可报价样本 | A:一致 | A:误拒 | A:多报 | A:价差 | B:一致 | B:误拒 | B:多报 | B:价差 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for _, name in CHANNEL_MAP:
        st = stats[name]
        e, p = st["eng"], st["py"]
        lines.append(
            f"| {name} | {e['_excel_quotable']} "
            f"| {e['match']} | {e['missing']} | {e['extra']} | {e['price_diff']} "
            f"| {p['match']} | {p['missing']} | {p['extra']} | {p['price_diff']} |")

    # 通过判定: 全渠道 A/B 两侧 误拒+多报+价差 均为 0
    bad = []
    for _, name in CHANNEL_MAP:
        e, p = stats[name]["eng"], stats[name]["py"]
        e_bad = e["missing"] + e["extra"] + e["price_diff"]
        p_bad = p["missing"] + p["extra"] + p["price_diff"]
        if e_bad or p_bad:
            bad.append((name, e_bad, p_bad))
    lines += ["", "## 通过判定", ""]
    if not bad:
        lines.append("**PASS — 全部 10 渠道 A/B 两侧 0 误拒 / 0 多报 / 0 价差 (100% 一致)**")
    else:
        for name, e_bad, p_bad in bad:
            lines.append(f"- FAIL {name}: A异常 {e_bad} / B异常 {p_bad}")
    lines.append(f"- 最优渠道不一致: A {optimal['js']['diff']} / B {optimal['py']['diff']}")

    lines += ["", "## 最优渠道选择 (与 Excel 标准一致率)", ""]
    for tag, label in (("js", "A 前端引擎"), ("py", "B 后端试算")):
        o = optimal[tag]
        lines.append(f"- {label}: 一致 {o['match']} / 不一致 {o['diff']} / 双方均无可用渠道 {o['none']}")

    lines += ["", "## 价差明细 (分引擎统计, Excel价 → 系统价)", ""]
    for _, name in CHANNEL_MAP:
        st = stats[name]
        for tag, label in (("eng_diffs", "A前端"), ("py_diffs", "B后端")):
            ds = st[tag]
            if ds:
                avg = sum(b - a for _, a, b in ds) / len(ds)
                mx = max(ds, key=lambda t: abs(t[2] - t[1]))
                lines.append(
                    f"- **{name} [{label}]**: {len(ds)} 条价差, 平均偏差 {avg:+.2f} 元, "
                    f"最大偏差 {mx[2]-mx[1]:+.2f} 元 (例 #{mx[0]}: {mx[1]}→{mx[2]})")

    lines += ["", "## 售价推导 (结构性差异, 非缺陷: Excel=普货运费+利润0.9x+系数28; 系统=最优运费+利润1.0x+系数26)", ""]
    if price_rows:
        djs = [b - a for a, b, _ in price_rows]
        dpy = [c - a for a, _, c in price_rows]
        lines.append(f"- 有标准可比样本: {len(price_rows)}")
        lines.append(f"- A 前端售价 vs Excel: 平均差 {sum(djs)/len(djs):+.0f} 日元 (区间 {min(djs):+.0f} ~ {max(djs):+.0f})")
        lines.append(f"- B 后端售价 vs Excel: 平均差 {sum(dpy)/len(dpy):+.0f} 日元 (区间 {min(dpy):+.0f} ~ {max(dpy):+.0f})")

    (HERE / "report.md").write_text("\n".join(lines))
    print("\n".join(lines))

    # 异常明细 CSV (供逐条核对)
    with open(HERE / "mismatches.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["样本#", "L", "W", "H", "实重", "渠道", "Excel", "前端A", "后端B"])
        w.writerows(csv_rows)
    print(f"\n报告: {HERE/'report.md'}  异常明细: {HERE/'mismatches.csv'} ({len(csv_rows)} 行)")


if __name__ == "__main__":
    main()
