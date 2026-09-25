// 通用 harness: 用指定 channelRules (或 null=内置默认) 跑批量样本
// 用法: node run_node_rules.js <rules.json|null> <samples.json> <out.json>
const fs = require('fs');
globalThis.window = globalThis;
eval(fs.readFileSync(__dirname + '/../server/static/js/pricing_tool.js', 'utf8'));
const E = window.PricingToolEngine;
const rulesArg = process.argv[2] === 'null' ? null : JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const samples = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = samples.map(function (s) {
  var r = E.calculate(s.L, s.W, s.H, s.F, s.purchase, 1.0, null, null, rulesArg);
  var fr = {};
  (r.freights || []).forEach(function (f) { fr[f.channel] = f.cost; });
  return { freights: fr, optimalChannel: r.optimalChannel, optimalFreight: r.optimalFreight };
});
fs.writeFileSync(process.argv[4], JSON.stringify(out));
console.log('JS 引擎完成: ' + out.length + ' 条样本 (rules=' + (rulesArg ? 'DB配置' : '内置默认') + ')');
