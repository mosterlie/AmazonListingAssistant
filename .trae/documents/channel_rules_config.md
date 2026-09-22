# 方案：物流渠道计费标准通用化 — 可配置、可修改

> 已与用户确认：① 编辑界面用**结构化表单**（每渠道一张卡片，全字段可视化编辑）；② 新配置**试算工具与录入页同时生效**，一处修改全局生效。

## Context

当前 10 大物流渠道的计费规则（限重/限尺寸/体积重系数/阶梯费率/附加费/折扣）硬编码在 `server/static/js/pricing_tool.js` 的 `PricingToolEngine.calculate` 内（上一任务从录入页迁出），调价必须改代码。目标：提炼出**通用计费维度**，规则变为配置数据（存数据库），在系统管理页提供编辑界面；试算工具与录入页自动按新配置计算；渠道展示的"计费标准"文字也由配置自动生成。

已核实：前端无任何地方调用 `/api/pricing/*`，后端 `pricing_service.py` 对前端是死代码 → 本次以**前端引擎为唯一解释器**，后端仅透传存储配置（不动 pricing_service / pricing_config.CHANNEL_RULES，控制范围）。

## 一、通用维度模型（channel_rules 配置结构）

每渠道一组同构字段，解释器按字段驱动计算：

```json
{
  "key": "sf_small", "name": "顺丰小包", "enabled": true,
  "limits": {
    "max_weight": 30,            // 实重上限kg (空=不限)
    "max_single_side": 120,      // 最长边cm
    "max_sum_sides": 160,        // 三边和cm
    "max_length": null, "max_width": null, "max_height": null,  // 单边各自上限(川日大包)
    "max_combined_girth": null,  // 长+2×(宽+高)上限(航空邮政)
    "max_cw": null,              // 计费重上限kg(川日900/佐川30)
    "reject_both_over": [{"mid":80,"min":80},{"mid":70,"min":70}]  // 中边与最小边同时超限拒收(顺丰大件)
  },
  "charge_weight": {
    "vol_ratio": 8000,           // 体积重除数(空=不计体积重)
    "round_to": null,            // 进位: 0.5 / 1 / 0.001 / null(不进位)
    "min_cw": null,              // 最低计费重(顺丰大件20)
    "bands": [                   // 按三边和分段选模式, 命中第一个满足比较的段
      {"max_sum": null, "mode": "max_actual_vol"}
      // max_sum 比较: cmp "lte"(默认, ≤) / "lt"(<); 实施时新增, 用于精确复刻
      //   日川系 band1 的 三边和<100 严格边界 (band: {"max_sum":100,"cmp":"lt","mode":"actual"})
      // mode: actual | max_actual_vol | avg_actual_vol | max_actual_avg
      //       | cond_vol_cap (附 ref_vol_ratio/cap/if_true/if_false, 初岛黑猫专用)
    ]
  },
  "pricing": {
    "type": "tiered_step",       // tiered_step | first_continue
    "step_unit": 0.5,            // 档内递增单位kg: n=ceil(cw/step_unit) (顺丰小包计费重不进位但按0.5递增)
    "tiers": [                   // 命中第一个满足比较的档; 同样支持 cmp lte/lt
                                 // (川日大包 tiers 原代码为 cw<21/<51/... 严格 <, 全部 cmp:"lt")
      {"max_cw": 2, "base": 38, "step": 8},              // step型: base+(n-1)×step
      {"max_cw": 100, "rate": 15, "min_charge": 20}      // rate型(step留空): max(cw,min_charge)×rate; min_charge=该档最低计费重(顺丰大件首档20)
    ],
    "first_weight_fee": null, "continue_per_kg": null, "extra_fee": null,  // 航空: 124.2/29.6/8
    "op_fee": 0,                 // 固定操作费(初岛160免泡=20)
    "discount": 0.8              // 整单折扣(顺丰小包0.8)
  },
  "surcharges": [                // 附加费组, 各组结果相加
    { "pick": "add",             // 组内多条件: add=相加 / max=取大(义乌)
      "items": [
        {"basis": "sum_sides",   // sum_sides | max_side | weight
         "tiers": [{"min":159,"fee":80},{"min":179,"fee":100},{"min":200,"fee":150},{"min":220,"fee":200},{"min":239,"fee":260}],
         "cw_below": null}       // 可选条件: 计费重<某值才生效(川日 max_side>159 且 cw<300 → 200)
      ]
    }
  ],
  "round_total": "round2"        // 总价取整: null | round2 | ceil
}
```

**10 渠道映射要点**（改写自现有硬编码，数值不变）：顺丰小包=vol8000+max模式+0.8折扣；顺丰国际大件=vol6000+min_cw 20+rate档+拒收规则；日川普货/带电=bands[≤100实重, 其余max(实重,均值)]+尺寸/重量附加费组；川日大包=单边各自上限+混合档(首档base/step, 其余rate)+max_side附加费(cw_below 300)；佐川=单档base/step；义乌=bands[140/160]+附加费组pick=max；初岛160免泡=bands[160实重]+op_fee 20+两个sum_sides附加item相加；初岛黑猫=cond_vol_cap(ref 6000/cap 120)；航空邮政=first_continue型+girth限制。

## 二、逐渠道公式对照表（现有硬编码 ⇔ 新模型，确保逻辑一致）

| 渠道 | 可用条件（现→新） | 计费重（现→新） | 运费公式（现→新） | 附加/取整（现→新） |
|---|---|---|---|---|
| 顺丰小包 | 实重≤30｜最长边≤120｜三边和≤160 → limits 三字段 | max(实重, ÷8000体积重)，**不进位** → vol_ratio 8000, round_to null, bands[max_actual_vol] | ceil(cw/0.5) 档进：≤2首38+8/≤5首40+9/≤10首41+11/其余42+12，**×0.8** → tiers[step型] + step_unit 0.5 + discount 0.8 | 无附加｜round(base×0.8, 2) → round_total round2 |
| 顺丰国际大件 | 最长边≤200｜拒收(中>80且小>80)或(中>70且小>70) → max_single_side + reject_both_over[2组] | max(实重, ÷6000体积重)，向上保留3位小数，**最低按20kg计费** → round_to 0.001 + 首档 tier.min_charge 20 | <100kg 15元/kg｜≤500 14｜≤1000 13 → tiers[rate型] | 无附加｜不取整 → round_total null |
| 日川普货 | 实重≤20｜三边和≤960 → limits | 三边和<100按实重；否则 **max(实重,(实重+÷6000体积重)/2)**，进位0.5 → bands[actual→max_actual_avg], round_to 0.5 | ≤2首32+6.5/≤5首33+7/≤10首34+7.5/其余35+8（每0.5kg） → tiers[step型] | 尺寸阶梯(159→80/179→100/200→150/220→200/239→260) + 实重>9.9加50，两组**相加** → surcharges[add+add]｜不取整 |
| 日川带电 | 同日川普货 → 同上 | 同日川普货 | ≤2首35+7/≤5首36+7.5/≤10首36+8/其余37+8.5 → tiers[step型] | 同日川普货附加 |
| 川日大包 | 计费重≤900｜长≤305｜宽≤175｜高≤155 → max_cw + max_length/width/height | 同日川系 bands + 进位0.5 | <21kg 首60+18/0.5kg；<51 19元/kg；<101 18.5；<301 17.5；<501 17；其余16.5 → tiers 混合档[首档base/step，其余rate] | 最长边>159且计费重<300加200 → item[basis:max_side, cw_below:300]｜round2 |
| 佐川大件 | 计费重≤30｜三边和≤250｜最长边≤150 → limits | 同日川系 bands + 进位0.5 | 首40+10/0.5kg → tiers[{null,40,10}] | 无附加｜不取整 |
| 义乌小包 | 实重≤20｜最长边≤9100｜三边和≤9160 → limits（9100/9160 等价于不限，照抄保证等价） | 三边和≤140实重；≤160取均值；否则取大者，**不进位** → bands[actual→avg→max_actual_vol], round_to null | ≤2首34+6/≤5首35+7/其余36+8 → tiers[step型] | max(最长边>99→35，三边和>160→80/>200→120) → 1组 **pick:max**｜总价**向上取整** → round_total ceil |
| 初岛160免泡 | 实重≤20｜三边和≤260 → limits | 三边和≤160实重，否则取均值，不进位 → bands[actual→avg] | ≤2首34+6/≤5首35+7/其余36+8 + **操作费20** → tiers + op_fee 20 | 两组三边和阶梯(50/100 与 30/20)相加 → surcharges[add]｜ceil |
| 初岛黑猫 | 实重≤20｜最长边≤160｜三边和≤**159**（代码中 cwHeimao 判定 159，与可用性 160 取交集）→ max_sum_sides 159 | 若 max(实重,÷6000体积重)≤120 按实重，否则取均值 → bands[cond_vol_cap: ref 6000/cap 120] | ≤2首36+6/≤5首37+7/≤10首38+8/其余39+10 → tiers[step型] | 无附加｜ceil |
| 航空邮政大包 | 实重≤30｜最长边≤150｜长+2×(宽+高)≤330 → limits 含 max_combined_girth | 不计体积重，实重向上取整1kg → vol_ratio null, round_to 1, mode actual | 首重124.2(1kg起) + 续重29.6/kg + 操作费8 → pricing first_continue 型 | 无附加｜round2 |

**等价性证明要点**：
- `max_actual_avg` 模式 ≡ 现逻辑 `actWt > vol6000 ? actWt : (actWt+vol6000)/2`：act>vol 时 avg<act → max=act；act≤vol 时 avg≥act → max=avg，逐分支等价 ✓
- `cond_vol_cap` ≡ 现逻辑 `cwSfLarge≤120 ? actWt : avg`（cwSfLarge = ceil(max(act,vol6000)×1000)/1000）✓
- tiers 命中规则 = 现代码 if/else if 链（第一个 max_cw≥cw 的档）✓；附加费 tiers = 现 `sumSides>239?260:(>220?200:…)` 嵌套三元（取满足的最大 min）✓
- 售价公式**完全不变**：`priceJpy = round((采购价+所选渠道运费)×(1+利润系数)×价格系数)`，与 pricing_trial_tool.md 文档一致 ✓
- 对照中发现并已补入模型的 2 个缺口：①`pricing.step_unit`（顺丰小包计费重不进位，但档内按 0.5kg 递增，原 schema 把两者混为一谈）；②tier.`min_charge`（顺丰大件最低按 20kg 计费，只作用于首档）

## 三、实施步骤

### 1. `server/static/js/pricing_tool.js`（核心重构）
- 新增 `DEFAULT_CHANNEL_RULES`（按上节映射逐字转写现有数值，作为内置默认）
- `PricingToolEngine.calculate(..., pricingConfig, channelRules)` 重写为**通用解释器**：可用性判定 → 按 bands 算计费重 → 按 pricing.type/tiers 算基础运费 → 累加附加费组 → ×discount → 按 round_total 取整；`channelRules` 为空时回退 `DEFAULT_CHANNEL_RULES`；返回结构不变（freights/optimalChannel/priceJpy/vol6000/vol8000…），另附每个渠道的计费重明细
- `CHANNEL_STANDARDS` 静态文字替换为 `describeChannel(cfg)` 由配置自动生成摘要（限重/尺寸/计费重模式/费率档），折叠面板从当前生效配置渲染
- `PricingTool._loadConfig` 额外读取 `/api/settings` 的 `data.channel_rules`（合并覆盖默认）
- 删除旧硬编码计算体

### 2. `server/static/js/app.js`（录入页联动）
- `state` 增加 `channelRules: null`；`loadSystemSettings` 读取 `result.data.channel_rules`
- `calculateSkuPricingClient` 委托改为传 `(…, state.pricingConfig, state.channelRules)`

### 3. `server/routers/settings_router.py`（后端透传）
- `SystemSettingsSchema` 增加 `channel_rules: Optional[Dict[str, Any]] = None`
- GET `/api/settings`：`data` 增加 `channel_rules = get_setting("channel_rules", None)`
- POST（已含 `require_admin_user` 管理员校验）：`channel_rules` 非空时 `set_setting("channel_rules", payload.channel_rules)`，响应回带

### 4. `server/templates/settings.html`（新面板）
- 顶部胶囊导航加 `<button data-tab="channels">🚚 物流渠道</button>`（放在「💰 计价参数」后）
- 新增 `<div class="settings-panel" data-panel="channels">`：渠道卡片列表容器 + 顶部「💾 保存渠道计费标准」「↩️ 恢复默认」按钮与说明文字

### 5. `server/static/js/settings.js`（编辑器逻辑）
- 渲染：每渠道一张折叠卡片（名称+启用开关；展开显示表单）——限制 8 个数字输入（空=不限）+ 拒收规则两行；计费重（体积比/进位下拉/最低计费重 + bands 动态行：三边和上限+模式下拉，选中 cond_vol_cap 时展开 ref/cap/if_true/if_false 字段）；价格（类型下拉 → tiered_step 显示 tiers 动态表格[计费重上限/首费/步长/单价]，first_continue 显示 3 个数字框；操作费/折扣/总价取整下拉）；附加费（组动态编辑：pick 下拉 + item 行[basis 下拉 + min/fee 行 + cw_below]）
- 收集校验：`collectChannelRules()` 组装 JSON（数字空串转 null），保存时并入现有 POST `/api/settings` payload
- 「恢复默认」：`set_setting` 置空（提交 `channel_rules: null`），前端回退内置默认并重渲染
- `settings.html` 引用版本号升为 `?v=20260922_channels`

## 四、验证

1. **基线采集（改码前）**：CDP 在 9222 Chrome 对现引擎跑 ~10 组样本（覆盖每渠道命中/超限：30×20×10/1.2、40×30×20/3、50×40×30/8、60×50×40/15、100×60×40/25、80×70×60/12、120×80×50/5、200×100×80/10、310×180×160/100、缺尺寸边界），保存各渠道运费与售价 JSON
2. **等价回归（改码后）**：默认配置下同样本输出与基线**逐渠道逐值完全一致**（试算工具 + 录入页 `calculateSkuPricingClient` 双端）
3. **配置闭环**：系统管理页改「顺丰小包」折扣 0.8→0.9 保存 → 重开试算工具该渠道运费按 0.9 重算；改回 0.8 恢复一致
4. **禁用/恢复**：停用某渠道后其不出现在比价结果；「恢复默认」后回到基线值
5. **权限**：非管理员保存返回 401/403，仅查看正常

## 范围外（不做）
- 后端 `pricing_service.py` / `pricing_config.CHANNEL_RULES` 不改动（前端已不调用，避免双解释器；后续可另行清理）
- 桌面版不重新打包（无桌面端改动）
