/**
 * ============================================================================
 * 独立运费/售价试算工具 (Pricing Tool) — 配置驱动版
 * ============================================================================
 * 与商品录入页共用同一套计费引擎与费率规则:
 *   - DEFAULT_CHANNEL_RULES: 10 大渠道计费标准 (通用维度模型, 可在系统管理页配置修改)
 *   - PricingToolEngine.calculate(): 通用计费解释器, 按规则配置逐字段驱动:
 *       可用性判定(limits) → 计费重(charge_weight.bands) → 基础运费(pricing.tiers)
 *       → 附加费组(surcharges) → 整单折扣(discount) → 总价取整(round_total)
 *   - PricingTool: 自包含弹框 UI, 任意页面引入本文件后调用 PricingTool.open() 即可用
 *   - 计费标准文字由 describeChannel(配置) 自动生成, 与引擎同源, 无需手工同步
 *
 * 依赖: 无 (原生 JS, 样式自带 scoped 前缀 pt-)
 * ============================================================================
 */
(function () {
  "use strict";

  // ==========================================================================
  // 内置默认渠道规则 (数值与原硬编码引擎逐字一致; 数据库 channel_rules 为空时使用)
  // 字段说明:
  //   limits.max_*          可用性上限 (null=不限); max_cw 作用于计费重
  //   limits.reject_both_over  中边与最小边同时超限拒收 (顺丰大件)
  //   charge_weight.vol_ratio  体积重除数 (null=不计体积重)
  //   charge_weight.round_to   计费重进位: 0.5 / 1 / 0.001 / null(不进位)
  //   charge_weight.bands      按三边和分段选计费重模式, cmp: lte(默认)/lt
  //       mode: actual | max_actual_vol | avg_actual_vol | max_actual_avg
  //             | cond_vol_cap (ref_vol_ratio/cap/if_true/if_false, 初岛黑猫)
  //   pricing.type          tiered_step(阶梯首续) | first_continue(首重+续重)
  //   pricing.step_unit     档内递增单位kg: n = ceil(计费重/step_unit)
  //   pricing.tiers         命中第一个满足比较的档: step型 base+(n-1)*step;
  //                         rate型 cw*rate (min_charge=该档最低计费重, 顺丰大件首档20)
  //   pricing.op_fee        固定操作费;  pricing.discount  整单折扣乘数(0.8=打8折)
  //   surcharges            附加费组: 组内 pick add=相加 / max=取大;
  //                         item.basis sum_sides|max_side|weight, tiers 按 值>min
  //                         取最大 min 的 fee; cw_below=计费重<该值才生效
  //   round_total           总价取整: null | round2 | ceil
  // ==========================================================================
  var DEFAULT_CHANNEL_RULES = [
    {
      key: "sf_small", name: "顺丰小包", enabled: true,
      limits: { max_weight: 30, max_single_side: 120, max_sum_sides: 160, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [] },
      charge_weight: { vol_ratio: 8000, round_to: null, min_cw: null, bands: [{ max_sum: null, cmp: "lte", mode: "max_actual_vol" }] },
      pricing: {
        type: "tiered_step", step_unit: 0.5,
        tiers: [
          { max_cw: 2, cmp: "lte", base: 38, step: 8, rate: null, min_charge: null },
          { max_cw: 5, cmp: "lte", base: 40, step: 9, rate: null, min_charge: null },
          { max_cw: 10, cmp: "lte", base: 41, step: 11, rate: null, min_charge: null },
          { max_cw: null, cmp: "lte", base: 42, step: 12, rate: null, min_charge: null }
        ],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: 0.8
      },
      surcharges: [],
      round_total: "round2"
    },
    {
      key: "sf_large", name: "顺丰国际大件", enabled: true,
      limits: { max_weight: null, max_single_side: 200, max_sum_sides: null, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [{ mid: 80, min: 80 }, { mid: 70, min: 70 }] },
      charge_weight: { vol_ratio: 6000, round_to: 0.001, min_cw: null, bands: [{ max_sum: null, cmp: "lte", mode: "max_actual_vol" }] },
      pricing: {
        type: "tiered_step", step_unit: null,
        tiers: [
          { max_cw: 100, cmp: "lt", base: null, step: null, rate: 15, min_charge: 20 },
          { max_cw: 500, cmp: "lt", base: null, step: null, rate: 14, min_charge: null },
          { max_cw: 1000, cmp: "lt", base: null, step: null, rate: 13, min_charge: null }
        ],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: null
      },
      surcharges: [],
      round_total: "ceil2"
    },
    {
      key: "rc_plain", name: "日川普货", enabled: true,
      limits: { max_weight: null, max_single_side: null, max_sum_sides: 960, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [] },
      charge_weight: {
        vol_ratio: 6000, round_to: 0.5, min_cw: null,
        bands: [{ max_sum: 100, cmp: "lt", mode: "actual" }, { max_sum: null, cmp: "lte", mode: "max_actual_avg" }]
      },
      pricing: {
        type: "tiered_step", step_unit: 0.5,
        tiers: [
          { max_cw: 2, cmp: "lte", base: 32, step: 6.5, rate: null, min_charge: null },
          { max_cw: 5, cmp: "lte", base: 33, step: 7, rate: null, min_charge: null },
          { max_cw: 10, cmp: "lte", base: 34, step: 7.5, rate: null, min_charge: null },
          { max_cw: null, cmp: "lte", base: 35, step: 8, rate: null, min_charge: null }
        ],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: null
      },
      surcharges: [
        { pick: "add", items: [{ basis: "sum_sides", cw_below: null, tiers: [{ min: 159, fee: 80 }, { min: 179, fee: 100 }, { min: 200, fee: 150 }, { min: 220, fee: 200 }, { min: 239, fee: 260 }] }] },
        { pick: "add", items: [{ basis: "weight", cw_below: null, tiers: [{ min: 9.9, fee: 50 }] }] }
      ],
      round_total: "ceil"
    },
    {
      key: "rc_batt", name: "日川带电", enabled: true,
      limits: { max_weight: null, max_single_side: null, max_sum_sides: 960, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [] },
      charge_weight: {
        vol_ratio: 6000, round_to: 0.5, min_cw: null,
        bands: [{ max_sum: 100, cmp: "lt", mode: "actual" }, { max_sum: null, cmp: "lte", mode: "max_actual_avg" }]
      },
      pricing: {
        type: "tiered_step", step_unit: 0.5,
        tiers: [
          { max_cw: 2, cmp: "lte", base: 38, step: 9, rate: null, min_charge: null },
          { max_cw: 5, cmp: "lte", base: 39, step: 9.5, rate: null, min_charge: null },
          { max_cw: 10, cmp: "lte", base: 40, step: 10, rate: null, min_charge: null },
          { max_cw: null, cmp: "lte", base: 41, step: 11, rate: null, min_charge: null }
        ],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: null
      },
      surcharges: [
        { pick: "add", items: [{ basis: "sum_sides", cw_below: null, tiers: [{ min: 159, fee: 80 }, { min: 179, fee: 100 }, { min: 200, fee: 150 }, { min: 220, fee: 200 }, { min: 239, fee: 260 }] }] },
        { pick: "add", items: [{ basis: "weight", cw_below: null, tiers: [{ min: 9.9, fee: 50 }] }] }
      ],
      round_total: "ceil"
    },
    {
      key: "rc_big", name: "川日大包", enabled: true,
      limits: { max_weight: null, max_single_side: null, max_sum_sides: 960, max_length: 305, max_width: 175, max_height: 155, max_combined_girth: null, max_cw: null, max_cw_surplus_ratio: 3, reject_both_over: [] },
      charge_weight: {
        vol_ratio: 6000, round_to: 0.5, min_cw: null,
        bands: [{ max_sum: 100, cmp: "lt", mode: "actual" }, { max_sum: null, cmp: "lte", mode: "max_actual_avg" }]
      },
      pricing: {
        type: "tiered_step", step_unit: 0.5,
        tiers: [
          { max_cw: 21, cmp: "lt", base: 60, step: 18, rate: null, min_charge: null },
          { max_cw: 51, cmp: "lt", base: null, step: null, rate: 19, min_charge: null },
          { max_cw: 101, cmp: "lt", base: null, step: null, rate: 18.5, min_charge: null },
          { max_cw: 301, cmp: "lt", base: null, step: null, rate: 17.5, min_charge: null },
          { max_cw: 501, cmp: "lt", base: null, step: null, rate: 17, min_charge: null },
          { max_cw: 1000, cmp: "lt", base: null, step: null, rate: 16.5, min_charge: null },
          { max_cw: null, cmp: "lte", base: null, step: null, rate: 16, min_charge: null }
        ],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: null
      },
      surcharges: [
        { pick: "add", items: [{ basis: "max_side", cw_below: 300, tiers: [{ min: 159, fee: 200 }] }] }
      ],
      round_total: null
    },
    {
      key: "sagawa", name: "佐川大件", enabled: true,
      limits: { max_weight: null, max_single_side: 150, max_sum_sides: 250, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: 30, reject_both_over: [] },
      charge_weight: {
        vol_ratio: 6000, round_to: 0.5, min_cw: null,
        bands: [{ max_sum: 100, cmp: "lt", mode: "actual" }, { max_sum: null, cmp: "lte", mode: "max_actual_avg" }]
      },
      pricing: {
        type: "tiered_step", step_unit: 0.5,
        tiers: [{ max_cw: null, cmp: "lte", base: 40, step: 10, rate: null, min_charge: null }],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: null
      },
      surcharges: [],
      round_total: null
    },
    {
      key: "yw_small", name: "义乌小包", enabled: true,
      limits: { max_weight: null, max_single_side: 9100, max_sum_sides: 9160, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [] },
      charge_weight: {
        vol_ratio: 6000, round_to: null, min_cw: null,
        bands: [
          { max_sum: 140, cmp: "lte", mode: "actual" },
          { max_sum: 160, cmp: "lte", mode: "avg_actual_vol" },
          { max_sum: null, cmp: "lte", mode: "max_actual_vol" }
        ]
      },
      pricing: {
        type: "tiered_step", step_unit: 0.5,
        tiers: [
          { max_cw: 2, cmp: "lte", base: 34, step: 6, rate: null, min_charge: null },
          { max_cw: 5, cmp: "lte", base: 35, step: 7, rate: null, min_charge: null },
          { max_cw: null, cmp: "lte", base: 36, step: 8, rate: null, min_charge: null }
        ],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: null
      },
      surcharges: [
        { pick: "max", items: [
          { basis: "max_side", cw_below: null, tiers: [{ min: 99, fee: 35 }] },
          { basis: "sum_sides", cw_below: null, tiers: [{ min: 160, fee: 80 }, { min: 200, fee: 120 }] }
        ] }
      ],
      round_total: "ceil"
    },
    {
      key: "chudao160", name: "初岛160免泡", enabled: true,
      limits: { max_weight: null, max_single_side: 9100, max_sum_sides: 260, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [] },
      charge_weight: {
        vol_ratio: 6000, round_to: null, min_cw: null,
        bands: [{ max_sum: 160, cmp: "lte", mode: "actual" }, { max_sum: null, cmp: "lte", mode: "avg_actual_vol" }]
      },
      pricing: {
        type: "tiered_step", step_unit: 0.5,
        tiers: [
          { max_cw: 2, cmp: "lte", base: 34, step: 6, rate: null, min_charge: null },
          { max_cw: 5, cmp: "lte", base: 35, step: 7, rate: null, min_charge: null },
          { max_cw: null, cmp: "lte", base: 36, step: 8, rate: null, min_charge: null }
        ],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 20, discount: null
      },
      surcharges: [
        { pick: "add", items: [
          { basis: "sum_sides", cw_below: null, tiers: [{ min: 160, fee: 50 }, { min: 200, fee: 100 }] },
          { basis: "sum_sides", cw_below: null, tiers: [{ min: 160, fee: 30 }, { min: 200, fee: 20 }] }
        ] }
      ],
      round_total: "ceil"
    },
    {
      key: "chudao_heimao", name: "初岛黑猫", enabled: true,
      limits: { max_weight: null, max_single_side: 160, max_sum_sides: 160, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [] },
      charge_weight: {
        vol_ratio: 6000, round_to: null, min_cw: null,
        bands: [
          { max_sum: 120, cmp: "lte", mode: "actual" },
          { max_sum: 159, cmp: "lte", mode: "avg_actual_vol" }
        ]
      },
      pricing: {
        type: "tiered_step", step_unit: 0.5,
        tiers: [
          { max_cw: 2, cmp: "lte", base: 36, step: 6, rate: null, min_charge: null },
          { max_cw: 5, cmp: "lte", base: 37, step: 7, rate: null, min_charge: null },
          { max_cw: 10, cmp: "lte", base: 38, step: 8, rate: null, min_charge: null },
          { max_cw: null, cmp: "lte", base: 39, step: 10, rate: null, min_charge: null }
        ],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: null
      },
      surcharges: [],
      round_total: "ceil"
    },
    {
      key: "air_post", name: "航空邮政大包", enabled: true,
      limits: { max_weight: 30, max_single_side: 150, max_sum_sides: null, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [] },
      charge_weight: { vol_ratio: null, round_to: 1, min_cw: null, bands: [{ max_sum: null, cmp: "lte", mode: "actual" }] },
      pricing: {
        type: "first_continue", step_unit: null, tiers: [],
        first_weight_fee: 124.2, continue_per_kg: 29.6, extra_fee: 8.0, op_fee: 0, discount: null,
        girth_discount: { threshold: 330, factor_above: 1.0, factor_below: 0.9 }
      },
      surcharges: [],
      round_total: "ceil2"
    }
  ];

  // ==========================================================================
  // 通用计费解释器
  // ==========================================================================
  function num(v, dft) {
    var n = parseFloat(v);
    return isNaN(n) ? (dft || 0) : n;
  }

  function volWeight(L, W, H, ratio) {
    if (!ratio) return null;
    return Math.ceil(Math.round((L * W * H / ratio) * 1000 * 1e6) / 1e6) / 1000;
  }

  // 按 bands (第一个满足三边和条件的段) 计算计费重; 无命中段返回 null
  function computeCw(cwCfg, ctx) {
    var bands = (cwCfg && cwCfg.bands) || [];
    var volW = volWeight(ctx.L, ctx.W, ctx.H, cwCfg ? cwCfg.vol_ratio : null);
    for (var i = 0; i < bands.length; i++) {
      var b = bands[i] || {};
      if (b.max_sum !== null && b.max_sum !== undefined) {
        var hit = (b.cmp === "lt") ? (ctx.sumSides < b.max_sum) : (ctx.sumSides <= b.max_sum);
        if (!hit) continue;
      }
      var raw;
      switch (b.mode) {
        case "actual":
          raw = ctx.actWt;
          break;
        case "max_actual_vol":
          raw = Math.max(ctx.actWt, volW || 0);
          break;
        case "avg_actual_vol":
          raw = (ctx.actWt + volW) / 2;
          break;
        case "max_actual_avg":
          raw = ctx.actWt > volW ? ctx.actWt : (ctx.actWt + volW) / 2;
          break;
        case "cond_vol_cap": {
          var ref = b.ref_vol_ratio || (cwCfg ? cwCfg.vol_ratio : null);
          var volRef = volWeight(ctx.L, ctx.W, ctx.H, ref);
          var m = Math.max(ctx.actWt, volRef || 0);
          if (m <= b.cap) raw = (b.if_true === "avg") ? (ctx.actWt + volRef) / 2 : ctx.actWt;
          else raw = (b.if_false === "actual") ? ctx.actWt : (ctx.actWt + volRef) / 2;
          break;
        }
        default:
          return null;
      }
      var rt = cwCfg ? cwCfg.round_to : null;
      if (rt === 0.5) raw = Math.ceil(Math.round(raw / 0.5 * 1e6) / 1e6) * 0.5;
      else if (rt === 1) raw = Math.ceil(Math.round(raw * 1e6) / 1e6);
      else if (rt === 0.001) raw = Math.ceil(Math.round(raw * 1000 * 1e6) / 1e6) / 1000;
      else if (rt) raw = Math.ceil(Math.round(raw / rt * 1e6) / 1e6) * rt;
      if (cwCfg && cwCfg.min_cw !== null && cwCfg.min_cw !== undefined && raw < cwCfg.min_cw) {
        raw = cwCfg.min_cw;
      }
      return raw;
    }
    return null;
  }

  function isAvailable(rule, cw, ctx) {
    var lim = rule.limits || {};
    function over(val, cap) { return cap !== null && cap !== undefined && val > cap; }
    if (over(ctx.actWt, lim.max_weight)) return false;
    if (over(ctx.maxSide, lim.max_single_side)) return false;
    if (over(ctx.sumSides, lim.max_sum_sides)) return false;
    if (over(ctx.L, lim.max_length)) return false;
    if (over(ctx.W, lim.max_width)) return false;
    if (over(ctx.H, lim.max_height)) return false;
    if (lim.max_combined_girth !== null && lim.max_combined_girth !== undefined &&
        ((ctx.sumSides - ctx.maxSide) * 2 + ctx.maxSide) > lim.max_combined_girth) return false;
    if (cw === null) return false; // 计费重无法计算 → 不可用 (分段未命中)
    if (over(cw, lim.max_cw)) return false;
    if (lim.max_cw_surplus_ratio !== null && lim.max_cw_surplus_ratio !== undefined &&
        cw > ctx.actWt * lim.max_cw_surplus_ratio) return false; // 超3倍泡单询
    var rbo = lim.reject_both_over || [];
    for (var i = 0; i < rbo.length; i++) {
      var g = rbo[i] || {};
      if (ctx.midSide > g.mid && ctx.minSide > g.min) return false;
    }
    return true;
  }

  function calcSurcharges(groups, cw, ctx) {
    var total = 0;
    (Array.isArray(groups) ? groups : []).forEach(function (g) {
      if (!g || !Array.isArray(g.items) || !g.items.length) return;
      var vals = [];
      g.items.forEach(function (item) {
        if (!item) return;
        if (item.cw_below !== null && item.cw_below !== undefined && !(cw < item.cw_below)) return;
        var baseVal = item.basis === "max_side" ? ctx.maxSide : (item.basis === "weight" ? ctx.actWt : ctx.sumSides);
        var best = null;
        (Array.isArray(item.tiers) ? item.tiers : []).forEach(function (t) {
          if (!t) return;
          if (baseVal > t.min && (best === null || t.min > best.min)) best = t;
        });
        vals.push(best ? num(best.fee) : 0);
      });
      if (!vals.length) return;
      var gv;
      if (g.pick === "max") gv = Math.max.apply(null, vals);
      else gv = vals.reduce(function (a, b) { return a + b; }, 0);
      total += gv;
    });
    return total;
  }

  function calcFreight(rule, cw, ctx) {
    var p = rule.pricing || {};
    var raw;
    if (p.type === "first_continue") {
      var baseW = num(p.first_weight_fee) + (cw - 1) * num(p.continue_per_kg);
      var gd = p.girth_discount;
      if (gd && gd.threshold !== null && gd.threshold !== undefined) {
        var girth = (ctx.sumSides - ctx.maxSide) * 2 + ctx.maxSide;
        baseW = baseW * (girth > gd.threshold ? num(gd.factor_above, 1) : num(gd.factor_below, 1));
      }
      raw = baseW + num(p.extra_fee);
    } else {
      var tiers = p.tiers || [];
      var tier = null;
      for (var i = 0; i < tiers.length; i++) {
        var t = tiers[i] || {};
        var mc = t.max_cw;
        var hit = (mc === null || mc === undefined) ? true : (t.cmp === "lt" ? cw < mc : cw <= mc);
        if (hit) { tier = t; break; }
      }
      if (!tier) return null;
      if (tier.base !== null && tier.base !== undefined && tier.step !== null && tier.step !== undefined) {
        var n = p.step_unit ? Math.ceil(Math.round(cw / p.step_unit * 1e6) / 1e6) : 1;
        raw = tier.base + (n - 1) * tier.step;
      } else if (tier.rate !== null && tier.rate !== undefined) {
        var w = (tier.min_charge !== null && tier.min_charge !== undefined && cw < tier.min_charge) ? tier.min_charge : cw;
        raw = w * tier.rate;
      } else {
        return null;
      }
    }
    raw += num(p.op_fee);
    raw += calcSurcharges(rule.surcharges, cw, ctx);
    var disc = (p.discount === null || p.discount === undefined) ? 1 : num(p.discount, 1);
    if (disc !== 1) raw = raw * disc;
    if (rule.round_total === "round2") raw = Math.round(raw * 100) / 100;
    else if (rule.round_total === "ceil2") raw = Math.ceil(Math.round(raw * 100 * 1e6) / 1e6) / 100; // Excel ROUNDUP(x,2)
    else if (rule.round_total === "ceil") raw = Math.ceil(raw);
    return raw;
  }

  function normalizeRules(channelRules) {
    if (Array.isArray(channelRules) && channelRules.length) return channelRules;
    if (channelRules && Array.isArray(channelRules.channels) && channelRules.channels.length) return channelRules.channels;
    return DEFAULT_CHANNEL_RULES;
  }

  function calculate(length, width, height, weight, purchasePrice, profitCoeff, chosenChannel, pricingConfig, channelRules) {
    var L = parseFloat(length) || 0;
    var W = parseFloat(width) || 0;
    var H = parseFloat(height) || 0;
    var actWt = parseFloat(weight) || 0;
    var cost = parseFloat(purchasePrice) || 0;
    var coeff = parseFloat(profitCoeff) || 1.0;
    var pCoeff = (pricingConfig && pricingConfig.price_coefficient) ? parseFloat(pricingConfig.price_coefficient) : 26.0;
    var rules = normalizeRules(channelRules);

    var sumSides = L + W + H;
    var maxSide = sumSides > 0 ? Math.max(L, W, H) : 0;
    var minSide = sumSides > 0 ? Math.min(L, W, H) : 0;
    var midSide = sumSides - maxSide - minSide;

    // 如果尺寸或重量未录入完整
    if (L <= 0 || W <= 0 || H <= 0 || actWt <= 0) {
      return {
        hasValidPricing: false,
        optimalChannel: "",
        optimalFreight: 0,
        selectedChannel: "",
        selectedFreight: 0,
        priceJpy: cost > 0 ? Math.round(cost * (1 + coeff) * pCoeff) : "",
        freights: [],
        vol6000: 0,
        vol8000: 0,
        chargeWeights: {}
      };
    }

    var vol6000 = Math.ceil((L * W * H / 6000) * 1000) / 1000;
    var vol8000 = Math.ceil((L * W * H / 8000) * 1000) / 1000;
    var ctx = { L: L, W: W, H: H, actWt: actWt, sumSides: sumSides, maxSide: maxSide, minSide: minSide, midSide: midSide };

    var freights = [];
    var chargeWeights = {};

    rules.forEach(function (rule) {
      if (!rule || rule.enabled === false) return;
      var cwCfg = rule.charge_weight || {};
      var cw = computeCw(cwCfg, ctx);
      if (cw !== null) chargeWeights[rule.name] = cw;
      if (!isAvailable(rule, cw, ctx)) return;
      var freight = calcFreight(rule, cw, ctx);
      if (freight === null) return;
      freights.push({ channel: rule.name, cost: freight, cw: cw });
    });

    // 按照价格从小到大排序所有可用渠道 (稳定排序, 同价保持配置顺序)
    freights.sort(function (a, b) { return a.cost - b.cost; });

    var optimalChannel = "";
    var optimalFreight = 0;
    if (freights.length > 0) {
      optimalChannel = freights[0].channel;
      optimalFreight = freights[0].cost;
    }

    // 默认使用最优快递；若用户手工选择了其他渠道且存在，则使用所选渠道
    var selectedChannel = optimalChannel;
    var selectedFreight = optimalFreight;
    if (chosenChannel) {
      var matched = freights.find(function (f) { return f.channel === chosenChannel; });
      if (matched) {
        selectedChannel = matched.channel;
        selectedFreight = matched.cost;
      }
    }

    var totalCost = cost + selectedFreight;
    var plannedProfit = totalCost * coeff;
    var priceJpy = Math.round((totalCost + plannedProfit) * pCoeff);

    return {
      hasValidPricing: true,
      optimalChannel: optimalChannel,
      optimalFreight: optimalFreight,
      selectedChannel: selectedChannel,
      selectedFreight: selectedFreight,
      priceJpy: priceJpy > 0 ? priceJpy : 0,
      freights: freights,
      vol6000: vol6000,
      vol8000: vol8000,
      chargeWeights: chargeWeights
    };
  }

  // ==========================================================================
  // 计费标准文字自动生成 (describeChannel: 配置 → 摘要, 供试算工具/系统管理页展示)
  // ==========================================================================
  function fmtN(v, unit, tail) {
    if (v === null || v === undefined || v === "") return "";
    return v + (unit || "") + (tail || "");
  }

  function describeLimits(lim) {
    var parts = [];
    if (lim.max_weight !== null && lim.max_weight !== undefined) parts.push("实重≤" + lim.max_weight + "kg");
    if (lim.max_cw !== null && lim.max_cw !== undefined) parts.push("计费重≤" + lim.max_cw + "kg");
    if (lim.max_single_side !== null && lim.max_single_side !== undefined) parts.push("最长边≤" + lim.max_single_side + "cm");
    if (lim.max_sum_sides !== null && lim.max_sum_sides !== undefined) parts.push("三边和≤" + lim.max_sum_sides + "cm");
    if (lim.max_length !== null && lim.max_length !== undefined) parts.push("长≤" + lim.max_length + "cm");
    if (lim.max_width !== null && lim.max_width !== undefined) parts.push("宽≤" + lim.max_width + "cm");
    if (lim.max_height !== null && lim.max_height !== undefined) parts.push("高≤" + lim.max_height + "cm");
    if (lim.max_combined_girth !== null && lim.max_combined_girth !== undefined) parts.push("长+2×(宽+高)≤" + lim.max_combined_girth + "cm");
    (lim.reject_both_over || []).forEach(function (g) {
      if (g && g.mid !== undefined) parts.push("不收:中边与最小边同时>" + g.mid + "/" + g.min + "cm");
    });
    return parts.length ? parts.join("，") : "无收货限制";
  }

  var MODE_TEXT = {
    actual: "按实重",
    max_actual_vol: "取实重/体积重较大者",
    avg_actual_vol: "取实重与体积重均值",
    max_actual_avg: "取实重与均值较大者"
  };

  function describeCw(cwCfg) {
    var bands = (cwCfg && cwCfg.bands) || [];
    if (!bands.length) return "计费重: 未配置";
    var volTxt = cwCfg.vol_ratio ? ("体积重÷" + cwCfg.vol_ratio) : "";
    function bandText(b) {
      if (!b) return "";
      var prefix = (b.max_sum !== null && b.max_sum !== undefined) ? ("三边和" + (b.cmp === "lt" ? "<" : "≤") + b.max_sum + " ") : "";
      var t;
      if (b.mode === "cond_vol_cap") {
        t = "max(实重,÷" + (b.ref_vol_ratio || cwCfg.vol_ratio) + ")≤" + b.cap + "kg 按实重，否则取均值";
      } else if (b.mode === "max_actual_vol") {
        t = volTxt ? ("max(实重, " + volTxt + ")") : "按实重";
      } else if (b.mode === "avg_actual_vol") {
        t = volTxt ? ("(实重+" + volTxt + ")÷2") : "按实重";
      } else if (b.mode === "max_actual_avg") {
        t = volTxt ? ("实重>" + volTxt + "时取实重，否则取均值") : "按实重";
      } else {
        t = MODE_TEXT[b.mode] || b.mode;
      }
      return prefix + t;
    }
    var txt = "计费重: " + bands.map(bandText).join("；");
    if (cwCfg.round_to === 0.5) txt += "，0.5kg进位";
    else if (cwCfg.round_to === 1) txt += "，向上取整kg";
    else if (cwCfg.round_to === 0.001) txt += "，向上保留3位小数";
    if (cwCfg.min_cw !== null && cwCfg.min_cw !== undefined) txt += "，最低计费" + cwCfg.min_cw + "kg";
    return txt;
  }

  function describePricing(p) {
    var parts = [];
    if (p.type === "first_continue") {
      parts.push("首重" + p.first_weight_fee + "元(1kg起) + 续重" + p.continue_per_kg + "元/kg" + (p.extra_fee ? (" + 操作费" + p.extra_fee + "元") : ""));
    } else {
      var su = p.step_unit ? ("/" + p.step_unit + "kg") : "";
      (p.tiers || []).forEach(function (t) {
        if (!t) return;
        var head;
        if (t.max_cw === null || t.max_cw === undefined) head = "其他";
        else head = (t.cmp === "lt" ? "<" : "≤") + t.max_cw + "kg";
        if (t.base !== null && t.base !== undefined && t.step !== null && t.step !== undefined) {
          parts.push(head + " 首" + t.base + "+" + t.step + su);
        } else if (t.rate !== null && t.rate !== undefined) {
          parts.push(head + " " + t.rate + "元/kg" + (t.min_charge !== null && t.min_charge !== undefined ? ("(最低按" + t.min_charge + "kg)") : ""));
        }
      });
    }
    if (p.op_fee) parts.push("操作费" + p.op_fee + "元");
    if (p.discount !== null && p.discount !== undefined && p.discount !== 1) {
      parts.push("整单打" + Math.round(p.discount * 100) / 10 + "折");
    }
    return parts.join("；");
  }

  var BASIS_TEXT = { sum_sides: "三边和", max_side: "最长边", weight: "实重" };

  function describeSurcharges(groups) {
    if (!groups || !groups.length) return "";
    var gTexts = groups.map(function (g) {
      var iT = (g.items || []).map(function (item) {
        if (!item) return "";
        var cond = (item.cw_below !== null && item.cw_below !== undefined) ? ("(计费重<" + item.cw_below + "kg)") : "";
        var tiers = (item.tiers || []).map(function (t) { return ">" + t.min + "加" + t.fee; }).join("、");
        return (BASIS_TEXT[item.basis] || item.basis) + tiers + cond;
      }).filter(function (s) { return s; }).join(" + ");
      return g.pick === "max" ? ("max(" + iT + ")") : iT;
    });
    return "附加费: " + gTexts.join("；");
  }

  function describeChannel(rule) {
    if (!rule) return "";
    var parts = [describeLimits(rule.limits || {}), describeCw(rule.charge_weight || {})];
    var pTxt = describePricing(rule.pricing || {});
    if (pTxt) parts.push(pTxt);
    var sTxt = describeSurcharges(rule.surcharges);
    if (sTxt) parts.push(sTxt);
    if (rule.round_total === "round2") parts.push("运费四舍五入保留2位");
    else if (rule.round_total === "ceil") parts.push("运费向上取整");
    return parts.join("。") + "。";
  }

  window.PricingToolEngine = {
    calculate: calculate,
    describeChannel: describeChannel,
    DEFAULT_CHANNEL_RULES: DEFAULT_CHANNEL_RULES
  };

  // ==========================================================================
  // 自包含弹框 UI 组件
  // ==========================================================================
  var PricingTool = {
    _cfg: null,          // pricing_config (来自 /api/settings)
    _rules: null,        // channel_rules (来自 /api/settings, null=用内置默认)
    _injected: false,
    _chosenChannel: null // 用户手动选择的渠道

    ,

    _defaults: function () {
      return { tax_rate: 0.17, exchange_rate: 23.0, price_coefficient: 26.0, default_profit_coeff: 1.0 };
    },

    _inject: function () {
      if (this._injected) return;
      this._injected = true;

      var style = document.createElement("style");
      style.textContent = [
        "#pricingToolModal{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;}",
        "#pricingToolModal .pt-backdrop{position:absolute;inset:0;background:rgba(15,23,42,.6);backdrop-filter:blur(4px);}",
        "#pricingToolModal .pt-dialog{position:relative;background:#fff;width:92%;max-width:760px;max-height:90vh;border-radius:12px;box-shadow:0 25px 50px -12px rgba(0,0,0,.25);display:flex;flex-direction:column;overflow:hidden;animation:ptSlideIn .2s cubic-bezier(.16,1,.3,1);}",
        "@keyframes ptSlideIn{from{opacity:0;transform:translateY(20px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}",
        "#pricingToolModal .pt-header{padding:16px 24px;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;background:#f8fafc;}",
        "#pricingToolModal .pt-close{background:none;border:none;font-size:1.3rem;color:#64748b;cursor:pointer;padding:4px 8px;border-radius:6px;}",
        "#pricingToolModal .pt-close:hover{background:#e2e8f0;color:#0f172a;}",
        "#pricingToolModal .pt-body{padding:20px 24px;overflow-y:auto;flex:1;}",
        "#pricingToolModal .pt-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;}",
        "#pricingToolModal .pt-field label{display:block;font-size:.75rem;color:#64748b;font-weight:600;margin-bottom:4px;}",
        "#pricingToolModal .pt-field input{width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid #cbd5e1;border-radius:6px;font-size:.88rem;outline:none;}",
        "#pricingToolModal .pt-field input:focus{border-color:#8b5cf6;box-shadow:0 0 0 2px rgba(139,92,246,.15);}",
        "#pricingToolModal .pt-btn{width:100%;margin-top:14px;padding:10px 0;border:none;border-radius:8px;background:#8b5cf6;color:#fff;font-size:.92rem;font-weight:600;cursor:pointer;}",
        "#pricingToolModal .pt-btn:hover{background:#7c3aed;}",
        "#pricingToolModal .pt-select{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #cbd5e1;border-radius:6px;font-size:.86rem;background:#fff;}",
        "#pricingToolModal .pt-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px;}",
        "#pricingToolModal .pt-card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;}",
        "#pricingToolModal .pt-card .pt-k{font-size:.72rem;color:#64748b;margin-bottom:3px;}",
        "#pricingToolModal .pt-card .pt-v{font-size:1.02rem;font-weight:700;color:#0f172a;}",
        "#pricingToolModal .pt-card.pt-price{background:#f5f3ff;border-color:#ddd6fe;}",
        "#pricingToolModal .pt-card.pt-price .pt-v{color:#7c3aed;font-size:1.3rem;}",
        "#pricingToolModal .pt-formula{margin-top:8px;font-size:.76rem;color:#94a3b8;text-align:center;}",
        "#pricingToolModal .pt-table{width:100%;border-collapse:collapse;margin-top:14px;font-size:.84rem;}",
        "#pricingToolModal .pt-table th{background:#f1f5f9;color:#475569;padding:7px 10px;text-align:left;font-weight:600;border-bottom:1px solid #e2e8f0;}",
        "#pricingToolModal .pt-table td{padding:7px 10px;border-bottom:1px solid #f1f5f9;color:#334155;}",
        "#pricingToolModal .pt-table tr.pt-best td{background:#f5f3ff;font-weight:700;color:#6d28d9;}",
        "#pricingToolModal .pt-badge{display:inline-block;padding:1px 7px;border-radius:999px;background:#ede9fe;color:#6d28d9;font-size:.7rem;font-weight:600;}",
        "#pricingToolModal .pt-hint{margin-top:12px;padding:10px 12px;border-radius:8px;background:#fffbeb;border:1px solid #fde68a;color:#92400e;font-size:.84rem;}",
        "#pricingToolModal .pt-std{margin-top:18px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;}",
        "#pricingToolModal .pt-std>summary{padding:10px 14px;background:#f8fafc;cursor:pointer;font-size:.86rem;font-weight:600;color:#475569;user-select:none;}",
        "#pricingToolModal .pt-std>summary:hover{background:#f1f5f9;}",
        "#pricingToolModal .pt-std-body{padding:6px 14px 12px;}",
        "#pricingToolModal .pt-std-item{padding:8px 0;border-bottom:1px dashed #e2e8f0;font-size:.8rem;line-height:1.65;}",
        "#pricingToolModal .pt-std-item:last-child{border-bottom:none;}",
        "#pricingToolModal .pt-std-item .pt-std-name{font-weight:700;color:#0f172a;margin-right:8px;}",
        "#pricingToolModal .pt-std-note{padding:8px 0 0;font-size:.72rem;color:#94a3b8;}",
        "@media (max-width:720px){#pricingToolModal .pt-grid{grid-template-columns:repeat(3,1fr)}#pricingToolModal .pt-summary{grid-template-columns:repeat(2,1fr)}}"
      ].join("\n");
      document.head.appendChild(style);

      var wrap = document.createElement("div");
      wrap.id = "pricingToolModal";
      wrap.style.display = "none";
      wrap.innerHTML = [
        '<div class="pt-backdrop" onclick="PricingTool.close()"></div>',
        '<div class="pt-dialog">',
        '  <div class="pt-header">',
        '    <div style="display:flex;align-items:center;gap:10px;">',
        '      <span style="font-size:1.4rem;">🧮</span>',
        '      <div>',
        '        <h3 style="margin:0;font-size:1.1rem;color:#0f172a;font-weight:700;">运费 / 售价试算工具</h3>',
        '        <div style="font-size:.78rem;color:#64748b;margin-top:2px;">输入子 SKU 尺寸重量与采购价，按 10 大快递渠道比价并推导建议日元售价（与商品录入页共用同一套计费引擎）</div>',
        '      </div>',
        '    </div>',
        '    <button type="button" class="pt-close" onclick="PricingTool.close()">✕</button>',
        '  </div>',
        '  <div class="pt-body">',
        '    <div class="pt-grid">',
        '      <div class="pt-field"><label>长 (cm)</label><input type="number" step="any" min="0" id="ptLen" placeholder="长"></div>',
        '      <div class="pt-field"><label>宽 (cm)</label><input type="number" step="any" min="0" id="ptWid" placeholder="宽"></div>',
        '      <div class="pt-field"><label>高 (cm)</label><input type="number" step="any" min="0" id="ptHei" placeholder="高"></div>',
        '      <div class="pt-field"><label>重量 (kg)</label><input type="number" step="any" min="0" id="ptWgt" placeholder="重量"></div>',
        '      <div class="pt-field"><label>采购价 (¥)</label><input type="number" step="any" min="0" id="ptCost" placeholder="采购价"></div>',
        '      <div class="pt-field"><label>利润系数</label><input type="number" step="any" min="0" id="ptCoeff" placeholder="1.0"></div>',
        '    </div>',
        '    <button type="button" class="pt-btn" onclick="PricingTool.calc()">🧮 立即试算</button>',
        '    <div id="ptResultArea" style="margin-top:16px;"></div>',
        '    <details class="pt-std">',
        '      <summary>📋 各快递公司计费标准（10 大渠道）</summary>',
        '      <div class="pt-std-body">',
        '        <div id="ptStdList"></div>',
        '        <div class="pt-std-note">※ 以上标准由当前生效的渠道计费配置自动生成，可在「系统管理 → 🚚 物流渠道」中配置修改。</div>',
        '      </div>',
        '    </details>',
        '  </div>',
        '</div>'
      ].join("");
      document.body.appendChild(wrap);

      // 渠道下拉切换 → 按所选渠道重算
      document.getElementById("ptResultArea").addEventListener("change", function (e) {
        if (e.target && e.target.id === "ptChannelSelect") {
          PricingTool._chosenChannel = e.target.value || null;
          PricingTool.calc();
        }
      });

      // ESC 关闭
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") PricingTool.close();
      });
    },

    _renderStandards: function () {
      var el = document.getElementById("ptStdList");
      if (!el) return;
      var rules = this._rules || window.PricingToolEngine.DEFAULT_CHANNEL_RULES;
      el.innerHTML = rules.map(function (r) {
        if (!r) return "";
        var desc = window.PricingToolEngine.describeChannel(r);
        var nameTxt = r.enabled === false ? (r.name + "（已停用）") : r.name;
        return '<div class="pt-std-item"><span class="pt-std-name">' + nameTxt + '</span><span style="color:#475569;">' + desc + "</span></div>";
      }).join("");
    },

    _loadConfig: function () {
      var self = this;
      var fallback = this._defaults();
      if (!window.fetch) { self._cfg = fallback; self._rules = null; return Promise.resolve(); }
      return fetch("/api/settings").then(function (r) { return r.json(); }).then(function (result) {
        if (result && result.code === 0 && result.data && result.data.pricing_config) {
          self._cfg = Object.assign(fallback, result.data.pricing_config);
        } else {
          self._cfg = fallback;
        }
        var cr = result && result.code === 0 && result.data ? result.data.channel_rules : null;
        self._rules = (Array.isArray(cr) && cr.length) ? cr : null;
      }).catch(function () { self._cfg = fallback; self._rules = null; });
    },

    open: function () {
      this._inject();
      var self = this;
      this._loadConfig().then(function () {
        var coeffInp = document.getElementById("ptCoeff");
        if (coeffInp && !coeffInp.value && self._cfg) {
          coeffInp.value = self._cfg.default_profit_coeff || 1.0;
        }
        self._renderStandards();
        self.calc();
      });
      document.getElementById("pricingToolModal").style.display = "flex";
    },

    close: function () {
      var m = document.getElementById("pricingToolModal");
      if (m) m.style.display = "none";
    },

    _v: function (id) { return document.getElementById(id).value; },

    calc: function () {
      var area = document.getElementById("ptResultArea");
      if (!area) return;
      var res = window.PricingToolEngine.calculate(
        this._v("ptLen"), this._v("ptWid"), this._v("ptHei"),
        this._v("ptWgt"), this._v("ptCost"), this._v("ptCoeff"),
        this._chosenChannel, this._cfg, this._rules
      );
      this._render(area, res);
    },

    _render: function (area, res) {
      var pCoeff = (this._cfg && this._cfg.price_coefficient) ? this._cfg.price_coefficient : 26.0;
      var cost = parseFloat(this._v("ptCost")) || 0;
      var coeff = parseFloat(this._v("ptCoeff")) || 1.0;

      if (!res.hasValidPricing) {
        var html0 = "";
        if (res.priceJpy !== "") {
          html0 += '<div class="pt-summary"><div class="pt-card pt-price" style="grid-column:1/-1;"><div class="pt-k">建议日元售价（尺寸/重量未录全，按纯采购价估算）</div><div class="pt-v">¥ ' + res.priceJpy + ' 円</div></div></div>';
          html0 += '<div class="pt-formula">采购价 ¥' + cost + " × (1 + 利润系数 " + coeff + ") × 价格系数 " + pCoeff + " = " + res.priceJpy + " 円</div>";
        }
        html0 += '<div class="pt-hint">💡 请完整输入 <b>长、宽、高、重量</b> 后试算各快递渠道运费（缺一时无法比价）。</div>';
        area.innerHTML = html0;
        return;
      }

      if (res.freights.length === 0) {
        area.innerHTML = '<div class="pt-hint">⚠️ 当前尺寸/重量超出全部渠道的收货限制，暂无可用渠道。可展开下方「计费标准」核对限制条件。</div>';
        return;
      }

      var opt = '<option value="">— 请选择渠道 —</option>' + res.freights.map(function (f) {
        return '<option value="' + f.channel + '" ' + (f.channel === res.selectedChannel ? "selected" : "") + ">¥" + f.cost + "  " + f.channel + (f.channel === res.optimalChannel ? "（最便宜）" : "") + "</option>";
      }).join("");

      var rows = res.freights.map(function (f) {
        var cls = f.channel === res.selectedChannel ? ' class="pt-best"' : "";
        var badge = f.channel === res.optimalChannel ? ' <span class="pt-badge">最优</span>' : "";
        var tag = f.channel === res.selectedChannel && res.selectedChannel !== res.optimalChannel ? ' <span class="pt-badge" style="background:#dbeafe;color:#1d4ed8;">当前</span>' : "";
        return "<tr" + cls + "><td>" + f.channel + badge + tag + '</td><td>' + (f.cw !== null && f.cw !== undefined ? f.cw + " kg" : "-") + '</td><td>¥' + f.cost + "</td></tr>";
      }).join("");

      area.innerHTML = [
        '<div class="pt-grid" style="margin-bottom:2px;">',
        '  <div class="pt-field" style="grid-column:1/-1;"><label>快递渠道（按运费升序，可切换后实时重算）</label><select class="pt-select" id="ptChannelSelect">' + opt + "</select></div>",
        "</div>",
        '<div class="pt-summary">',
        '  <div class="pt-card"><div class="pt-k">最优渠道</div><div class="pt-v">' + res.optimalChannel + '</div><div style="font-size:.74rem;color:#64748b;margin-top:2px;">¥' + res.optimalFreight + "</div></div>",
        '  <div class="pt-card"><div class="pt-k">所选渠道运费</div><div class="pt-v">¥' + res.selectedFreight + "</div></div>",
        '  <div class="pt-card"><div class="pt-k">体积重 (÷6000 / ÷8000)</div><div class="pt-v" style="font-size:.88rem;">' + res.vol6000 + " / " + res.vol8000 + " kg</div></div>",
        '  <div class="pt-card pt-price"><div class="pt-k">建议日元售价</div><div class="pt-v">¥ ' + res.priceJpy + " 円</div></div>",
        "</div>",
        '<div class="pt-formula">( 采购价 ¥' + cost + " + 运费 ¥" + res.selectedFreight + " ) × ( 1 + 利润系数 " + coeff + " ) × 价格系数 " + pCoeff + " = " + res.priceJpy + " 円</div>",
        '<table class="pt-table"><thead><tr><th>渠道</th><th>计费重</th><th>运费 (¥)</th></tr></thead><tbody>' + rows + "</tbody></table>"
      ].join("");
    }
  };

  window.PricingTool = PricingTool;
})();
