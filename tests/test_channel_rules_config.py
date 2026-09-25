"""
系统管理 · 快递费用配置 (channel_rules) 模块全量测试
硬性要求: 每个渠道 ≥10w 测试用例, 一次全部通过; 覆盖各种边界场景。

测试内容:
  A. 维护功能: 完整规则入库→回读逐字段一致 / null清除回退 / 逐渠道全参数扰动持久化
  B. 计算正确性: DB配置路径 (GET下发的规则喂给引擎) × 14.8w样本 (12w随机 + 2w阈值边界网格 + 定制边界场景)
     每渠道 ~14.8w 用例, 逐渠道与 Excel标准 比对 (0误拒/0多报/0价差 才算通过)
  C. 引擎健壮性: 随机扰动规则 (删字段/置空/改类型) × 探针输入, 不允许抛异常
结束后恢复原配置, 不污染数据。
"""
import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE / "pricing_regression"))

from server.database import get_setting, set_setting                       # noqa: E402
from server.routers.settings_router import get_system_settings, update_system_settings, SystemSettingsSchema  # noqa: E402
from run_regression import gen_samples, compare_channel                    # noqa: E402
from excel_standard import excel_standard, CHANNEL_MAP, quotable           # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail and not cond else ""))


ADMIN = {"username": "tester", "role": "admin"}


def post_rules(rules):
    payload = asyncio.run(get_system_settings())
    body = SystemSettingsSchema(**{**payload["data"], "channel_rules": rules})
    return asyncio.run(update_system_settings(body, admin=ADMIN))


def get_rules():
    return asyncio.run(get_system_settings())["data"]["channel_rules"]


def node_calc(rules, samples, tag):
    rp, sp, op = HERE / f"rules_{tag}.json", HERE / f"samples_{tag}.json", HERE / f"out_{tag}.json"
    rp.write_text(json.dumps(rules if rules is not None else "null"))
    sp.write_text(json.dumps(samples))
    subprocess.run(["node", str(HERE / "run_node_rules.js"),
                    str(rp) if rules is not None else "null",
                    str(sp), str(op)], check=True, cwd=ROOT)
    out = json.loads(op.read_text())
    rp.unlink(); sp.unlink(); op.unlink()
    return out


# ------------------------------------------------------------ 定制边界场景
def edge_samples():
    E = []

    def add(L, W, H, F):
        E.append({"L": L, "W": W, "H": H, "F": F, "purchase": 100.0})

    # 顺丰小包: 实重30边界 / 单边120 / 三边和160 / 档位2/5/10
    for wt in (29.9, 30.0, 30.1):
        add(50, 20, 10, wt)
    for side in (119.9, 120.0, 120.1):
        add(side, 20, 10, 1.0)
    for s in (159.9, 160.0, 160.1):
        add(s - 30, 20, 10, 1.0)
    for wt in (2.0, 2.1, 4.9, 5.0, 5.1, 9.9, 10.0, 10.1):
        add(50, 20, 10, wt)
    # 计费重 0.5 进位边界 (2.24→2.5? 2.24*2=4.48→ceil=5→2.5)
    add(50, 20, 10, 2.24); add(50, 20, 10, 2.25); add(50, 20, 10, 2.26)

    # 顺丰国际大件: 单边200 / 中小边同超80、同超70 / 首档min_charge20 / 100/500/1000档位
    for side in (199.9, 200.0, 200.1):
        add(side, 10, 10, 1.0)
    add(90, 80.1, 80.1, 5); add(90, 80.1, 79.9, 5); add(90, 79.9, 79.9, 5)
    add(90, 70.1, 70.1, 5); add(90, 70.1, 69.9, 5)
    add(10, 10, 10, 0.1)                       # cw<20 → min_charge=20
    add(60, 40, 40, 99.9); add(60, 40, 40, 100.0); add(60, 40, 40, 100.1)     # cw 100档
    add(100, 50, 30, 499.9); add(100, 50, 30, 500.0); add(100, 50, 30, 500.1) # 500档
    # vol 重边界: L*W*H/6000 恰为 x.0005 (roundup 3位)

    # 日川普货/带电: 三边和960 / 100档(actual vs avg) / 附加费159/179/200/220/239 / 实重9.9
    for s in (959.9, 960.0, 960.1):
        add(s - 60, 30, 30, 5.0)
    for s in (99.9, 100.0, 100.1):
        add(s - 30, 20, 10, 3.0)
    for s in (159.0, 159.1, 179.0, 179.1, 200.0, 200.1, 220.0, 220.1, 239.0, 239.1):
        add(s - 30, 20, 10, 5.0)
    for wt in (9.8, 9.9, 10.0):
        add(50, 20, 10, wt)

    # 川日大包: 单边305/175/155 / 3倍泡恰好边界 / cw档21/51/101/301/501/1000 / 长边159附加+cw300边界
    for L, mx in ((304.9, 305.0), (305.0, 305.0), (305.1, 305.1)):
        add(L, 50, 50, 5.0)
    add(174.9, 174.9, 50, 5.0); add(175.0, 175.0, 50, 5.0); add(175.1, 175.1, 50, 5.0)
    add(154.9, 154.9, 60, 5.0); add(155.0, 155.0, 60, 5.0); add(155.1, 155.1, 60, 5.0)
    add(50, 50, 60, 5.0)                       # vol=25 → (5+25)/2=15=3×5 → 可报价
    add(50, 50, 60, 4.9)                       # cw15 > 3×4.9 → 询价
    for wt in (20.9, 21.0, 50.9, 51.0, 100.9, 101.0, 300.9, 301.0, 500.9, 501.0):
        add(50, 20, 10, wt)
    add(200, 5, 5, 299.5); add(200, 5, 5, 300.0)   # 长边>159 + cw<300 附加200边界

    # 佐川: cw30 / 三边和250 / 单边150
    for wt in (29.9, 30.0, 30.1):
        add(100, 50, 50, wt)
    for s in (249.9, 250.0, 250.1):
        add(s - 60, 30, 30, 5.0)
    for side in (149.9, 150.0, 150.1):
        add(side, 20, 10, 5.0)

    # 义乌小包: 分段140/160 / 附加99 / 和160/200
    for s in (139.9, 140.0, 140.1, 159.9, 160.0, 160.1):
        add(s - 30, 20, 10, 3.0)
    for side in (98.9, 99.0, 99.1):
        add(side, 20, 10, 3.0)
    for s in (159.9, 160.0, 160.1, 199.9, 200.0, 200.1):
        add(s - 30, 20, 10, 3.0)

    # 初岛160: 和160/260 / 附加160/200
    for s in (159.9, 160.0, 160.1, 259.9, 260.0, 260.1):
        add(s - 30, 20, 10, 3.0)

    # 初岛黑猫: 和120(actual)/120.1(avg) / 159 / 单边160
    for s in (119.9, 120.0, 120.1, 158.9, 159.0, 159.1):
        add(s - 30, 20, 10, 3.0)
    for side in (159.9, 160.0, 160.1):
        add(side, 5, 5, 3.0)

    # 航空邮政大包: 实重30 / 单边150 / 围长330 折扣边界 / 进整边界
    for wt in (29.9, 30.0, 30.1):
        add(50, 20, 10, wt)
    for side in (149.9, 150.0, 150.1):
        add(side, 20, 10, 5.0)
    add(150, 45, 45, 5.0)                      # girth=330 → 0.9折
    add(150, 45.1, 45, 5.0)                    # girth=330.2 → 1.0
    for wt in (1.0, 1.01, 2.0, 2.01):
        add(50, 20, 10, wt)
    return E


# ------------------------------------------------------------ 参数扰动 roundtrip
ENUM = {"cmp": ["lte", "lt"], "mode": ["actual", "max_actual_vol", "avg_actual_vol", "max_actual_avg"],
        "round_total": [None, "round2", "ceil", "ceil2"], "type": ["tiered_step", "first_continue"],
        "pick": ["add", "max"], "basis": ["sum_sides", "max_side", "weight"]}
SKIP = {"key", "name"}


def walk_scalars(obj, path=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += walk_scalars(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += walk_scalars(v, f"{path}[{i}]")
    else:
        out.append((path, obj))
    return out


def perturb_value(path, v):
    key = path.split(".")[-1].split("[")[0]
    if key in ENUM:
        vals = ENUM[key]
        return vals[(vals.index(v) + 1) % len(vals)] if v in vals else v
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        return v + 7.3 if isinstance(v, float) else v + 1
    return v


def perturb_rule(rule):
    r2 = copy.deepcopy(rule)
    for p, v in walk_scalars(rule):
        if p.split(".")[0] in SKIP:
            continue
        keys = p.replace("]", "").replace("[", ".").split(".")
        tgt = r2
        for k in keys[:-1]:
            tgt = tgt[int(k)] if k.isdigit() else tgt[k]
        last = keys[-1]
        if last.isdigit():
            tgt[int(last)] = perturb_value(p, v)
        else:
            tgt[last] = perturb_value(p, v)
    return r2


def main():
    print("== A. 维护功能: 规则入库/回读/清除 ==")
    # 内置默认规则从引擎导出 (前端真实数据)
    code = ("const fs=require('fs');globalThis.window=globalThis;"
            "eval(fs.readFileSync('%s','utf8'));"
            "console.log(JSON.stringify(window.PricingToolEngine.DEFAULT_CHANNEL_RULES));"
            ) % (ROOT / "server/static/js/pricing_tool.js")
    default_rules = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
    snap = get_rules()
    try:
        r = post_rules(default_rules)
        check("完整10渠道规则入库 → code 0", r.get("code") == 0, str(r.get("msg")))
        check("GET 回读与入库规则逐字节一致", get_rules() == default_rules)
        r = post_rules(None)
        check("null 清除规则 → code 0", r.get("code") == 0)
        check("清除后 GET 为 None", get_rules() is None)
        r = post_rules({"channels": default_rules})
        check("兼容 {channels:[...]} 包装格式入库", r.get("code") == 0 and get_rules() == {"channels": default_rules})
        post_rules(None)

        print("\n== A2. 逐渠道全参数扰动持久化 (所有快递配置参数) ==")
        total_params = 0
        for rule in default_rules:
            p = perturb_rule(rule)
            n = sum(1 for pp, _ in walk_scalars(p) if pp.split(".")[0] not in SKIP)
            total_params += n
            r = post_rules([p])
            ok = r.get("code") == 0 and get_rules() == [p]
            check(f"[{rule['name']}] {n} 个参数扰动全部持久化", ok)
        print(f"  覆盖配置参数标量总数: {total_params}")

        print("\n== B. DB配置路径 × 全渠道计算 (每渠道≥10w, 一次通过) ==")
        post_rules(default_rules)
        rules_db = get_rules()
        check("DB规则 = 内置默认 (无失真)", rules_db == default_rules)

        samples = gen_samples(seed=43, random_only=False)     # 12w随机 + 2w边界网格
        samples += edge_samples()
        n = len(samples)
        print(f"样本总量: {n} (随机12w + 边界网格2w + 定制边界{len(samples) - 140000})")

        js = node_calc(rules_db, samples, "cfg")
        stats = {name: {"match": 0, "missing": 0, "extra": 0, "price_diff": 0, "q": 0} for _, name in CHANNEL_MAP}
        diffs = []
        for idx, (s, jr) in enumerate(zip(samples, js)):
            ex = excel_standard(s["L"], s["W"], s["H"], s["F"], s["purchase"])
            for _, name in CHANNEL_MAP:
                ev = ex["channels"][name]
                if quotable(ev):
                    stats[name]["q"] += 1
                jv = jr["freights"].get(name, "拒收")
                cat, _ = compare_channel(ev, jv)
                stats[name][cat] += 1
                if cat in ("missing", "extra", "price_diff") and len(diffs) < 30:
                    diffs.append([idx, s["L"], s["W"], s["H"], s["F"], name, ev, jv, cat])
        print(f"\n| 渠道 | 用例数 | 可报价 | 一致 | 误拒 | 多报 | 价差 |")
        print(f"|---|---|---|---|---|---|---|")
        for _, name in CHANNEL_MAP:
            st = stats[name]
            print(f"| {name} | {st['match']+st['missing']+st['extra']+st['price_diff']} | {st['q']} "
                  f"| {st['match']} | {st['missing']} | {st['extra']} | {st['price_diff']} |")
        for _, name in CHANNEL_MAP:
            st = stats[name]
            total = st["match"] + st["missing"] + st["extra"] + st["price_diff"]
            bad = st["missing"] + st["extra"] + st["price_diff"]
            check(f"[{name}] {total} 用例 (≥100000) 全部通过", bad == 0 and total >= 100000,
                  f"bad={bad}")
        if diffs:
            with open(HERE / "pricing_regression" / "mismatches_rules.csv", "w") as f:
                f.write("idx,L,W,H,F,channel,excel,engine,cat\n")
                for d in diffs:
                    f.write(",".join(map(str, d)) + "\n")

        print("\n== C. 引擎健壮性: 扰动规则不崩 ==")
        import random
        rng = random.Random(7)
        probe = [{"L": 50, "W": 30, "H": 20, "F": 3.5, "purchase": 88},
                 {"L": 130, "W": 90, "H": 70, "F": 15, "purchase": 200},
                 {"L": 300, "W": 120, "H": 90, "F": 28, "purchase": 500}]
        fuzz_code = (
            "const fs=require('fs');globalThis.window=globalThis;"
            "eval(fs.readFileSync('%s','utf8'));const E=window.PricingToolEngine;"
            "const D=E.DEFAULT_CHANNEL_RULES;const rngSeed=%d;"
            "let s=rngSeed;const rnd=()=>{s=(s*1103515245+12345)%%2147483648;return s/2147483648;};"
            "function mut(r){r=JSON.parse(JSON.stringify(r));"
            "  for(let i=0;i<3;i++){const path=['limits','charge_weight','pricing','surcharges','round_total'][Math.floor(rnd()*5)];"
            "  const roll=rnd();if(roll<0.3&&r[path]!==undefined)delete r[path];"
            "  else if(roll<0.6&&r[path]!==undefined)r[path]=null;"
            "  else if(roll<0.8&&r[path]!==undefined)r[path]=rnd()<0.5?{}:[];}"
            "  return r;}"
            "let calls=0,probes=JSON.parse(fs.readFileSync('/dev/stdin','utf8'));"
            "for(let i=0;i<2000;i++){const rules=D.map(mut);"
            "  for(const p of probes){const out=E.calculate(p.L,p.W,p.H,p.F,p.purchase,1.0,null,null,rules);"
            "    if(!out||!Array.isArray(out.freights))throw new Error('bad shape at '+i);calls++;}}"
            "console.log('fuzz ok calls='+calls);"
        ) % (ROOT / "server/static/js/pricing_tool.js", 7)
        cp = subprocess.run(["node", "-e", fuzz_code], input=json.dumps(probe),
                            capture_output=True, text=True)
        check("2000 组随机扰动规则 × 3 探针 无异常且结构合法", cp.returncode == 0,
              cp.stderr.strip()[:200])
        if cp.returncode == 0:
            print(" ", cp.stdout.strip())

        print("\n== D. 清除回退 ==")
        post_rules(None)
        out = node_calc(None, samples[:50], "dflt")
        check("null 规则 → 引擎走内置默认可计算", len(out) == 50)
    finally:
        post_rules(snap)

    print(f"\n========== 结果: PASS {len(PASS)} / FAIL {len(FAIL)} ==========")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)
    print("=== PASS: 快递费用配置模块全项通过 (每渠道≥10w, 一次通过) ===")


if __name__ == "__main__":
    main()
