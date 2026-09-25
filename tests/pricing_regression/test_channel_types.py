"""
测试1: 系统试算(后端) / 商品子SKU(前端) / Excel 三方「快递渠道类型」一致性
  - 静态: 三方渠道名称清单 (数量/名称/顺序) 必须完全一致
  - 动态: 10w 随机样本, 逐样本「可报价渠道集合」三方必须完全一致
用法: python3 test_channel_types.py [样本数, 默认100000] [--seed N]
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, HERE)

from server.services.pricing_service import PricingService            # noqa: E402
from excel_standard import excel_standard, CHANNEL_MAP, quotable      # noqa: E402
from run_regression import gen_samples                                # noqa: E402


def frontend_channel_names() -> list:
    """从 pricing_tool.js 导出的 DEFAULT_CHANNEL_RULES 提取渠道名 (Node 真实运行)"""
    code = (
        "const fs=require('fs');globalThis.window=globalThis;"
        "eval(fs.readFileSync('%s','utf8'));"
        "console.log(JSON.stringify(window.PricingToolEngine.DEFAULT_CHANNEL_RULES.map(r=>r.name)));"
    ) % (ROOT / "server/static/js/pricing_tool.js")
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip())


def main():
    n = 100000
    seed = 888123
    args = sys.argv[1:]
    if args and args[0].isdigit():
        n = int(args[0])
    if "--seed" in args:
        seed = int(args[args.index("--seed") + 1])

    fails = []

    # ---------------- 1. 静态: 渠道名称清单一致性 ----------------
    excel_names = [name for _, name in CHANNEL_MAP]
    py = PricingService.calculate_sku_pricing(20, 20, 20, 1.0, 50.0)
    py_names = [f["channel"] for f in py["freights"]]
    js_names = frontend_channel_names()
    print("Excel 渠道清单 :", excel_names)
    print("后端试算渠道   :", py_names)
    print("前端子SKU渠道  :", js_names)
    if py_names != excel_names:
        fails.append(f"后端渠道清单与Excel不一致: {py_names}")
    if js_names != excel_names:
        fails.append(f"前端渠道清单与Excel不一致: {js_names}")
    print(f"[静态] 渠道数量: Excel={len(excel_names)} 后端={len(py_names)} 前端={len(js_names)}")

    # ---------------- 2. 动态: 10w 样本逐样本可报价集合一致性 ----------------
    samples = gen_samples(seed=seed, random_only=True, n_random=n)
    print(f"动态样本: {len(samples)} (纯随机 seed={seed})")
    (HERE / "samples.json").write_text(json.dumps(samples))
    subprocess.run(["node", str(HERE / "run_node.js"),
                    str(HERE / "samples.json"), str(HERE / "js_results.json")],
                   check=True, cwd=HERE)
    js_results = json.loads((HERE / "js_results.json").read_text())

    set_mismatch = {"py": 0, "js": 0}
    examples = {"py": [], "js": []}
    chan_missing = {"py": {}, "js": {}}       # Excel有 系统无
    chan_extra = {"py": {}, "js": {}}         # Excel无 系统有

    for idx, (s, jr) in enumerate(zip(samples, js_results)):
        ex = excel_standard(s["L"], s["W"], s["H"], s["F"], s["purchase"])
        excel_set = {name for _, name in CHANNEL_MAP if quotable(ex["channels"][name])}
        pr = PricingService.calculate_sku_pricing(s["L"], s["W"], s["H"], s["F"], s["purchase"])
        py_set = {f["channel"] for f in pr["freights"] if f.get("status") == "可用" and f.get("cost") is not None}
        js_set = set(jr["freights"].keys())
        for tag, s_set in (("py", py_set), ("js", js_set)):
            if s_set != excel_set:
                set_mismatch[tag] += 1
                if len(examples[tag]) < 5:
                    examples[tag].append((idx, s, sorted(excel_set - s_set), sorted(s_set - excel_set)))
                for c in excel_set - s_set:
                    chan_missing[tag][c] = chan_missing[tag].get(c, 0) + 1
                for c in s_set - excel_set:
                    chan_extra[tag][c] = chan_extra[tag].get(c, 0) + 1

    print(f"\n[动态] 可报价渠道集合不一致样本数: 后端B={set_mismatch['py']}  前端A={set_mismatch['js']} / {len(samples)}")
    if chan_missing["py"] or chan_extra["py"]:
        print(f"  后端 渠道缺失分布: {chan_missing['py']}  多报分布: {chan_extra['py']}")
    if chan_missing["js"] or chan_extra["js"]:
        print(f"  前端 渠道缺失分布: {chan_missing['js']}  多报分布: {chan_extra['js']}")
    for tag, label in (("py", "后端"), ("js", "前端")):
        for idx, s, miss, extra in examples[tag]:
            print(f"  [{label}] 例 #{idx}: L={s['L']} W={s['W']} H={s['H']} F={s['F']}  Excel有系统无={miss}  系统有Excel无={extra}")
        if set_mismatch[tag] == 0:
            print(f"  [{label}] PASS — 每个样本的可报价渠道集合与 Excel 完全一致")

    if set_mismatch["py"] or set_mismatch["js"] or fails:
        for f in fails:
            print("FAIL:", f)
        sys.exit(1)
    print("\n=== PASS: 渠道类型三方一致 (静态清单 + 全部样本逐样本集合) ===")


if __name__ == "__main__":
    main()
