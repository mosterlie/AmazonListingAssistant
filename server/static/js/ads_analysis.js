/**
 * 广告分析前端交互逻辑
 * Tab1 数据导入 (三份Excel上传 + 数据关联) / Tab2 在线产品-子 (筛选+列配置+分页)
 * Tab3 在线产品-父 (父SKU聚合) / Tab4 广告研判 (广告组汇总+列配置)
 * 移植自 browser_toolkit/server/static/js/ads_analysis.js (API 前缀改为 /api/ads)
 */
"use strict";

// 网站默认进入的页签
const DEFAULT_TAB = "research";

const ADS = {
  tab: DEFAULT_TAB,
  prod: { rows: [], fields: [], defaults: [], total: 0, page: 1, pageSize: 50, sort: "", order: "desc", cols: [] },
  par: { rows: [], sortKey: "", sortDir: "" },
  // days: 默认近1天; expanded: 默认收起; marked: 是否标记筛选 (空=全部); selected: 批量勾选的广告组名
  // page/pageSize: 分页 (默认每页 20); total/markedTotal: 服务端返回的总数
  res: { rows: [], fields: [], defaults: [], cols: [], sortKey: "", sortDir: "",
         days: "1", expanded: false, marked: "", selected: new Set(),
         page: 1, pageSize: 20, total: 0, markedTotal: 0, queryKey: "" },
  // 统计结果弹窗: data=服务端结果; custom=自定义分组(仅内存); excluded=各区域已清除的重复项(仅内存)
  stat: { data: null, custom: [], excluded: {}, editKey: "", seq: 0, options: null,
          unBatch: { budget: "", bid: "" } }
};

const PROD_COL_KEY = "adsProductsCols_v2";
const RES_COL_KEY = "adsResearchCols_v10";

// 广告研判默认收缩的关联字段 (默认只展示 子ASIN, 点「子ASIN」列头的 ▸ 展开后才显示)
const RES_COLLAPSE_FIELDS = ["父ASIN", "父SKU", "变体数量", "广告产品", "活动开始日期", "活动结束日期"];

function showToast(msg, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast-msg toast-${type}`;
  toast.innerText = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fmtNum(v) {
  if (v === "" || v == null || v === "-") return "-";
  const n = Number(v);
  if (Number.isNaN(n)) return escapeHtml(v);
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

/** 价格类字段 (含"价格"、以"价"结尾、英文 Price), 展示时四舍五入只保留整数 */
function isPriceField(field) {
  return /价格|价[）)]?$|Price/.test(String(field || ""));
}

function fmtPrice(v) {
  if (v === "" || v == null || v === "-") return "-";
  const n = Number(v);
  if (Number.isNaN(n)) return escapeHtml(v);
  return Math.round(n).toLocaleString("zh-CN");
}

// ═══════════════ Tab 切换 ═══════════════
function switchTab(tab) {
  ADS.tab = tab;
  document.querySelectorAll("#adsSubnav .ads-subnav-item").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  document.querySelectorAll(".ads-panel").forEach(p => {
    p.classList.toggle("active", p.dataset.panel === tab);
  });
  if (tab === "import") loadAdsStatus();
  if (tab === "products") loadProducts();
  if (tab === "parents") loadParents();
  if (tab === "research") loadResearch();
}

// ═══════════════ Tab1 数据导入 ═══════════════
async function loadAdsStatus() {
  try {
    const res = await fetch("/api/ads-analysis/status");
    const result = await res.json();
    if (result.code !== 0) return;
    const d = result.data;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.innerText = v; };
    set("stProducts", fmtNum(d.products.count));
    set("stCampaigns", fmtNum(d.campaigns.count));
    set("stGroups", fmtNum(d.groups.count));
    set("stAutoAd", d.link && d.products.count ? fmtNum(d.link.products_with_ad) : "—");
    const linked = d.link || {};
    const stLinked = document.getElementById("stLinked");
    if (stLinked) {
      if (!linked.campaigns_total) { stLinked.innerText = "未关联"; stLinked.style.color = "#94a3b8"; }
      else if (linked.linked) { stLinked.innerText = "✅ 已关联"; stLinked.style.color = "#059669"; }
      else { stLinked.innerText = "⚠️ 待关联"; stLinked.style.color = "#d97706"; }
    }
  } catch (err) { console.error("加载导入状态失败", err); }
}

function bindUpload(fileInputId, nameSpanId, btnId, resId, apiPath) {
  const fileInput = document.getElementById(fileInputId);
  const nameSpan = document.getElementById(nameSpanId);
  const btn = document.getElementById(btnId);
  const resEl = document.getElementById(resId);
  if (!fileInput || !btn) return;
  fileInput.addEventListener("change", () => {
    nameSpan.innerText = fileInput.files.length ? fileInput.files[0].name : "选择 .xlsx 文件";
    resEl.innerText = "";
    resEl.style.color = "#16a34a";
  });
  btn.addEventListener("click", async () => {
    if (!fileInput.files.length) { showToast("请先选择 Excel 文件", "error"); return; }
    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    btn.disabled = true;
    const old = btn.innerText;
    btn.innerText = "⏳ 导入中...";
    try {
      const res = await fetch(apiPath, { method: "POST", body: fd });
      const result = await res.json();
      if (res.ok && result.code === 0) {
        resEl.style.color = "#16a34a";
        resEl.innerText = `✅ ${result.msg}`;
        showToast(result.msg, "success");
        loadAdsStatus();
      } else {
        resEl.style.color = "#dc2626";
        resEl.innerText = `❌ ${result.detail || result.msg || "导入失败"}`;
        showToast(result.detail || result.msg || "导入失败", "error");
      }
    } catch (err) {
      resEl.style.color = "#dc2626";
      resEl.innerText = `❌ 网络异常: ${err.message}`;
      showToast(`网络异常: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.innerText = old;
    }
  });
}

function bindLinkData() {
  const btn = document.getElementById("btnLinkData");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const old = btn.innerText;
    btn.innerText = "⏳ 关联中...";
    try {
      const res = await fetch("/api/ads-analysis/link", { method: "POST" });
      const result = await res.json();
      if (res.ok && result.code === 0) {
        showToast(result.msg, "success");
        const d = result.data || {};
        if (d.unmatched_asins && d.unmatched_asins.length) {
          console.warn("未匹配ASIN:", d.unmatched_asins);
        }
        loadAdsStatus();
      } else {
        showToast(result.detail || result.msg || "关联失败", "error");
      }
    } catch (err) {
      showToast(`网络异常: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.innerText = old;
    }
  });
}

function bindClearData() {
  const btn = document.getElementById("btnClearData");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    if (!confirm("确认清空所有数据？\n\n在线产品 / 广告活动 / 广告组 以及关联结果将全部删除，操作不可恢复！")) return;
    if (!confirm("再次确认：真的要清空全部已导入及已处理的数据吗？")) return;
    btn.disabled = true;
    const old = btn.innerText;
    btn.innerText = "⏳ 清空中...";
    try {
      const res = await fetch("/api/ads-analysis/clear", { method: "POST" });
      const result = await res.json();
      if (res.ok && result.code === 0) {
        // 清空前端缓存, 避免残留旧数据渲染
        ADS.prod.rows = []; ADS.prod.total = 0; ADS.prod.fields = []; ADS.prod.page = 1;
        ADS.par.rows = [];
        ADS.res.rows = []; ADS.res.fields = [];
        showToast(result.msg, "success");
        loadAdsStatus();
      } else {
        showToast(result.detail || result.msg || "清空失败", "error");
      }
    } catch (err) {
      showToast(`网络异常: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.innerText = old;
    }
  });
}

// ═══════════════ 列配置 (localStorage 持久化) ═══════════════
function loadCols(key, defaults) {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr) && arr.length) return arr;
    }
  } catch (e) { /* 忽略损坏配置 */ }
  return [...defaults];
}

function saveCols(key, cols) {
  try { localStorage.setItem(key, JSON.stringify(cols)); } catch (e) { /* 忽略 */ }
}

function buildColList(listEl, fields, cols, onChange) {
  listEl.innerHTML = "";
  if (!Array.isArray(fields) || !Array.isArray(cols)) return;
  fields.forEach(f => {
    const label = document.createElement("label");
    label.className = "ads-col-item";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = cols.includes(f);
    cb.addEventListener("change", () => {
      const set = new Set(cols);
      if (cb.checked) set.add(f); else set.delete(f);
      const next = fields.filter(x => set.has(x));
      cols.length = 0;
      next.forEach(x => cols.push(x));
      onChange();
    });
    const span = document.createElement("span");
    span.innerText = f;
    label.appendChild(cb);
    label.appendChild(span);
    listEl.appendChild(label);
  });
}

function bindColPop(btnId, popId, listId, fields, cols, key, onChange, resetDefaults) {
  const btn = document.getElementById(btnId);
  const pop = document.getElementById(popId);
  const listEl = document.getElementById(listId);
  if (!btn || !pop) return;
  const render = () => {
    const fieldList = typeof fields === "function" ? fields() : (fields || []);
    buildColList(listEl, fieldList, cols, onChange);
  };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    document.querySelectorAll(".ads-colpop").forEach(p => { if (p !== pop) p.classList.remove("open"); });
    render();
    pop.classList.toggle("open");
  });
  pop.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", () => pop.classList.remove("open"));
  const allBtn = document.getElementById(listId.replace("List", "All"));
  const resetBtn = document.getElementById(listId.replace("List", "Reset"));
  if (allBtn) allBtn.addEventListener("click", () => {
    const fieldList = typeof fields === "function" ? fields() : (fields || []);
    cols.length = 0;
    fieldList.forEach(f => cols.push(f));
    saveCols(key, cols); render(); onChange();
  });
  if (resetBtn) resetBtn.addEventListener("click", () => {
    const defList = typeof resetDefaults === "function" ? (resetDefaults() || []) : (resetDefaults || []);
    cols.length = 0;
    defList.forEach(f => cols.push(f));
    saveCols(key, cols); render(); onChange();
  });
}

// ═══════════════ Tab2 在线产品-子 ═══════════════
function ellipsisSpan(text, extraClass = "", maxWidth = 220) {
  const s = String(text == null ? "" : text);
  if (!s || s === "-") return "-";
  return `<span class="ads-ellipsis ${extraClass}" style="max-width:${maxWidth}px;" title="${escapeHtml(s)}">${escapeHtml(s)}</span>`;
}

/** 可单击复制的单元格 (子ASIN/父ASIN/父SKU/标题) */
function copyableSpan(text, extraClass = "", maxWidth = 92) {
  const s = String(text == null ? "" : text);
  if (!s || s === "-") return "-";
  return `<span class="ads-ellipsis ads-copy ${extraClass}" style="max-width:${maxWidth}px;"`
    + ` data-copy="${escapeHtml(s)}" title="单击复制：${escapeHtml(s)}">${escapeHtml(s)}</span>`;
}

function prodCell(field, row) {
  const v = row[field];
  if (field === "图片") {
    const src = escapeHtml(v || "");
    return src ? `<img class="ads-prod-img" src="${src}" loading="lazy" onerror="this.style.display='none'">` : "-";
  }
  if (field === "是否开通自动广告") {
    return v === "是" ? '<span class="ads-badge-yes">已开通</span>' : '<span class="ads-badge-no">未开通</span>';
  }
  // 标题 / MSKU 过长自动省略 (悬停显示完整内容), 列宽收窄给其他列腾位置
  if (field === "标题") return ellipsisSpan(v, "", 220);
  if (field === "MSKU") return ellipsisSpan(v, "ads-mono", 110);
  if (isPriceField(field)) return fmtPrice(v);
  const asinLike = /ASIN$/.test(field) || field === "SKU" || field === "FNSKU";
  if (asinLike && v) return `<span style="font-family:ui-monospace,monospace; font-size:0.8rem;">${escapeHtml(v)}</span>`;
  if (v === "" || v == null || v === "-") return "-";
  return escapeHtml(v);
}

async function loadProducts() {
  const p = ADS.prod;
  const autoAd = document.getElementById("prodAutoAdFilter") ? document.getElementById("prodAutoAdFilter").value : "";
  const kw = document.getElementById("prodKeyword") ? document.getElementById("prodKeyword").value.trim() : "";
  const params = new URLSearchParams({
    auto_ad: autoAd, keyword: kw, sort: p.sort, order: p.order,
    page: p.page, page_size: p.pageSize
  });
  try {
    const res = await fetch(`/api/ads-analysis/products?${params}`);
    const result = await res.json();
    if (result.code !== 0) { showToast(result.detail || "加载产品失败", "error"); return; }
    const d = result.data;
    p.fields = d.fields || [];
    p.defaults = d.defaults || [];
    p.rows = d.rows || [];
    p.total = d.total || 0;
    p.page = d.page || 1;
    if (!p.cols.length) loadCols(PROD_COL_KEY, p.defaults).forEach(x => p.cols.push(x));
    renderProdHead();
    renderProdBody();
    renderProdPager();
    const badge = document.getElementById("prodCountBadge");
    if (badge) badge.innerText = `共 ${fmtNum(p.total)} 条`;
  } catch (err) { showToast(`网络异常: ${err.message}`, "error"); }
}

function renderProdHead() {
  const p = ADS.prod;
  const cols = p.cols.filter(c => p.fields.includes(c) || c === "是否开通自动广告");
  const head = document.getElementById("prodHead");
  head.innerHTML = cols.map(c => {
    let arrow = "";
    if (p.sort === c) arrow = p.order === "asc" ? " ▲" : " ▼";
    return `<th class="sortable" data-field="${escapeHtml(c)}">${escapeHtml(c)}${arrow}</th>`;
  }).join("");
  head.querySelectorAll("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const f = th.dataset.field;
      if (ADS.prod.sort === f) {
        ADS.prod.order = ADS.prod.order === "asc" ? "desc" : "asc";
      } else {
        ADS.prod.sort = f;
        ADS.prod.order = "desc";
      }
      ADS.prod.page = 1;
      loadProducts();
    });
  });
}

function renderProdBody() {
  const p = ADS.prod;
  const cols = p.cols.filter(c => p.fields.includes(c) || c === "是否开通自动广告");
  const body = document.getElementById("prodBody");
  if (!p.rows.length) {
    body.innerHTML = `<tr><td colspan="${Math.max(cols.length, 1)}" style="text-align:center; padding:36px; color:var(--text-muted);">
      暂无数据，请先到「📥 数据导入」上传在线产品Excel</td></tr>`;
    return;
  }
  body.innerHTML = p.rows.map(row => `<tr>${cols.map(c => `<td>${prodCell(c, row)}</td>`).join("")}</tr>`).join("");
}

function renderProdPager() {
  const p = ADS.prod;
  const pager = document.getElementById("prodPager");
  const totalPages = Math.max(1, Math.ceil(p.total / p.pageSize));
  pager.innerHTML = `
    <span>每页
      <select id="prodPageSize" style="padding:3px 6px; border:1px solid var(--border); border-radius:6px;">
        ${[50, 100, 200].map(n => `<option value="${n}" ${n === p.pageSize ? "selected" : ""}>${n}</option>`).join("")}
      </select> 条
    </span>
    <button class="btn btn-outline btn-sm" id="prodPrev" ${p.page <= 1 ? "disabled" : ""}>‹ 上一页</button>
    <span>第 ${p.page} / ${totalPages} 页</span>
    <button class="btn btn-outline btn-sm" id="prodNext" ${p.page >= totalPages ? "disabled" : ""}>下一页 ›</button>`;
  const sizeSel = document.getElementById("prodPageSize");
  if (sizeSel) sizeSel.addEventListener("change", () => { p.pageSize = Number(sizeSel.value); p.page = 1; loadProducts(); });
  const prev = document.getElementById("prodPrev");
  if (prev) prev.addEventListener("click", () => { if (p.page > 1) { p.page--; loadProducts(); } });
  const next = document.getElementById("prodNext");
  if (next) next.addEventListener("click", () => { if (p.page < totalPages) { p.page++; loadProducts(); } });
}

// ═══════════════ Tab3 在线产品-父 ═══════════════
const PAR_COLS = ["图片", "父ASIN", "父SKU", "子ASIN", "标题", "产品价格", "变体数量", "是否在投"];

function parCell(field, row) {
  const v = row[field];
  if (field === "图片") {
    const src = escapeHtml(v || "");
    return src ? `<img class="ads-prod-img" src="${src}" loading="lazy" onerror="this.style.display='none'">` : "-";
  }
  // 代表子品的标题: 单击复制, 超出省略
  if (field === "标题") return copyableSpan(v, "", 260);
  if (field === "是否在投") {
    return v === "是" ? '<span class="ads-badge-yes">在投</span>' : '<span class="ads-badge-no">未投</span>';
  }
  if (/ASIN$/.test(field) && v) return `<span style="font-family:ui-monospace,monospace; font-size:0.8rem;">${escapeHtml(v)}</span>`;
  if (field === "产品价格" && v !== "" && v != null) return `¥${fmtPrice(v)}`;
  if (v === "" || v == null) return "-";
  return escapeHtml(v);
}

async function loadParents() {
  const kw = document.getElementById("parKeyword") ? document.getElementById("parKeyword").value.trim() : "";
  const hasAd = document.getElementById("parHasAdFilter") ? document.getElementById("parHasAdFilter").value : "";
  const sortSel = document.getElementById("parSort");
  const [sort, order] = sortSel ? sortSel.value.split(":") : ["", "desc"];
  const params = new URLSearchParams({ keyword: kw, has_ad: hasAd, sort, order });
  try {
    const res = await fetch(`/api/ads-analysis/parents?${params}`);
    const result = await res.json();
    if (result.code !== 0) { showToast(result.detail || "加载失败", "error"); return; }
    ADS.par.rows = result.data.rows || [];
    renderParTable();
    const badge = document.getElementById("parCountBadge");
    if (badge) badge.innerText = `共 ${fmtNum(ADS.par.rows.length)} 条`;
    // 打广判定所依据的最新日期
    const info = document.getElementById("parLatestDate");
    if (info) info.innerText = result.data.base_date ? `（判定日期：${result.data.base_date}）` : "";
  } catch (err) { showToast(`网络异常: ${err.message}`, "error"); }
}

function renderParTable() {
  const rows = ADS.par.rows;
  const head = document.getElementById("parHead");
  head.innerHTML = PAR_COLS.map(c => {
    let arrow = "";
    if ((c === "产品价格" || c === "变体数量") && ADS.par.sortKey === c) {
      arrow = ADS.par.sortDir === "asc" ? " ▲" : " ▼";
    }
    const sortable = (c === "产品价格" || c === "变体数量") ? " sortable" : "";
    return `<th class="${sortable}" data-field="${escapeHtml(c)}">${escapeHtml(c)}${arrow}</th>`;
  }).join("");
  head.querySelectorAll("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const f = th.dataset.field;
      if (ADS.par.sortKey === f) ADS.par.sortDir = ADS.par.sortDir === "asc" ? "desc" : "asc";
      else { ADS.par.sortKey = f; ADS.par.sortDir = "desc"; }
      const numeric = (a, b) => (Number(a[f]) || 0) - (Number(b[f]) || 0);
      rows.sort(numeric);
      if (ADS.par.sortDir === "desc") rows.reverse();
      renderParTable();
    });
  });
  const body = document.getElementById("parBody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="${PAR_COLS.length}" style="text-align:center; padding:36px; color:var(--text-muted);">
      暂无数据，请先完成「📥 数据导入」与「🔗 数据关联」</td></tr>`;
    return;
  }
  body.innerHTML = rows.map(r => `<tr>${PAR_COLS.map(c => `<td>${parCell(c, r)}</td>`).join("")}</tr>`).join("");
}

// ═══════════════ Tab4 广告研判 ═══════════════
const RES_OP_COL = "操作";
const RES_CHK_COL = "__chk";     // 批量勾选列 (固定在左侧)
const RES_NO_COL = "序号";        // 行序号列

// 「?」图标提示文案 (鼠标悬停查看)
const RES_HELP_TEXT = [
  "【汇总口径】一条 = 一个广告组：量/花费类累加，点击率等比率按总量重算，竞价类取最新",
  "【排序】点击表头可排序",
  "【省略】ASIN / SKU / 标题等长文本列超出省略，鼠标悬停查看完整值",
  "【复制】单击 子ASIN / 父ASIN / 父SKU / 标题 可复制完整内容",
  "【图片】单击产品缩略图可放大预览",
  "【展开/收起】「子ASIN」列头的 ▸ 展开 / ▾ 收起 可展开或收起 父ASIN、父SKU、变体数量、广告产品、活动起止日期",
  "【操作】「操作」列固定在表格最右侧：输入新的每日预算 / 默认竞价后，对应列显示 ↑ 增加（红）/ ↓ 减少（绿），该行即为已标记，可按「标记」筛选",
  "【批量】勾选行后可批量设置每日预算 / 默认竞价（留空字段保持原值）；「🧹」清空已输入内容；「清除标记」清空全部已标记内容"
].join("\n");
// 数值旧→新变化: 增加=红色上升箭头, 减少=绿色下降箭头
function resDeltaTip(field, oldVal, newVal) {
  const fmt = field === "默认竞价" ? fmtPrice : fmtNum;
  const a = Number(oldVal), b = Number(newVal);
  let arrow = "";
  if (oldVal !== "" && oldVal != null && !Number.isNaN(a) && !Number.isNaN(b) && a !== b) {
    arrow = b > a ? ' <span class="ads-up" title="较原值增加">↑</span>'
                  : ' <span class="ads-down" title="较原值减少">↓</span>';
  }
  const before = oldVal === "" || oldVal == null ? "-" : fmt(oldVal);
  return `${before} <span style="color:#94a3b8;">→</span> <b>${fmt(newVal)}</b>${arrow}`;
}

/** 操作列: 左=每日预算新值, 右=默认竞价新值 */
function resOpCell(row) {
  const g = escapeHtml(row["广告组名"] || "");
  const input = (field) => `<input class="ads-op-input" type="text" inputmode="decimal"`
    + ` data-field="${field}" data-group="${g}"`
    + ` value="${escapeHtml(row[field] || "")}"`
    + ` placeholder="${field === "新每日预算" ? "预算" : "竞价"}"`
    + ` title="${field === "新每日预算" ? "输入每日预算新值" : "输入默认竞价新值"}">`;
  return `<span class="ads-op">${input("新每日预算")}${input("新默认竞价")}</span>`;
}

function resCell(field, row) {
  const v = row[field];
  if (field === RES_OP_COL) return resOpCell(row);
  // 每日预算 / 默认竞价: 录入新值后展示 旧 → 新 + 涨跌箭头
  if (field === "每日总预算" || field === "默认竞价") {
    const nv = row[field === "每日总预算" ? "新每日预算" : "新默认竞价"];
    if (nv !== "" && nv != null) return resDeltaTip(field, v, nv);
    return field === "默认竞价" ? fmtPrice(v) : fmtNum(v);
  }
  if (field === "图片") {
    const src = escapeHtml(v || "");
    return src ? `<img class="ads-prod-img" src="${src}" loading="lazy" onerror="this.style.display='none'">` : "-";
  }
  // 列宽收紧: 长文本列一律单行省略, 悬停 title 查看完整值
  if (field === "广告组名") return ellipsisSpan(v, "ads-strong", 150);
  if (field === "广告活动名") return ellipsisSpan(v, "", 130);
  if (field === "日期范围") return ellipsisSpan(v, "ads-mono", 120);
  // 打广天数: 悬停显示具体打广日期 (每行 6 个日期)
  if (field === "打广天数") {
    if (v === "" || v == null) return "-";
    const dates = Array.isArray(row["打广日期"]) ? row["打广日期"] : [];
    let tip = "";
    if (dates.length) {
      const md = dates.map(d => String(d).slice(5));            // MM-DD
      const lines = [];
      for (let i = 0; i < md.length; i += 6) lines.push(md.slice(i, i + 6).join("、"));
      tip = ` title="${escapeHtml(`打广日期（共 ${dates.length} 天，${dates[0]} ~ ${dates[dates.length - 1]}）\n${lines.join("\n")}`)}"`;
    }
    return `<span class="ads-days"${tip}>${fmtNum(v)}</span>`;
  }
  // 标题/ASIN/SKU: 单击即复制完整内容; 标题列与 子ASIN 列同宽, 超出省略
  if (field === "标题") return copyableSpan(v, "", 92);
  if (/ASIN$/.test(field)) return copyableSpan(v, "ads-mono", 92);
  if (/SKU$/.test(field)) return copyableSpan(v, "ads-mono", 78);
  if (isPriceField(field)) return fmtPrice(v);
  if (v === "" || v == null || v === "-") return "-";
  if (typeof v === "number" || /^-?\d+(\.\d+)?$/.test(String(v))) return fmtNum(v);
  return String(v).length > 14 ? ellipsisSpan(v, "", 150) : escapeHtml(v);
}

async function loadResearch() {
  const r = ADS.res;
  const kw = document.getElementById("resKeyword") ? document.getElementById("resKeyword").value.trim() : "";
  const params = new URLSearchParams({
    keyword: kw, days: r.days, marked: r.marked,
    sort: r.sortKey, order: r.sortDir,
    page: r.page, page_size: r.pageSize
  });
  try {
    const res = await fetch(`/api/ads-analysis/research?${params}`);
    const result = await res.json();
    if (result.code !== 0) { showToast(result.detail || "加载失败", "error"); return; }
    const d = result.data;
    r.fields = d.fields || [];
    r.defaults = d.defaults || [];
    r.rows = d.rows || [];
    r.total = d.total || 0;
    r.page = d.page || 1;
    r.pageSize = d.page_size || r.pageSize;
    if (!r.cols.length) loadCols(RES_COL_KEY, r.defaults).forEach(x => r.cols.push(x));
    // 筛选条件变化时清掉已不可见的勾选 (翻页/排序不影响已勾选的行)
    const qkey = `${r.days}|${r.marked}|${kw}`;
    if (r.queryKey !== qkey) {
      const visible = new Set(r.rows.map(x => x["广告组名"] || ""));
      Array.from(r.selected).forEach(g => { if (!visible.has(g)) r.selected.delete(g); });
      r.queryKey = qkey;
    }
    renderResTable();
    renderResPager();
    updateResBadge(d.marked_total);
    updateResBatchInfo();
    updateResHelp(d);
  } catch (err) { showToast(`网络异常: ${err.message}`, "error"); }
}

/** 「?」图标悬停提示: 说明口径 + 当前统计窗口 (自绘浮层, 不依赖浏览器原生 title) */
function updateResHelp(d) {
  const tip = document.getElementById("resHelpTip");
  if (!tip) return;
  const rg = (d && d.range) || {};
  const win = rg.start
    ? `${rg.start} ~ ${rg.end}${rg.days ? `（近${rg.days}天）` : "（全部）"}`
    : "—";
  const marked = (d && d.marked_total) || 0;
  tip.innerText = `${RES_HELP_TEXT}\n\n当前统计窗口：${win}\n当前列表：共 ${ADS.res.total} 个广告组`
    + (marked ? ` · 已标记 ${marked}` : "");
  // 兜底: 同时设置原生 title (浮层未生效时仍可查看)
  const help = document.getElementById("resHelp");
  if (help) help.title = "说明（悬停查看）";
}

/** 广告研判可见列: 未展开时隐藏关联字段 (父ASIN/父SKU/变体数量/广告产品) */
function resVisibleCols() {
  const r = ADS.res;
  const cols = r.cols.filter(c => r.fields.includes(c));
  return r.expanded ? cols : cols.filter(c => !RES_COLLAPSE_FIELDS.includes(c));
}

/** 展开/收起关联字段 (默认收起; 切换后仅在本次会话内保持, 刷新页面回到收起) */
function setResExpanded(v, rerender = true) {
  ADS.res.expanded = !!v;
  if (rerender) renderResTable();
}

/** 实际渲染的列: [勾选, 序号] + 可见列 + 操作列 (左右两端固定) */
function resDisplayCols() {
  const cols = resVisibleCols();
  if (!cols.includes(RES_OP_COL)) cols.push(RES_OP_COL);
  return [RES_CHK_COL, RES_NO_COL].concat(cols);
}

/** 表格下方的批量操作提示 (已选条数 / 按钮可用状态) */
function updateResBatchInfo() {
  const n = ADS.res.selected.size;
  const cnt = document.getElementById("resBatchCount");
  if (cnt) cnt.innerText = `已选 ${n} 条`;
  const btn = document.getElementById("resBatchApply");
  if (btn) btn.disabled = n === 0;
}

/** 批量设置选中行的新每日预算 / 新默认竞价 (留空项保留原值) */
async function applyBatchMarks() {
  const names = Array.from(ADS.res.selected);
  if (!names.length) { showToast("请先勾选要设置的行", "error"); return; }
  const nb = (document.getElementById("resBatchBudget") || {}).value || "";
  const nbid = (document.getElementById("resBatchBid") || {}).value || "";
  if (!nb.trim() && !nbid.trim()) { showToast("请先填写新的每日预算或默认竞价", "error"); return; }
  const btn = document.getElementById("resBatchApply");
  const old = btn ? btn.innerText : "";
  if (btn) { btn.disabled = true; btn.innerText = "⏳ 应用中..."; }
  try {
    const res = await fetch("/api/ads-analysis/marks/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_names: names, new_budget: nb.trim(), new_bid: nbid.trim() })
    });
    const result = await res.json();
    if (!res.ok || result.code !== 0) { showToast(result.detail || result.msg || "批量设置失败", "error"); return; }
    ADS.res.selected.clear();
    showToast(result.msg, "success");
    loadResearch();
  } catch (err) {
    showToast(`网络异常: ${err.message}`, "error");
  } finally {
    if (btn) { btn.disabled = ADS.res.selected.size === 0; btn.innerText = old; }
  }
}

/** 顶部徽标: 组数 + 已标记数 (均为服务端总数, 不受分页影响) */
function updateResBadge(markedTotal) {
  if (typeof markedTotal === "number") ADS.res.markedTotal = markedTotal;
  const badge = document.getElementById("resCountBadge");
  if (!badge) return;
  badge.innerText = `共 ${fmtNum(ADS.res.total)} 个广告组`
    + (ADS.res.markedTotal ? ` · 已标记 ${fmtNum(ADS.res.markedTotal)}` : "");
}

/** 广告研判分页控件 */
function renderResPager() {
  const r = ADS.res;
  const pager = document.getElementById("resPager");
  if (!pager) return;
  const totalPages = Math.max(1, Math.ceil(r.total / r.pageSize));
  pager.innerHTML = `
    <span>每页
      <select id="resPageSize" style="padding:3px 6px; border:1px solid var(--border); border-radius:6px;">
        ${[10, 20, 30, 50, 100, 200].map(n => `<option value="${n}" ${n === r.pageSize ? "selected" : ""}>${n}</option>`).join("")}
      </select> 条
    </span>
    <span>共 ${fmtNum(r.total)} 条</span>
    <button class="btn btn-outline btn-sm" id="resPrev" ${r.page <= 1 ? "disabled" : ""}>‹ 上一页</button>
    <span>第 ${r.page} / ${totalPages} 页</span>
    <button class="btn btn-outline btn-sm" id="resNext" ${r.page >= totalPages ? "disabled" : ""}>下一页 ›</button>`;
  const sizeSel = document.getElementById("resPageSize");
  if (sizeSel) sizeSel.addEventListener("change", () => {
    r.pageSize = Number(sizeSel.value);
    r.page = 1;
    loadResearch();
  });
  const prev = document.getElementById("resPrev");
  if (prev) prev.addEventListener("click", () => { if (r.page > 1) { r.page--; loadResearch(); } });
  const next = document.getElementById("resNext");
  if (next) next.addEventListener("click", () => {
    if (r.page < Math.max(1, Math.ceil(r.total / r.pageSize))) { r.page++; loadResearch(); }
  });
}

function resRowHtml(row, cols, idx) {
  const name = row["广告组名"] || "";
  return cols.map(c => {
    if (c === RES_CHK_COL) {
      const checked = ADS.res.selected.has(name) ? " checked" : "";
      return `<td class="ads-chk-col"><input type="checkbox" class="ads-row-check"`
        + ` data-group="${escapeHtml(name)}"${checked}></td>`;
    }
    if (c === RES_NO_COL) return `<td class="ads-idx-col">${idx}</td>`;
    if (c === RES_OP_COL) return `<td class="ads-op-col">${resCell(c, row)}</td>`;
    return `<td>${resCell(c, row)}</td>`;
  }).join("");
}

function renderResTable() {
  const r = ADS.res;
  const cols = resDisplayCols();
  const head = document.getElementById("resHead");
  // 展开/收起按钮放在「子ASIN」列头 (该列不可见时退回到第一列表头)
  const anchorField = cols.includes("子ASIN") ? "子ASIN" : cols[0];
  const allChecked = r.rows.length > 0 && r.rows.every(x => r.selected.has(x["广告组名"] || ""));
  head.innerHTML = cols.map(c => {
    if (c === RES_CHK_COL) {
      return `<th class="ads-chk-col"><input type="checkbox" id="resCheckAll"`
        + `${allChecked ? " checked" : ""} title="全选 / 取消全选当前列表"></th>`;
    }
    if (c === RES_NO_COL) return `<th class="ads-idx-col" data-field="${RES_NO_COL}">${RES_NO_COL}</th>`;
    if (c === RES_OP_COL) return `<th class="ads-op-col" data-field="${RES_OP_COL}">${RES_OP_COL}</th>`;
    let arrow = "";
    if (r.sortKey === c) arrow = r.sortDir === "asc" ? " ▲" : " ▼";
    const toggle = c === anchorField
      ? `<button class="ads-expand-btn" type="button" title="展开/收起关联字段（共 ${RES_COLLAPSE_FIELDS.length} 项）">`
        + `${r.expanded ? "▾ 收起" : "▸ 展开"}</button>`
      : "";
    return `<th class="sortable" data-field="${escapeHtml(c)}">${escapeHtml(c)}${arrow}${toggle}</th>`;
  }).join("");
  const toggleBtn = head.querySelector(".ads-expand-btn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", (e) => {
      e.stopPropagation();   // 避免触发该列表头排序
      setResExpanded(!ADS.res.expanded);
    });
  }
  const allBox = head.querySelector("#resCheckAll");
  if (allBox) {
    allBox.addEventListener("click", (e) => e.stopPropagation());   // 不要触发表头排序
    allBox.addEventListener("change", () => {
      r.rows.forEach(x => {
        const g = x["广告组名"] || "";
        if (allBox.checked) r.selected.add(g); else r.selected.delete(g);
      });
      renderResTable();
      updateResBatchInfo();
    });
  }
  head.querySelectorAll("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const f = th.dataset.field;
      if (r.sortKey === f) r.sortDir = r.sortDir === "asc" ? "desc" : "asc";
      else { r.sortKey = f; r.sortDir = "desc"; }
      r.page = 1;          // 排序由服务端执行, 回到第一页
      loadResearch();
    });
  });
  const body = document.getElementById("resBody");
  if (!r.rows.length) {
    body.innerHTML = `<tr><td colspan="${Math.max(cols.length, 1)}" style="text-align:center; padding:36px; color:var(--text-muted);">
      暂无数据，请先完成「📥 数据导入」与「🔗 数据关联」</td></tr>`;
    return;
  }
  const base = (r.page - 1) * r.pageSize;   // 序号跨页连续
  body.innerHTML = r.rows.map((row, i) => {
    const cls = row["是否标记"] === "是" ? ' class="ads-marked"' : "";
    return `<tr${cls} data-group="${escapeHtml(row["广告组名"] || "")}">${resRowHtml(row, cols, base + i + 1)}</tr>`;
  }).join("");
}

/** 保存操作列输入的"新值" (任一有值 => 该条记录已标记) */
async function saveResMark(groupName, field, value) {
  const row = ADS.res.rows.find(x => (x["广告组名"] || "") === groupName);
  if (!row) return;
  row[field] = value;
  const payload = {
    group_name: groupName,
    new_budget: row["新每日预算"] || "",
    new_bid: row["新默认竞价"] || ""
  };
  try {
    const res = await fetch("/api/ads-analysis/marks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (!res.ok || result.code !== 0) {
      showToast(result.detail || result.msg || "保存失败", "error");
      return;
    }
    const wasMarked = row["是否标记"] === "是";
    row["是否标记"] = (result.data && result.data.marked) ? "是" : "否";
    if (row["是否标记"] === "是" && !wasMarked) ADS.res.markedTotal += 1;
    else if (row["是否标记"] === "否" && wasMarked) ADS.res.markedTotal = Math.max(0, ADS.res.markedTotal - 1);
    refreshResRow(groupName);
    // 标记状态与当前筛选不符时重新拉取列表, 否则只更新计数
    const mismatch = (ADS.res.marked === "1" && row["是否标记"] === "否")
      || (ADS.res.marked === "0" && row["是否标记"] === "是");
    if (mismatch) loadResearch(); else updateResBadge();
  } catch (err) {
    showToast(`网络异常: ${err.message}`, "error");
  }
}

/** 只重绘该行, 避免整表重渲染导致滚动位置跳动 */
function refreshResRow(groupName) {
  const r = ADS.res;
  const idx = r.rows.findIndex(x => (x["广告组名"] || "") === groupName);
  if (idx < 0) return;
  const row = r.rows[idx];
  const cols = resDisplayCols();
  const no = (r.page - 1) * r.pageSize + idx + 1;
  document.querySelectorAll("#resBody tr").forEach(tr => {
    if (tr.dataset.group !== groupName) return;
    tr.className = row["是否标记"] === "是" ? "ads-marked" : "";
    tr.innerHTML = resRowHtml(row, cols, no);
  });
}

/** 勾选列: 单行勾选 / 表头全选 */
function bindResCheckboxes() {
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (!el || !el.classList || !el.classList.contains("ads-row-check")) return;
    const g = el.dataset.group || "";
    if (el.checked) ADS.res.selected.add(g); else ADS.res.selected.delete(g);
    const all = document.getElementById("resCheckAll");
    if (all) {
      all.checked = ADS.res.rows.length > 0
        && ADS.res.rows.every(x => ADS.res.selected.has(x["广告组名"] || ""));
    }
    updateResBatchInfo();
  });
}

/** 操作列输入框: 回车/失焦即保存 */
function bindResMarkInputs() {
  const save = (el) => {
    const group = el.dataset.group || "";
    const field = el.dataset.field || "";
    if (!group || !field) return;
    const row = ADS.res.rows.find(x => (x["广告组名"] || "") === group);
    const old = row ? (row[field] || "") : "";
    if (old === el.value.trim()) return;
    saveResMark(group, field, el.value.trim());
  };
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el && el.classList && el.classList.contains("ads-op-input")) save(el);
  });
  document.addEventListener("keydown", (e) => {
    const el = e.target;
    if (el && el.classList && el.classList.contains("ads-op-input") && e.key === "Enter") el.blur();
  });
}

// ═══════════════ 统计结果弹窗 ═══════════════
// 说明: 自定义分组、各区域"已清除的重复项"均为**本次会话内存态**(刷新即失效, 不落库)
function closeStatModal() {
  const modal = document.getElementById("statModal");
  if (modal) modal.classList.remove("open");
}

async function openStatModal() {
  const modal = document.getElementById("statModal");
  const body = document.getElementById("statBody");
  if (!modal || !body) return;
  body.innerHTML = '<div style="padding:24px; text-align:center; color:#94a3b8;">⏳ 统计中...</div>';
  modal.classList.add("open");
  try {
    const res = await fetch("/api/ads-analysis/stats");
    const result = await res.json();
    if (!res.ok || result.code !== 0) {
      body.innerHTML = `<div style="padding:24px; color:#dc2626;">统计失败：${escapeHtml(result.detail || "未知错误")}</div>`;
      return;
    }
    await statLoadOptions();                 // 先取店铺/创建方式等选项, 供表单直接渲染
    ADS.stat.setForm = statDefaultSetForm(); // 每次打开重置表单默认值 (结束日期=开始+7天)
    ADS.stat.data = result.data;
    renderStatModal();
  } catch (err) {
    body.innerHTML = `<div style="padding:24px; color:#dc2626;">网络异常：${escapeHtml(err.message)}</div>`;
  }
}

// 重复ASIN 配色: 黄金角(hue 递增 137.5°) + 明度/饱和度分档, 可区分上百种颜色
function dupColorAt(i) {
  const h = Math.round((i * 137.508) % 360);
  const l = [88, 80, 71][Math.floor(i / 24) % 3];              // 每 24 个换一档明度
  const s = [80, 92, 68][Math.floor(i / 8) % 3];               // 每 8 个换一档饱和度
  return {
    bg: `hsl(${h}, ${s}%, ${l}%)`,
    bd: `hsl(${h}, ${Math.min(92, s + 8)}%, ${Math.max(42, l - 26)}%)`,
    fg: `hsl(${h}, 72%, 25%)`
  };
}

// ─────────── 内存态: 区域标识 / 清除项 / 重复项计算 ───────────
const STAT_SCOPE_UN = "unadvertised";

function statScopeCombo(budget, bid) {
  return `combo:${budget}|${bid}`;
}

function statExcludedSet(scope) {
  return new Set(ADS.stat.excluded[scope] || []);
}

/** 扣除本区域"已清除的重复项"后的 ASIN 列表 */
function statVisible(list, scope) {
  const ex = statExcludedSet(scope);
  return (list || []).filter(a => a && !ex.has(a));
}

/** 全区域重复ASIN (组合 + 未投广代表ASIN + 自定义分组, 均已扣除本地清除项) */
function statDupSet(regions) {
  const counter = new Map();
  regions.forEach(r => {
    new Set(statVisible(r.list, r.scope)).forEach(a => counter.set(a, (counter.get(a) || 0) + 1));
  });
  return new Set([...counter.entries()].filter(kv => kv[1] > 1).map(kv => kv[0]));
}

/** 区域工具按钮: 清除本区域的重复项 / 恢复已清除 (均为内存操作) */
function statRegionTools(list, scope, dupSet) {
  const exCount = statExcludedSet(scope).size;
  const dups = statVisible(list, scope).filter(a => dupSet.has(a));
  let h = "";
  if (dups.length) {
    h += `<span class="ads-stat-copy ads-stat-danger" data-act="exclude"`
      + ` data-scope="${escapeHtml(scope)}" data-asins="${escapeHtml(dups.join(","))}"`
      + ` title="把本区域内的重复ASIN清除（仅本次会话，可恢复）">🧹 清除重复项(${dups.length})</span>`;
  }
  if (exCount) {
    h += `<span class="ads-stat-copy" data-act="restore" data-scope="${escapeHtml(scope)}"`
      + ` title="恢复本区域已清除的ASIN">↺ 恢复已清除(${exCount})</span>`;
  }
  return h;
}

function statCollectGroups() {
  const d = ADS.stat.data || {};
  const combos = d.combos || [];
  const out = [];
  // ① 参数组合 (标记后的每日预算/默认竞价已在服务端生效)
  combos.forEach((c, i) => {
    const scope = statScopeCombo(c.new_budget, c.new_bid);
    const asins = statVisible(c.asin_list, scope);
    if (!c.new_budget || !c.new_bid || !asins.length) return;
    out.push({ label: `组合${i + 1}`, budget: c.new_budget, bid: c.new_bid, asins });
  });
  // ② 未投广区域: 栏目统一一对输入框, 适配该栏目下所有代表ASIN (一套参数=一个任务)
  const ub = statFormValue("unPlanBudget").trim();
  const ubd = statFormValue("unPlanBid").trim();
  if (ub || ubd) {
    const un = d.unadvertised || {};
    const ex = statExcludedSet(STAT_SCOPE_UN);
    const asins = ((un.items || []).map(x => x.asin)).filter(a => !ex.has(a));
    if (asins.length) out.push({ label: "未投广分组", budget: ub, bid: ubd, asins });
  }
  // ③ 自定义分组 (内存态)
  (ADS.stat.custom || []).forEach((g, i) => {
    const asins = statVisible(g.asins, g.scope);
    if (!asins.length) return;
    out.push({ label: `自定义分组${i + 1}`, budget: g.budget, bid: g.bid, asins });
  });
  return out;
}

async function statLoadOptions() {
  if (ADS.stat.options) return ADS.stat.options;
  try {
    const res = await fetch("/api/ads/options");
    const r = await res.json();
    ADS.stat.options = (r && r.data) || {};
  } catch (e) {
    ADS.stat.options = {};
  }
  return ADS.stat.options;
}

/** 覆盖检查: 本任务集覆盖的父ASIN vs「在线产品-父」总数, 并区分「未投广未配参数」与「数据缺失」 */
function statCoverageHtml(groups) {
  const cov = (ADS.stat.data || {}).coverage || {};
  const asinParent = cov.asin_parent || {};
  const allParents = new Set(Object.values(asinParent));
  const total = allParents.size || (cov.parent_total || 0);
  if (!total) return "";
  const covered = new Set();
  groups.forEach(g => g.asins.forEach(a => {
    const p = asinParent[a];
    if (p) covered.add(p);
  }));
  // 缺口按「在线产品-父」的父ASIN全量比对 (服务端 missing 只覆盖组合+未投广口径, 这里以当前任务集实际内容为准)
  const reasonMap = new Map(((cov.missing || [])).map(m => [m.parent_asin, m]));
  const gapParents = [...allParents].filter(p => !covered.has(p));
  const unParent = new Set();
  const unItems = (((ADS.stat.data || {}).unadvertised || {}).items) || [];
  const unEx = statExcludedSet(STAT_SCOPE_UN);
  unItems.forEach(x => {
    if (!unEx.has(x.asin)) {
      const p = asinParent[x.asin];
      if (p) unParent.add(p);
    }
  });
  const unPending = gapParents.filter(p => unParent.has(p));               // 未投广栏目未填参数
  const dataGap = gapParents.filter(p => !unParent.has(p)).map(p => reasonMap.get(p) ||
    { parent_asin: p, parent_sku: "", children: [], children_count: 0,
      reason: "广告组报表与广告活动报表均未覆盖该ASIN" });                // 报表数据缺失
  const missing = gapParents;
  if (!missing.length) {
    return `<div style="color:#059669; font-weight:700;">✅ 覆盖检查：本任务集覆盖 ${covered.size} / ${total} 个父ASIN，与「在线产品-父」一致</div>`;
  }
  // 每个没对上的父ASIN 展示其下一个子ASIN (代表, 单击可复制)
  const repOf = new Map();
  unItems.forEach(x => {
    const p = asinParent[x.asin];
    if (p && !repOf.has(p)) repOf.set(p, x.asin);
  });
  ((cov.missing || [])).forEach(m => {
    if (m.rep_asin && !repOf.has(m.parent_asin)) repOf.set(m.parent_asin, m.rep_asin);
  });
  const childTag = (p) => {
    const rep = repOf.get(p);
    return rep ? ` · 子ASIN <span class="ads-copy" data-copy="${escapeHtml(rep)}" title="单击复制该子ASIN">${escapeHtml(rep)}</span>` : "";
  };
  // 差异父SKU 的"代表子ASIN"清单 (一键复制用)
  const gapReps = gapParents.map(p => repOf.get(p)).filter(Boolean);
  const gapRows = dataGap.map(m => {
    const rep = repOf.get(m.parent_asin);
    return `<div style="margin-left:12px;">· <b>${escapeHtml(m.parent_asin)}</b>` + childTag(m.parent_asin) +
      (m.children_count ? `（共 ${m.children_count} 个子ASIN${m.parent_sku ? `，父SKU ${escapeHtml(m.parent_sku)}` : ""}）` : "") +
      `：${escapeHtml(m.reason)}` +
      (rep ? `<span class="ads-copy ads-stat-copy" data-copy="${escapeHtml(rep)}" title="复制该父SKU的代表子ASIN">📋 复制子ASIN</span>` : "") +
      `</div>`;
  }).join("");
  const unPendingRows = unPending.length
    ? `<div style="margin-top:3px; font-size:0.75rem;">` + unPending.map(p =>
        `<span style="display:inline-block; margin-right:10px;"><b>${escapeHtml(p)}</b>${childTag(p)}</span>`)
        .join('<span style="color:#d1d5db;">｜</span>') + `</div>`
    : "";
  return `<div style="background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:8px 10px; color:#92400e;">` +
    `<div style="font-weight:700;">⚠️ 覆盖检查：本任务集覆盖 ${covered.size} / ${total} 个父ASIN，还差 ${missing.length} 个` +
    (gapReps.length
      ? ` <span class="ads-copy ads-stat-copy" data-copy="${escapeHtml(gapReps.join(","))}" title="复制全部差异父SKU各一个代表子ASIN">📋 复制子ASIN</span>`
      : "") + `</div>` +
    (unPending.length
      ? `<div style="margin-top:4px;">① 未投广栏目有 <b>${unPending.length}</b> 个父ASIN未填「每日预算/默认竞价」，本次不纳入（在 ② 栏目填上即可带上）</div>${unPendingRows}`
      : "") +
    (dataGap.length
      ? `<div style="margin-top:4px;">② 数据出入 <b>${dataGap.length}</b> 个（广告组/广告活动报表未覆盖，建议重新导出报表）：</div>${gapRows}`
      : "") +
    `</div>`;
}

function statUpdateSetPreview() {
  const el = document.getElementById("statSetPreview");
  if (!el) return;
  const groups = statCollectGroups();
  const covEl = document.getElementById("statCoverage");
  if (covEl) covEl.innerHTML = statCoverageHtml(groups);
  const asinTotal = groups.reduce((n, g) => n + g.asins.length, 0);
  el.innerHTML = groups.length
    ? `将生成 <b>${groups.length}</b> 个广告任务 / <b>${asinTotal}</b> 个ASIN：`
      + groups.map(g => `<div>· ${escapeHtml(g.label)}：每日预算 <b>${escapeHtml(String(g.budget || "—"))}</b>`
        + ` / 默认竞价 <b>${escapeHtml(String(g.bid || "—"))}</b> → ${g.asins.length} 个ASIN</div>`).join("")
    : '<span style="color:#dc2626;">暂无可生成的分组：请在未投广行填写每日预算/默认竞价，或添加自定义分组</span>';
}

async function generateTaskSet() {
  const groups = statCollectGroups();
  if (!groups.length) { showToast("暂无可生成的分组", "error"); return; }
  const sf = Object.assign({}, ADS.stat.setForm || {}, statReadSetForm());
  const name = (sf.name || "").trim();
  const shop = sf.shop || "";
  const start = sf.start || "";
  const end = sf.end || "";
  const mode = sf.mode || "";
  const batch = sf.batch || "";
  if (!name) { showToast("请填写任务集名称", "error"); return; }
  if (!shop) { showToast("请选择店铺", "error"); return; }
  if (!start) { showToast("请选择开始日期", "error"); return; }
  if (end && end < start) { showToast("结束日期不能早于开始日期", "error"); return; }
  const asinTotal = groups.reduce((n, g) => n + g.asins.length, 0);
  if (!confirm(`生成广告任务集？\n\n任务集：${name}\n店铺：${shop}　投放周期：${start} ~ ${end || "不限"}\n共 ${groups.length} 个广告任务 / ${asinTotal} 个ASIN\n\n生成后在「广告投放」页执行。`)) return;
  try {
    const res = await fetch("/api/ads/task-sets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        set_name: name, shop_name: shop, start_date: start, end_date: end,
        create_mode: mode, batch_size: Number(batch) || 0,
        tasks: groups.map(g => ({
          task_name: `${name}-${g.label}`, budget: g.budget, bid: g.bid, asins: g.asins
        }))
      })
    });
    const result = await res.json();
    if (!res.ok || result.code !== 0) { showToast(result.detail || result.msg || "生成失败", "error"); return; }
    showToast(result.msg, "success");
    window.location.href = "/ads";          // 一次确认后直接跳转投放页
  } catch (err) {
    showToast(`网络异常: ${err.message}`, "error");
  }
}

/** 生成任务集表单默认值 (结束日期 = 开始日期后 7 天) */
function statDefaultSetForm() {
  const opt = ADS.stat.options || {};
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
  const today = opt.today || `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const later = new Date(now.getTime() + 7 * 86400000);
  const end = `${later.getFullYear()}-${pad(later.getMonth() + 1)}-${pad(later.getDate())}`;
  return {
    name: `广告分析-${stamp}`,
    shop: (opt.shop_names || [])[0] || "",
    start: today,
    end: end,
    mode: (opt.create_modes || [])[0] || "",
    batch: "10"
  };
}

/** 读取表单当前值 (供输入变更时同步到内存态, 保证重绘不丢失) */
function statReadSetForm() {
  return {
    name: statFormValue("statSetName"),
    shop: statFormValue("statSetShop"),
    start: statFormValue("statSetDate"),
    end: statFormValue("statSetEndDate"),
    mode: statFormValue("statSetMode"),
    batch: statFormValue("statSetBatch")
  };
}

function renderStatModal() {
  const body = document.getElementById("statBody");
  const d = ADS.stat.data;
  if (!body || !d) return;
  const opt = ADS.stat.options || {};
  const sf = ADS.stat.setForm || (ADS.stat.setForm = statDefaultSetForm());

  const combos = (d.combos || []).map(c => ({
    ...c, scope: statScopeCombo(c.new_budget, c.new_bid)
  }));
  const un = d.unadvertised || { items: [], asin_list: [] };
  const custom = ADS.stat.custom || [];

  // 全区域重复ASIN (本地计算, 含自定义分组与本地清除项)
  const dupSet = statDupSet([
    ...combos.map(c => ({ scope: c.scope, list: c.asin_list })),
    { scope: STAT_SCOPE_UN, list: (un.items || []).map(x => x.asin) },
    ...custom.map(g => ({ scope: g.scope, list: g.asins }))
  ]);
  const dupList = [...dupSet];
  const dupColor = new Map(dupList.map((a, i) => [a, dupColorAt(i)]));
  const asinSpan = (a) => {
    const c = dupColor.get(a);
    const style = c ? ` style="background:${c.bg}; border-color:${c.bd}; color:${c.fg};"` : "";
    const tip = c ? "重复出现的ASIN（同色为同一ASIN），单击复制" : "单击复制";
    return `<span class="ads-asin ads-copy${c ? " ads-asin-dup" : ""}"${style}`
      + ` data-copy="${escapeHtml(a)}" title="${tip}：${escapeHtml(a)}">${escapeHtml(a)}</span>`;
  };
  const asinHtml = (list) => (!list || !list.length) ? "（无匹配ASIN）" : list.map(asinSpan).join(",");

  const dupTip = dupList.length
    ? `<span class="ads-dup-tip">⚠ 重复ASIN ${dupList.length} 个（同色为同一个ASIN）：
        <span class="ads-copy ads-stat-copy" data-copy="${escapeHtml(dupList.join(","))}"
              title="复制全部重复ASIN">📋 复制ASIN</span>
        ${dupList.map(asinSpan).join("，")}</span>`
    : "";

  // ① 参数组合
  const comboHtml = combos.length ? combos.map((c, i) => {
    const vis = statVisible(c.asin_list, c.scope);
    return `
    <div class="ads-stat-block ads-stat-sub">
      <div class="ads-stat-title">
        组合 ${i + 1}：每日预算 <b>${escapeHtml(c.new_budget || "—")}</b> ／ 默认竞价 <b>${escapeHtml(c.new_bid || "—")}</b>
        · ${vis.length} 个ASIN
        <span class="ads-copy ads-stat-copy" data-copy="${escapeHtml(vis.join(","))}">📋 复制ASIN</span>
        ${statRegionTools(c.asin_list, c.scope, dupSet)}
      </div>
      <div class="ads-stat-asin">${asinHtml(vis)}</div>
    </div>`;
  }).join("") : '<div style="color:#94a3b8; padding:8px 0;">暂无数据（需先导入广告组并完成数据关联）</div>';

  // ② 未投广: 每个父SKU一个代表ASIN; 栏目统一一对"每日预算/默认竞价"输入框(会话内存态)
  const unEx = statExcludedSet(STAT_SCOPE_UN);
  const unRows = (un.items || []).filter(x => !unEx.has(x.asin));
  const unBatch = ADS.stat.unBatch || { budget: "", bid: "" };
  const unBatchBar = `
    <div class="ads-batch-bar">
      <span class="ads-batch-label">统一配置本栏目</span>
      <span>每日预算 <input type="text" id="unPlanBudget" class="ads-op-input" style="width:80px;" inputmode="decimal"
                           placeholder="新值" value="${escapeHtml(unBatch.budget || "")}"></span>
      <span>默认竞价 <input type="text" id="unPlanBid" class="ads-op-input" style="width:80px;" inputmode="decimal"
                           placeholder="新值" value="${escapeHtml(unBatch.bid || "")}"></span>
      <span style="color:#94a3b8; font-size:0.76rem;">→ 适配本栏目全部 ${unRows.length} 个代表ASIN</span>
    </div>`;
  // 展示样式与其他分组一致: 代表ASIN 以 asin1,asin2,... 平铺 (点击可复制)
  const unListHtml = `<div class="ads-stat-asin">${
    unRows.length ? unRows.map(x => asinSpan(x.asin)).join(",")
                  : "（无匹配ASIN）"}</div>`;

  // ③ 自定义分组 (内存态)
  const groupHtml = custom.length ? custom.map((g, i) => {
    const vis = statVisible(g.asins, g.scope);
    return `
    <div class="ads-stat-block ads-stat-sub">
      <div class="ads-stat-title">自定义分组${i + 1}：每日预算 <b>${escapeHtml(g.budget || "—")}</b>
        ／ 默认竞价 <b>${escapeHtml(g.bid || "—")}</b> · ${vis.length} 个ASIN
        <span class="ads-copy ads-stat-copy" data-copy="${escapeHtml(vis.join(","))}">📋 复制ASIN</span>
        ${statRegionTools(g.asins, g.scope, dupSet)}
        <span class="ads-stat-copy" data-act="group-edit" data-key="${escapeHtml(g.key)}"
              data-budget="${escapeHtml(g.budget || "")}" data-bid="${escapeHtml(g.bid || "")}"
              data-asins="${escapeHtml(g.asins.join(","))}">✎ 编辑</span>
        <span class="ads-stat-copy ads-stat-danger" data-act="group-del" data-key="${escapeHtml(g.key)}">🗑 删除</span>
      </div>
      <div class="ads-stat-asin">${asinHtml(vis)}</div>
    </div>`;
  }).join("") : '<div style="color:#94a3b8; padding:4px 0;">暂无自定义分组</div>';

  body.innerHTML = `
    <div class="ads-stat-block">
      <div class="ads-stat-title">① 参数组合统计（每日预算 + 默认竞价；已标记的按标记后的值分组）
        · 共 ${fmtNum(d.group_total || 0)} 个广告组 / ${fmtNum(d.combo_total || 0)} 个组合</div>
      ${dupTip}
      <div class="ads-stat-block ads-stat-sub" style="margin:10px 0;">
        <div class="ads-stat-title">自定义分组 · 共 ${fmtNum(custom.length)} 个
          <span class="ads-stat-copy" data-act="group-new" title="新增一个自定义分组（仅本次会话有效）">＋ 新增分组</span>
        </div>
        <div id="statGroupForm" style="display:none; margin:8px 0; padding:10px; border:1px dashed #cbd5e1; border-radius:10px; background:#f8fafc;">
          <input type="hidden" id="statGroupId" value="">
          <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
            <span>每日预算 <input type="text" id="statGroupBudget" class="ads-op-input" style="width:74px;" inputmode="decimal" placeholder="如 300"></span>
            <span>默认竞价 <input type="text" id="statGroupBid" class="ads-op-input" style="width:74px;" inputmode="decimal" placeholder="如 15"></span>
          </div>
          <textarea id="statGroupAsins" rows="3" placeholder="ASIN 列表：逗号 / 换行分隔，如 B0AAAA1111,B0BBBB2222"
            style="width:100%; padding:7px 9px; border:1px solid var(--border); border-radius:8px; font-size:0.8rem; font-family:ui-monospace,monospace;"></textarea>
          <div style="margin-top:8px; display:flex; gap:8px;">
            <button class="btn btn-primary btn-sm" data-act="group-save" type="button" style="background:#0ea5e9;border-color:#0ea5e9;">保存分组</button>
            <button class="btn btn-outline btn-sm" data-act="group-cancel" type="button">取消</button>
          </div>
        </div>
        ${groupHtml}
      </div>
      ${comboHtml}
    </div>
    <div class="ads-stat-block">
      <div class="ads-stat-title">
        ② 当前未投广的父SKU（该父SKU下所有子ASIN均无正在投的广告活动；判定日期：${escapeHtml(d.base_date || "—")}，共 ${fmtNum(unRows.length)} 个父SKU）
        <span class="ads-copy ads-stat-copy" data-copy="${escapeHtml(unRows.map(x => x.asin).join(","))}" title="复制本区域代表ASIN">📋 复制ASIN</span>
        ${statRegionTools((un.items || []).map(x => x.asin), STAT_SCOPE_UN, dupSet)}
      </div>
      ${unListHtml}
      ${unBatchBar}
      <div style="font-size:0.75rem;color:#94a3b8;margin-top:6px;">
        💡 展示每个父SKU的代表子ASIN（逗号分隔，单击可复制）；填写上方统一的「每日预算 / 默认竞价」后，本栏目所有代表ASIN会作为一套参数，点下方「⚡ 生成广告任务集」即可生成对应广告任务（仅本次会话有效）。
      </div>
    </div>
    <div class="ads-stat-block">
      <div class="ads-stat-title">③ 生成广告任务集（每套「每日预算 + 默认竞价」= 一个广告任务）</div>
      <div id="statSetForm" style="margin-top:8px; padding:10px; border:1px dashed #bae6fd; border-radius:10px; background:#f0f9ff;">
        <div style="display:flex; gap:14px; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
          <span>任务集名称 <input type="text" id="statSetName" value="${escapeHtml(sf.name || "")}"
                 style="width:200px; padding:5px 8px; border:1px solid var(--border); border-radius:8px; font-size:0.8rem;"></span>
          <span>店铺 <select id="statSetShop" style="padding:5px 8px; border:1px solid var(--border); border-radius:8px; font-size:0.8rem;">
            ${(opt.shop_names || []).map(s => `<option value="${escapeHtml(s)}"${s === sf.shop ? " selected" : ""}>${escapeHtml(s)}</option>`).join("")}
          </select></span>
        </div>
        <div style="display:flex; gap:14px; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
          <span>开始日期 <input type="date" id="statSetDate" value="${escapeHtml(sf.start || "")}"
                 style="padding:4px 8px; border:1px solid var(--border); border-radius:8px; font-size:0.8rem;"></span>
          <span>结束日期 <input type="date" id="statSetEndDate" value="${escapeHtml(sf.end || "")}"
                 style="padding:4px 8px; border:1px solid var(--border); border-radius:8px; font-size:0.8rem;"
                 title="默认开始日期后 7 天"></span>
        </div>
        <div style="display:flex; gap:14px; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
          <span>创建方式 <select id="statSetMode" style="padding:5px 8px; border:1px solid var(--border); border-radius:8px; font-size:0.8rem;">
            ${(opt.create_modes || []).map(m => `<option value="${escapeHtml(m)}"${m === sf.mode ? " selected" : ""}>${escapeHtml(m)}</option>`).join("")}
          </select></span>
          <span>批次数量 <input type="number" id="statSetBatch" value="${escapeHtml(String(sf.batch || 10))}" min="0"
                 style="width:70px; padding:5px 8px; border:1px solid var(--border); border-radius:8px; font-size:0.8rem;"></span>
        </div>
        <div id="statCoverage" style="font-size:0.78rem; margin-bottom:8px; line-height:1.75;"></div>
        <div id="statSetPreview" style="font-size:0.78rem; color:#334155; background:#fff; border:1px solid #e2e8f0; border-radius:8px; padding:8px 10px; margin-bottom:8px; line-height:1.7;"></div>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-primary btn-sm" data-act="set-save" type="button" style="background:#0ea5e9;border-color:#0ea5e9;">⚡ 生成广告任务集</button>
        </div>
      </div>
    </div>`;
  statUpdateSetPreview();      // 分组/清除项变动后, 预览的任务集内容同步刷新
}

function statFormValue(id) {
  const el = document.getElementById(id);
  return el ? (el.value || "") : "";
}

function statSplitAsins(raw) {
  const s = String(raw || "").replace(/\n/g, ",").replace(/，/g, ",").replace(/\r/g, ",").replace(/\s/g, ",");
  return [...new Set(s.split(",").map(x => x.trim()).filter(Boolean))];
}

/** 统计结果弹窗内的操作 (清除/恢复重复项、计划参数、自定义分组、生成任务集) */
function bindStatActions() {
  document.addEventListener("click", async (e) => {
    const el = e.target && e.target.closest ? e.target.closest("[data-act]") : null;
    if (!el) return;
    const act = el.dataset.act;

    // ── 清除 / 恢复重复项 (仅内存态) ──
    if (act === "exclude") {
      e.stopPropagation();
      const scope = el.dataset.scope || "";
      const asins = (el.dataset.asins || "").split(",").filter(Boolean);
      if (!asins.length) { showToast("本区域没有重复项", "error"); return; }
      ADS.stat.excluded[scope] = [...new Set([...(ADS.stat.excluded[scope] || []), ...asins])];
      showToast(`已清除本区域 ${asins.length} 个重复ASIN（可点「↺ 恢复已清除」还原）`, "success");
      renderStatModal();
      return;
    }
    if (act === "restore") {
      e.stopPropagation();
      delete ADS.stat.excluded[el.dataset.scope || ""];
      renderStatModal();
      return;
    }

    // ── 自定义分组 (仅内存态) ──
    if (act === "group-new") {
      e.stopPropagation();
      const f = document.getElementById("statGroupForm");
      if (!f) return;
      ADS.stat.editKey = "";
      statFormValueReset(["statGroupBudget", "statGroupBid", "statGroupAsins"]);
      f.style.display = "block";
      return;
    }
    if (act === "group-edit") {
      e.stopPropagation();
      const f = document.getElementById("statGroupForm");
      if (!f) return;
      ADS.stat.editKey = el.dataset.key || "";
      const set = (id, v) => { const n = document.getElementById(id); if (n) n.value = v; };
      set("statGroupBudget", el.dataset.budget || "");
      set("statGroupBid", el.dataset.bid || "");
      set("statGroupAsins", el.dataset.asins || "");
      f.style.display = "block";
      f.scrollIntoView({ block: "nearest" });
      return;
    }
    if (act === "group-cancel") {
      e.stopPropagation();
      const f = document.getElementById("statGroupForm");
      if (f) f.style.display = "none";
      return;
    }
    if (act === "group-save") {
      e.stopPropagation();
      const budget = statFormValue("statGroupBudget").trim();
      const bid = statFormValue("statGroupBid").trim();
      const asins = statSplitAsins(statFormValue("statGroupAsins"));
      if (!budget && !bid) { showToast("请至少填写每日预算或默认竞价", "error"); return; }
      if (!asins.length) { showToast("请至少填写一个 ASIN", "error"); return; }
      if (ADS.stat.editKey) {
        const g = (ADS.stat.custom || []).find(x => x.key === ADS.stat.editKey);
        if (g) { g.budget = budget; g.bid = bid; g.asins = asins; }
      } else {
        ADS.stat.seq += 1;
        const key = `c${ADS.stat.seq}`;
        ADS.stat.custom.push({ key, scope: `custom:${key}`, budget, bid, asins });
      }
      ADS.stat.editKey = "";
      renderStatModal();
      showToast("自定义分组已保存（仅本次会话有效）", "success");
      return;
    }
    if (act === "group-del") {
      e.stopPropagation();
      const key = el.dataset.key || "";
      const g = (ADS.stat.custom || []).find(x => x.key === key);
      if (!g || !confirm(`确认删除该自定义分组（${g.asins.length} 个ASIN）？`)) return;
      ADS.stat.custom = ADS.stat.custom.filter(x => x.key !== key);
      delete ADS.stat.excluded[`custom:${key}`];
      renderStatModal();
      return;
    }

    // ── 生成广告任务集 ──
    if (act === "set-save") {
      e.stopPropagation();
      await generateTaskSet();
      return;
    }
  });

  // 输入联动: 未投广统一输入框 → 刷新预览; 任务集表单字段 → 同步内存态(重绘不丢值)
  const SET_FORM_IDS = ["statSetName", "statSetShop", "statSetDate", "statSetEndDate", "statSetMode", "statSetBatch"];
  const onFormInput = (e) => {
    const el = e.target;
    if (!el || !el.id) return;
    if (el.id === "unPlanBudget" || el.id === "unPlanBid") {
      ADS.stat.unBatch = {
        budget: statFormValue("unPlanBudget").trim(),
        bid: statFormValue("unPlanBid").trim()
      };
      statUpdateSetPreview();
    } else if (SET_FORM_IDS.includes(el.id)) {
      ADS.stat.setForm = Object.assign({}, ADS.stat.setForm || {}, statReadSetForm());
    }
  };
  document.addEventListener("input", onFormInput);
  document.addEventListener("change", onFormInput);
}

function statFormValueReset(ids) {
  ids.forEach(id => { const el = document.getElementById(id); if (el) el.value = ""; });
}

function bindStatModal() {
  const btn = document.getElementById("resStatBtn");
  if (btn) btn.addEventListener("click", openStatModal);
  const close = document.getElementById("statClose");
  if (close) close.addEventListener("click", closeStatModal);
  const modal = document.getElementById("statModal");
  if (modal) modal.addEventListener("click", (e) => { if (e.target === modal) closeStatModal(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal && modal.classList.contains("open")) closeStatModal();
  });
  bindStatActions();
}

// ═══════════════ 单击复制单元格 (子ASIN/父ASIN/父SKU/标题) ═══════════════
function fallbackCopy(text, onDone) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "-1000px";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); onDone(); }
  catch (err) { showToast("复制失败，请手动选中复制", "error"); }
  ta.remove();
}

function copyToClipboard(text, onDone) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(onDone).catch(() => fallbackCopy(text, onDone));
  } else {
    fallbackCopy(text, onDone);
  }
}

function bindCopyCells() {
  // 事件委托: 所有 .ads-copy 单元格单击即复制
  document.addEventListener("click", (e) => {
    const el = e.target && e.target.closest ? e.target.closest(".ads-copy") : null;
    if (!el) return;
    const text = el.getAttribute("data-copy") || el.textContent || "";
    if (!text) return;
    copyToClipboard(text, () => {
      showToast(`已复制：${text.length > 42 ? text.slice(0, 42) + "…" : text}`, "success");
    });
  });
}

// ═══════════════ 图片放大预览 ═══════════════
function bindImagePreview() {
  const box = document.getElementById("adsLightbox");
  const bigImg = document.getElementById("adsLightboxImg");
  if (!box || !bigImg) return;
  const close = () => { box.classList.remove("open"); bigImg.removeAttribute("src"); };
  // 事件委托: 所有表格里的产品缩略图都可点击放大
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (t && t.tagName === "IMG" && t.classList.contains("ads-prod-img")) {
      e.preventDefault();
      e.stopPropagation();
      const src = t.getAttribute("src") || "";
      if (!src) return;
      bigImg.src = src;
      box.classList.add("open");
      return;
    }
    if (t === box || (t && t.classList && t.classList.contains("ads-lightbox-close"))) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && box.classList.contains("open")) close();
  });
}

// ═══════════════ 初始化 ═══════════════
function debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

document.addEventListener("DOMContentLoaded", () => {
  // 子菜单切换
  document.querySelectorAll("#adsSubnav .ads-subnav-item").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // Tab1 导入
  bindUpload("fileProducts", "fileProductsName", "btnUploadProducts", "resProducts", "/api/ads-analysis/import/products");
  bindUpload("fileCampaigns", "fileCampaignsName", "btnUploadCampaigns", "resCampaigns", "/api/ads-analysis/import/campaigns");
  bindUpload("fileGroups", "fileGroupsName", "btnUploadGroups", "resGroups", "/api/ads-analysis/import/groups");
  bindLinkData();
  bindClearData();

  // Tab2 产品筛选
  const prodAuto = document.getElementById("prodAutoAdFilter");
  if (prodAuto) prodAuto.addEventListener("change", () => { ADS.prod.page = 1; loadProducts(); });
  const prodKw = document.getElementById("prodKeyword");
  if (prodKw) prodKw.addEventListener("keydown", debounce((e) => { if (e.key === "Enter") { ADS.prod.page = 1; loadProducts(); } }, 300));

  // Tab2 列设置
  bindColPop("prodColBtn", "prodColPop", "prodColList",
    () => ADS.prod.fields, ADS.prod.cols, PROD_COL_KEY,
    () => { saveCols(PROD_COL_KEY, ADS.prod.cols); renderProdHead(); renderProdBody(); },
    () => ADS.prod.defaults);

  // Tab3 筛选
  const parKw = document.getElementById("parKeyword");
  if (parKw) parKw.addEventListener("keydown", (e) => { if (e.key === "Enter") loadParents(); });
  const parHasAd = document.getElementById("parHasAdFilter");
  if (parHasAd) parHasAd.addEventListener("change", loadParents);
  const parSort = document.getElementById("parSort");
  if (parSort) parSort.addEventListener("change", loadParents);

  // Tab4
  const resKw = document.getElementById("resKeyword");
  if (resKw) resKw.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { ADS.res.page = 1; loadResearch(); }
  });
  // 时间范围: 近1天 / 近3天 / 近7天 / 所有
  document.querySelectorAll("#resRange .ads-range-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      ADS.res.days = btn.dataset.days || "";
      document.querySelectorAll("#resRange .ads-range-btn")
        .forEach(b => b.classList.toggle("active", b === btn));
      ADS.res.page = 1;
      loadResearch();
    });
  });
  // 关联字段默认收起 (按钮在「子ASIN」列头, 由 renderResTable 渲染)
  setResExpanded(false, false);
  // 操作列输入框 (新每日预算/新默认竞价) + 批量勾选/批量设置
  bindResMarkInputs();
  bindResCheckboxes();
  const batchApply = document.getElementById("resBatchApply");
  if (batchApply) batchApply.addEventListener("click", applyBatchMarks);
  // 🧹 清空批量输入框里已填写的内容
  const batchWipe = document.getElementById("resBatchWipe");
  if (batchWipe) batchWipe.addEventListener("click", () => {
    const b = document.getElementById("resBatchBudget");
    const d = document.getElementById("resBatchBid");
    if (b) b.value = "";
    if (d) d.value = "";
    showToast("已清空批量输入内容", "success");
  });
  // 清除所有已标记行的新值
  const clearMarks = document.getElementById("resClearMarks");
  if (clearMarks) clearMarks.addEventListener("click", async () => {
    if (!confirm("确认清除所有已标记的内容？\n\n所有已标记行的「新每日预算 / 新默认竞价」都会被清空，操作不可恢复！")) return;
    clearMarks.disabled = true;
    const old = clearMarks.innerText;
    clearMarks.innerText = "⏳ 清除中...";
    try {
      const res = await fetch("/api/ads-analysis/marks/clear", { method: "POST" });
      const result = await res.json();
      if (!res.ok || result.code !== 0) { showToast(result.detail || result.msg || "清除失败", "error"); return; }
      ADS.res.selected.clear();
      showToast(result.msg, "success");
      loadResearch();
    } catch (err) {
      showToast(`网络异常: ${err.message}`, "error");
    } finally {
      clearMarks.disabled = false;
      clearMarks.innerText = old;
    }
  });
  updateResBatchInfo();
  const resMarked = document.getElementById("resMarkedFilter");
  if (resMarked) resMarked.addEventListener("change", () => {
    ADS.res.marked = resMarked.value;
    ADS.res.page = 1;
    loadResearch();
  });
  bindColPop("resColBtn", "resColPop", "resColList",
    () => ADS.res.fields, ADS.res.cols, RES_COL_KEY,
    () => { saveCols(RES_COL_KEY, ADS.res.cols); renderResTable(); },
    () => ADS.res.defaults);

  // 产品图片点击放大预览 (在线产品-子 / 广告研判 通用)
  bindImagePreview();
  // 子ASIN/父ASIN/父SKU/标题 单击复制
  bindCopyCells();
  // 统计结果弹窗
  bindStatModal();

  // 默认进入「广告研判」
  switchTab(DEFAULT_TAB);
});
