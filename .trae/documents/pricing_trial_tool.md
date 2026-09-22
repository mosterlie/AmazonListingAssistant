# 方案：独立运费/售价试算工具（商品管理页弹框）

## Context

商品录入页（entry.html + app.js）中已有一套「子 SKU 长宽高/重量/采购价 → 10 大快递渠道运费比价 → 日元售价自动推导」的完整逻辑，核心函数 `calculateSkuPricingClient`（app.js L621-816），但与录入页强耦合（依赖 `state.pricingConfig`），无法在别处单独使用。

用户需求：把这套逻辑和各快递公司计费标准**整理成一个独立工具**，在商品管理页（list.html）加按钮，点击弹框试算。

## 现状关键事实（已核实）

- 计算引擎：app.js `calculateSkuPricingClient(L,W,H,重量,采购价,利润系数,选渠道)` — 纯函数，唯一外部依赖是 `state.pricingConfig.price_coefficient`（默认 26.0）；10 渠道规则硬编码在函数内（顺丰小包/顺丰国际大件/日川普货/日川带电/川日大包/佐川大件/义乌小包/初岛160免泡/初岛黑猫/航空邮政大包）
- 配置来源：`/api/settings` 返回 DB 自定义 `pricing_config`（app.js L44-55 加载），含 `price_coefficient`、`default_profit_coeff`
- 后端已有一份同逻辑（`server/services/pricing_service.py` + `/api/pricing/calculate-single`），但行为略有差异（重量 0 时默认 0.1 等），**不采用**，保证工具与录入页结果完全一致
- list.html 继承 base.html；app.js 在 base.html L132 全局加载（所有页面可用）；list.html 已有成熟的 `custom-modal` 弹窗模式（L209-241 结构、L289-354 样式）
- 静态目录挂载：`app.mount("/static", StaticFiles(...))`，新增 JS 文件即生效，无需重启

## 实施步骤

### 1. 新建 `server/static/js/pricing_tool.js`（独立工具本体）

- **`window.PricingToolEngine`**（纯计算引擎）：从 app.js 原样搬出 `calculateSkuPricingClient` 与 `mathCeilStep`，签名改为显式传参 `calculate(L, W, H, weight, purchasePrice, profitCoeff, chosenChannel, pricingConfig)`，`pCoeff` 取 `pricingConfig.price_coefficient || 26.0`，不再依赖 `state`
- **`window.PricingTool`**（自包含 UI 组件）：
  - `open()/close()`：首次调用时动态注入弹窗 DOM（自带一份 scoped 的 minimal 弹窗样式，复用 `custom-modal` 视觉风格：遮罩+居中卡片+右上角✕+遮罩点击关闭）
  - 输入区：长/宽/高(cm)、重量(kg)、采购价(¥)、利润系数（默认取配置 `default_profit_coeff`，可改）
  - 交互：输入即时联动试算 + 「🧮 立即试算」按钮
  - 结果区：
    - 体积重 vol6000 / vol8000 展示
    - 渠道下拉（与录入页同款：按运费升序，最便宜标「(最便宜)」，可手动切换渠道后实时重算售价）
    - 结果卡片：最优渠道及运费、所选渠道运费、总成本、**建议日元售价**（高亮，附公式 `(采购价+运费)×(1+利润系数)×价格系数`）
    - 各渠道运费明细表（渠道/运费/是否最优标记；不满足渠道限制的不显示）
  - 折叠面板「📋 各快递公司计费标准」：静态整理 10 渠道的限重/尺寸限制/计费重规则/阶梯费率（源自现有硬编码规则，与引擎同文件维护，注明"改费率请同步改引擎"）
  - 配置加载：`open()` 时 fetch `/api/settings` 取 `pricing_config`（失败回退默认值）
  - ESC 键关闭

### 2. 改 `server/static/js/app.js`：录入页改为复用共享引擎（"整理"的核心）

- `calculateSkuPricingClient` 函数体替换为委托调用：`return PricingToolEngine.calculate(L, W, H, weight, purchasePrice, profitCoeff, chosenChannel, state.pricingConfig);`（函数名/签名/返回结构不变，`recalcRowPricing` 等所有调用点零改动）
- 删除函数内旧实现与 `mathCeilStep`（已迁至 pricing_tool.js）
- 效果：录入页与试算工具共用同一份引擎与费率，永不分叉

### 3. 改 `server/templates/base.html`

- L132 app.js 之前插入：`<script src="/static/js/pricing_tool.js?v=20260922_pt1"></script>`（必须先于 app.js 加载）
- app.js 版本号升为 `?v=20260922_pt1`（防浏览器缓存旧实现）

### 4. 改 `server/templates/list.html`

- 卡片头部按钮区（L81-85，「➕ 录入」旁）新增：
  `<button type="button" class="btn btn-outline btn-sm" onclick="PricingTool.open()">🧮 试算</button>`

## 备选方案（未采用）

- 弹框改调后端 `/api/pricing/calculate-single`：后端实现与前端存在行为差异（如重量空值处理），且切渠道重算需网络往返；为与录入页结果严格一致，选用前端共享引擎

## 验证

1. 无需重启服务（模板/静态文件即改即生效），强制刷新页面（版本号防缓存）
2. 商品管理页：点「🧮 试算」→ 弹框打开；输入 30×20×10 / 1.2kg / 采购价 50 / 利润系数 1.0 → 渠道列表出现且最便宜者标最优 → 切换渠道后建议售价实时变化 → ESC/✕/遮罩关闭正常
3. 对照回归：录入页子 SKU 行填相同长宽高/重量/采购价，行内售价与工具弹框结果一致（验证 app.js 委托改造无回归）
4. 边界：只填部分尺寸 → 提示信息合理不报错；清空采购价 → 仅售价为空不崩
5. 折叠「计费标准」面板展开可读、收起不占空间
