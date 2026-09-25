// 批量调用真实前端计费引擎 (pricing_tool.js 的 PricingToolEngine) 进行回归测试
// 用法: node run_node.js samples.json js_results.json
"use strict";
const fs = require("fs");
const path = require("path");

// 模拟浏览器 window 环境
globalThis.window = globalThis;
const src = fs.readFileSync(path.join(__dirname, "../../server/static/js/pricing_tool.js"), "utf8");
eval(src);

const engine = globalThis.window.PricingToolEngine;
if (!engine) { console.error("引擎加载失败"); process.exit(1); }

const samples = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = [];

for (const s of samples) {
  const r = engine.calculate(s.L, s.W, s.H, s.F, s.purchase, 1.0, null, null, null);
  // freights 只含可用渠道: [{channel, cost, cw}]
  const fmap = {};
  for (const f of r.freights) fmap[f.channel] = { cost: f.cost, cw: f.cw };
  out.push({
    optimalChannel: r.optimalChannel,
    optimalFreight: r.optimalFreight,
    priceJpy: r.priceJpy,
    freights: fmap,
  });
}

fs.writeFileSync(process.argv[3], JSON.stringify(out));
console.log("JS 引擎完成:", out.length, "条样本");
