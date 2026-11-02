/**
 * 订单管理页面逻辑 (妙手订单包裹)
 * - 列表: /api/orders (分页 + 关键词/状态/店铺/平台/时间筛选)
 * - 详情: /api/orders/{id} (含商品明细)
 * - 同步: /api/orders/sync (按状态 + 时间范围拉取, 需 order:sync 权限)
 */
const orderState = {
  page: 1, page_size: 20, total: 0, pages: 0, loading: false,
  selected: new Set(),   // 批量选择: 订单 id (跨页保留)
};
let orderStatusOptions = [];

const ORDER_STATUS_STYLE = {
  unpaid: { bg: "#fef3c7", color: "#b45309", text: "未付款" },
  wait_confirmed: { bg: "#fef9c3", color: "#a16207", text: "待审核" },
  wait_seller_send: { bg: "#ffedd5", color: "#c2410c", text: "待发货" },
  wait_receiver_confirm: { bg: "#dcfce7", color: "#15803d", text: "已发货" },   // 已发货=绿色
  finished: { bg: "#f0fdf4", color: "#15803d", text: "已完成" },
  cancelled: { bg: "#f1f5f9", color: "#64748b", text: "已关闭" },
  returned: { bg: "#fef2f2", color: "#dc2626", text: "已退款" },
  refunding: { bg: "#fdf2f8", color: "#be185d", text: "售后中" },
};

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, m => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}

/* 初道轨迹描述可能带 HTML 实体 (如 &#8658; 配达完了), 展示/复制前先解码一次 */
function decodeEntities(s) {
  return String(s == null ? "" : s)
    .replace(/&#(\d+);/g, (m, d) => String.fromCharCode(Number(d)))
    .replace(/&#x([0-9a-f]+);/gi, (m, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/&(amp|lt|gt|quot|apos|nbsp);/gi, (m, n) => ({
      amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ",
    }[n.toLowerCase()]));
}

async function orderApi(url, options = {}) {
  const resp = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  if (resp.status === 401) { window.location.href = "/login"; throw new Error("未登录"); }
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok || body.code !== 0) throw new Error(body.detail || body.msg || "请求失败");
  return body;
}

function statusChip(status, text) {
  const conf = ORDER_STATUS_STYLE[status] || { bg: "#f1f5f9", color: "#475569" };
  const label = text || conf.text || status || "—";
  return `<span style="display:inline-block; padding:2px 9px; border-radius:9999px; font-size:0.72rem;
    font-weight:700; white-space:nowrap; background:${conf.bg}; color:${conf.color};">${escapeHtml(label)}</span>`;
}

function fmtMoney(amount, currency) {
  const n = Number(amount || 0);
  const cur = currency === "JPY" ? "JP¥" : (currency ? currency + " " : "");
  return `${cur}${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

/* 人民币估算: 金额 ÷ 22 (悬停提示用) */
const CNY_RATE = 22;
function cnyTip(amount) {
  const cny = Number(amount || 0) / CNY_RATE;
  return `约 ¥${cny.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}（按 ${CNY_RATE} 汇率折算）`;
}

/* ───────── 单据附件 (采购单/采购发票/发货单/配送轨迹/签收单/物流发票/清关证明) ───────── */
const DOC_TYPES = [
  { key: "purchase_order", label: "采购单", icon: "🧾" },
  { key: "purchase_invoice", label: "采购发票", icon: "🧮" },
  { key: "delivery_note", label: "发货单", icon: "📦" },
  { key: "delivery_track", label: "配送轨迹", icon: "🛣️" },
  { key: "receipt", label: "签收单", icon: "✍️" },
  { key: "logistics_invoice", label: "物流发票", icon: "🚚" },
  { key: "customs_cert", label: "清关证明", icon: "🛃" },
];
const docState = { orderId: 0, docType: "", orderSn: "", selected: new Set() };

function docTypeMeta(key) {
  return DOC_TYPES.find(d => d.key === key) || { key: key, label: key, icon: "📎" };
}

/* 单元格: 未上传显示小「＋」; 已有附件则显示每份文件的超小预览 + 曲别针
   (曲别针点开详情: 查看/下载/批量下载/删除/继续上传) */
function docCell(o, key) {
  const info = (o.docs && o.docs[key]) || {};
  const count = info.count || 0;
  const previews = info.previews || [];
  const meta = docTypeMeta(key);
  const sn = escapeHtml(o.order_sn || "");
  if (!count) {
    return `<button type="button" class="order-doc-add order-doc-add-xs"
      title="上传${meta.label}" onclick="pickOrderDoc(${o.id}, '${key}', '${sn}')">＋</button>`;
  }
  const thumbs = previews.map(p => `<img class="order-doc-mini" src="${escapeHtml(p.url)}" alt=""
      data-src="${escapeHtml(p.url)}" title="${escapeHtml(p.file_name || meta.label)}（点击预览）"
      onclick="openOrderImg(this.dataset.src, this.dataset.src)"
      onerror="this.style.display='none'">`).join("");
  const clipBtn = `<button type="button" class="order-doc-clip"
      title="${meta.label} · ${count} 个附件（查看详情 / 批量下载）"
      onclick="openOrderDocs(${o.id}, '${key}', '${sn}')">📎</button>`;
  return `<span class="order-doc-cell">${thumbs}${clipBtn}</span>`;
}

/* 文件类型徽标: 每种扩展名独立配色 (ext-<扩展名>), 一眼区分文件类型 */
const DOC_TYPE_EXTS = [
  "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt",
  "jpg", "jpeg", "png", "webp", "gif", "bmp", "heic",
  "zip", "rar", "7z",
];

function docFileType(fileName) {
  const ext = (String(fileName || "").split(".").pop() || "").toLowerCase();
  const key = DOC_TYPE_EXTS.includes(ext) ? ext : "file";
  return { ext: key === "file" ? "FILE" : key.toUpperCase(), cls: `ext-${key}` };
}

function pickOrderDoc(orderId, docType, orderSn) {
  docState.orderId = orderId;
  docState.docType = docType;
  docState.orderSn = orderSn || "";
  const input = document.getElementById("orderDocInput");
  input.value = "";
  input.click();
}

async function uploadOrderDocs(fileList) {
  const files = [...(fileList || [])];
  if (!files.length || !docState.orderId) return;
  const fd = new FormData();
  fd.append("doc_type", docState.docType);
  files.forEach(f => fd.append("files", f));
  try {
    const resp = await fetch(`/api/orders/${docState.orderId}/docs`, { method: "POST", body: fd });
    if (resp.status === 401) { window.location.href = "/login"; return; }
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok || body.code !== 0) throw new Error(body.detail || body.msg || "上传失败");
    showToast(body.msg || "上传成功", "success");
    await loadOrders();
    if (document.getElementById("orderDocModal").style.display === "flex") await renderDocList();
  } catch (e) {
    showToast("上传失败: " + e.message, "error");
  }
}

async function openOrderDocs(orderId, docType, orderSn) {
  docState.orderId = orderId;
  docState.docType = docType;
  docState.orderSn = orderSn || "";
  docState.selected.clear();
  const meta = docTypeMeta(docType);
  document.getElementById("orderDocTitle").innerText = `${meta.icon} ${meta.label}`;
  document.getElementById("orderDocSub").innerText =
    (orderSn ? orderSn + " · " : "") + "支持图片 / PDF / Office 文档 / 压缩包，可上传多份";
  document.getElementById("orderDocModal").style.display = "flex";
  await renderDocList();
}

async function renderDocList() {
  const box = document.getElementById("orderDocBody");
  box.innerHTML = `<div style="text-align:center; padding:30px; color:#94a3b8;">⏳ 加载中...</div>`;
  try {
    const body = await orderApi(`/api/orders/${docState.orderId}/docs`);
    const docs = (body.data || []).filter(d => d.doc_type === docState.docType);
    if (!docs.length) {
      docState.selected.clear();
      box.innerHTML = `<div style="text-align:center; padding:30px; color:#94a3b8;">
        暂无文件，点击下方「＋ 上传文件」添加</div>`;
      syncDocSelectionUI();
      return;
    }
    // 已删除的文件从选择集中剔除
    const validIds = new Set(docs.map(d => d.id));
    [...docState.selected].forEach(id => { if (!validIds.has(id)) docState.selected.delete(id); });
    box.innerHTML = docs.map(d => {
      const t = docFileType(d.file_name);
      return `
      <div class="order-doc-item">
        <input type="checkbox" class="doc-row-check" value="${d.id}"
          ${docState.selected.has(d.id) ? "checked" : ""}
          style="width:15px; height:15px; cursor:pointer; flex-shrink:0;">
        <div class="order-doc-thumb${d.preview_url ? " order-doc-thumb-zoom" : ""}"
          ${d.preview_url
            ? `data-src="${escapeHtml(d.preview_url)}" data-dl="${escapeHtml(d.relative_url || "")}"
               title="点击放大预览" onclick="openOrderImg(this.dataset.src, this.dataset.dl)"`
            : ""}>
          ${d.preview_url
            ? `<img src="${escapeHtml(d.preview_url)}" alt=""
                 style="object-fit:${d.is_image ? "cover" : "contain"}; background:#fff;">`
            : `<span class="order-doc-ext-big ${t.cls}">${t.ext}</span>`}
        </div>
        <div style="flex:1; min-width:0;">
          <div class="order-doc-name">
            <span class="order-doc-file">${escapeHtml(d.file_name)}</span>
            <span class="order-doc-ext ${t.cls}" title="文件类型">${t.ext}</span>
          </div>
          <div style="font-size:0.72rem; color:#94a3b8; margin-top:3px;">
            ${escapeHtml(d.size_text || "")} · ${escapeHtml((d.created_at || "").slice(0, 16))}</div>
        </div>
        <a class="btn btn-outline btn-sm" style="padding:3px 9px; font-size:0.72rem; text-decoration:none;"
          href="/api/orders/docs/${d.id}/download" target="_blank">下载</a>
        <button class="btn btn-outline btn-sm" type="button"
          style="padding:3px 9px; font-size:0.72rem; color:#dc2626; border-color:#fecaca;"
          onclick="deleteOrderDoc(${d.id})">删除</button>
      </div>`;
    }).join("");
    syncDocSelectionUI();
  } catch (e) {
    if (e.message !== "未登录") {
      box.innerHTML = `<div style="text-align:center; padding:30px; color:#dc2626;">
        加载失败: ${escapeHtml(e.message)}</div>`;
    }
  }
}

async function deleteOrderDoc(id) {
  if (!confirm("确定删除该附件吗？删除后文件不可恢复。")) return;
  try {
    const resp = await fetch(`/api/orders/docs/${id}`, { method: "DELETE" });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok || body.code !== 0) throw new Error(body.detail || body.msg || "删除失败");
    showToast("附件已删除", "success");
    docState.selected.delete(Number(id));
    await loadOrders();
    await renderDocList();
  } catch (e) {
    showToast("删除失败: " + e.message, "error");
  }
}

/* ───────── 附件批量选择 / 批量删除 ───────── */
function syncDocSelectionUI() {
  const bar = document.getElementById("orderDocToolbar");
  const countEl = document.getElementById("orderDocSelCount");
  const all = document.getElementById("orderDocCheckAll");
  const boxes = [...document.querySelectorAll("#orderDocBody .doc-row-check")];
  const count = docState.selected.size;
  if (bar) bar.style.display = boxes.length ? "flex" : "none";
  if (countEl) countEl.innerText = `已选 ${count} 个`;
  if (all) {
    all.checked = boxes.length > 0 && boxes.every(b => b.checked);
    all.indeterminate = boxes.some(b => b.checked) && !all.checked;
  }
}

async function batchDeleteOrderDocs() {
  const ids = [...docState.selected];
  if (!ids.length) { showToast("请先勾选要删除的附件", "error"); return; }
  if (!confirm(`确定删除选中的 ${ids.length} 个附件吗？删除后文件不可恢复。`)) return;
  try {
    const body = await orderApi("/api/orders/docs/batch-delete", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
    docState.selected.clear();
    showToast(body.msg || "已删除", "success");
    await renderDocList();
    await loadOrders();
  } catch (e) {
    showToast("批量删除失败: " + e.message, "error");
  }
}

function uploadMoreDocs() {
  if (!docState.orderId) return;
  const input = document.getElementById("orderDocInput");
  input.value = "";
  input.click();
}

/* 批量下载: 该订单该类型下全部附件打包为 zip */
function downloadDocsZip() {
  if (!docState.orderId || !docState.docType) return;
  const url = `/api/orders/${docState.orderId}/docs/zip?doc_type=${encodeURIComponent(docState.docType)}`;
  window.open(url, "_blank");
}

function closeOrderDocs() {
  document.getElementById("orderDocModal").style.display = "none";
}

/* ───────── 批量上传单据 (勾选多单 → 同一批文件写入每单的对应单据) ───────── */
const batchUploadState = { ids: [], picking: "", files: {} };
let batchUploading = false;

/* 同一文件去重键: 同名 + 同大小 + 同修改时间 */
function batchFileKey(f) {
  return `${f.name}__${f.size}__${f.lastModified}`;
}

function openBatchUpload() {
  const ids = [...orderState.selected];
  if (!ids.length) { showToast("请先勾选要上传的订单", "error"); return; }
  if (ids.length > 200) { showToast("单次最多批量上传 200 单，请减少勾选", "error"); return; }
  batchUploadState.ids = ids;
  batchUploadState.picking = "";
  batchUploadState.files = {};
  document.getElementById("orderBatchUploadSub").innerText =
    `已选 ${ids.length} 单 · 同一批文件会分别上传到这些订单的对应单据`;
  const prog = document.getElementById("orderBatchUploadProgress");
  prog.style.display = "none";
  prog.innerHTML = "";
  const btn = document.getElementById("orderBatchUploadStart");
  btn.disabled = false;
  btn.innerText = "开始上传";
  renderBatchUploadRows();
  document.getElementById("orderBatchUploadModal").style.display = "flex";
}

function renderBatchUploadRows() {
  const box = document.getElementById("orderBatchUploadRows");
  if (!box) return;
  box.innerHTML = DOC_TYPES.map(dt => {
    const files = batchUploadState.files[dt.key] || [];
    const chips = files.length
      ? `<div style="display:flex; flex-wrap:wrap; gap:4px;">${files.map((f, i) => `
          <span class="tag-badge" style="display:inline-flex; align-items:center; gap:4px; padding:1px 7px;
            border-radius:9999px; background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe;
            font-size:0.68rem; max-width:260px;">
            <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(f.name)}</span>
            <span style="cursor:pointer; color:#64748b; font-weight:700;" title="移除"
              onclick="removeBatchFile('${dt.key}', ${i})">✕</span>
          </span>`).join("")}</div>`
      : `<span style="font-size:0.74rem; color:#94a3b8;">未选择文件</span>`;
    return `<div style="display:flex; align-items:flex-start; gap:10px; padding:8px 10px;
        border:1px solid #e2e8f0; border-radius:8px;">
      <span style="font-size:1.05rem; line-height:1.5; flex-shrink:0;">${dt.icon}</span>
      <div style="flex:1; min-width:0;">
        <div style="font-size:0.8rem; font-weight:700; color:#334155;">
          ${dt.label}
          ${files.length ? `<span style="color:#2563eb;">· ${files.length} 个文件</span>` : ""}
        </div>
        <div style="margin-top:4px;">${chips}</div>
      </div>
      <button class="btn btn-outline btn-sm" type="button"
        style="padding:2px 9px; font-size:0.72rem; flex-shrink:0;"
        onclick="pickBatchDocFiles('${dt.key}')">选择文件</button>
    </div>`;
  }).join("");
}

function pickBatchDocFiles(key) {
  batchUploadState.picking = key;
  const input = document.getElementById("orderBatchUploadInput");
  input.value = "";
  input.click();
}

function removeBatchFile(key, index) {
  const list = batchUploadState.files[key] || [];
  list.splice(index, 1);
  batchUploadState.files[key] = list;
  renderBatchUploadRows();
}

function clearBatchUpload() {
  batchUploadState.files = {};
  renderBatchUploadRows();
}

function closeBatchUpload() {
  if (batchUploading) { showToast("正在上传，请稍候…", "error"); return; }
  const modal = document.getElementById("orderBatchUploadModal");
  if (modal) modal.style.display = "none";
  batchUploadState.ids = [];
  batchUploadState.files = {};
  batchUploadState.picking = "";
}

async function startBatchUpload() {
  if (batchUploading) return;
  const ids = [...batchUploadState.ids];
  if (!ids.length) { showToast("请先勾选要上传的订单", "error"); return; }
  const tasks = DOC_TYPES.filter(dt => (batchUploadState.files[dt.key] || []).length);
  if (!tasks.length) { showToast("请先为至少一类单据选择文件", "error"); return; }

  const btn = document.getElementById("orderBatchUploadStart");
  const prog = document.getElementById("orderBatchUploadProgress");
  batchUploading = true;
  btn.disabled = true;
  btn.innerText = "⏳ 上传中...";
  prog.style.display = "block";

  let savedFiles = 0, okOrders = 0, failOrders = 0, errs = [];
  const retryTypes = [];        // 未完全成功的单据类型 (保留文件, 便于重试)
  for (let i = 0; i < tasks.length; i += 1) {
    const dt = tasks[i];
    prog.innerHTML = `正在上传「${dt.icon} ${dt.label}」（${i + 1}/${tasks.length}）…`;
    const fd = new FormData();
    fd.append("order_ids", ids.join(","));
    fd.append("doc_type", dt.key);
    (batchUploadState.files[dt.key] || []).forEach(f => fd.append("files", f));
    try {
      const resp = await fetch("/api/orders/docs/batch-upload", { method: "POST", body: fd });
      if (resp.status === 401) { window.location.href = "/login"; return; }
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok || body.code !== 0) throw new Error(body.detail || body.msg || "上传失败");
      const d = body.data || {};
      savedFiles += (d.saved || []).length;
      okOrders = Math.max(okOrders, d.ok_orders || 0);
      const failed = d.failed || [];
      failed.forEach(x => {
        failOrders += 1;
        errs.push(`${dt.label} #${x.order_id}: ${x.reason || "失败"}`);
      });
      if (failed.length) retryTypes.push(dt.key);
      else delete batchUploadState.files[dt.key];   // 该类全部成功: 清空, 避免重复上传
    } catch (e) {
      if (e.message === "未登录") return;
      errs.push(`${dt.label}: ${e.message}`);
      retryTypes.push(dt.key);
    }
  }

  batchUploading = false;
  btn.disabled = false;
  btn.innerText = "开始上传";

  const parts = [`已上传 ${savedFiles} 个文件`];
  if (okOrders) parts.push(`覆盖 ${okOrders} 单`);
  if (failOrders) parts.push(`${failOrders} 单失败`);
  const msg = parts.join("，");
  const hasErr = errs.length > 0;
  prog.innerHTML = `${hasErr ? "⚠️" : "✅"} ${escapeHtml(msg)}` + (hasErr
    ? `<div style="margin-top:4px; color:#b45309;">${escapeHtml(errs.slice(0, 6).join("；"))}${
      errs.length > 6 ? ` 等 ${errs.length} 项` : ""}</div>`
    : "");
  showToast(msg, hasErr ? "error" : "success");

  await loadOrders();
  if (retryTypes.length) renderBatchUploadRows();   // 失败的类型保留文件, 供修正后重试
  else setTimeout(() => { if (!batchUploading) closeBatchUpload(); }, 1200);
}

document.getElementById("orderBatchUploadInput").addEventListener("change", function () {
  const key = batchUploadState.picking;
  if (!key) return;
  const list = batchUploadState.files[key] || [];
  const seen = new Set(list.map(batchFileKey));
  [...(this.files || [])].forEach(f => {
    const k = batchFileKey(f);
    if (seen.has(k)) return;
    seen.add(k);
    list.push(f);
  });
  batchUploadState.files[key] = list;
  renderBatchUploadRows();
});

document.getElementById("orderDocInput").addEventListener("change", function () {
  uploadOrderDocs(this.files);
});

/* ───────────── 筛选项 / 统计 ───────────── */
async function loadOrderFilters() {
  try {
    const body = await orderApi("/api/orders/filters");
    const d = body.data || {};
    orderStatusOptions = d.status_options || [];

    const statusSel = document.getElementById("orderStatus");
    statusSel.innerHTML = `<option value="">全部状态（不含已关闭）</option>` + orderStatusOptions.map(s => {
      const conf = ORDER_STATUS_STYLE[s.value] || {};
      return `<option value="${s.value}">${escapeHtml(s.label || conf.text || s.value)}</option>`;
    }).join("");

    const shopSel = document.getElementById("orderShop");
    shopSel.innerHTML = `<option value="">全部店铺</option>` + (d.shops || []).map(s =>
      `<option value="${escapeHtml(s.shop_id)}">${escapeHtml(s.shop_name || s.shop_id)}</option>`).join("");


    // 总数与各状态数量合并为「一块」汇总: 共 8 单 · 已发货 8 · 待发货 2
    const stats = d.stats || {};
    const parts = orderStatusOptions
      .filter(s => stats[s.value])
      .map(s => {
        const conf = ORDER_STATUS_STYLE[s.value] || {};
        return `<span style="color:${conf.color || "#475569"}; font-weight:700;">${escapeHtml(s.label)} ${stats[s.value]}</span>`;
      });
    const summary = `共 ${d.total || 0} 单` + (parts.length ? ` · ${parts.join(" · ")}` : "");
    document.getElementById("orderStatBar").innerHTML =
      `<span class="tag-badge" style="background:#f1f5f9; color:#475569; border:none; padding:3px 10px;
        white-space:normal; line-height:1.5;">${summary}</span>`;
  } catch (e) {
    if (e.message !== "未登录") showToast("加载筛选项失败: " + e.message, "error");
  }
}

/* ───────── 运单轨迹 (与运单管理同源: 初道 gettrack) ───────── */
const trackState = { orderId: 0, data: null };

/* 轨迹状态徽标: 按关键词着色 (签收=绿 / 异常退回=红 / 运输派送=蓝 / 揽收=靛) */
function trackChip(name) {
  const s = String(name || "").trim();
  if (!s) return `<span style="color:#cbd5e1;">—</span>`;
  let bg = "#f1f5f9", color = "#475569";
  if (/签收|妥投|已送达|投递成功|delivered/i.test(s)) { bg = "#dcfce7"; color = "#15803d"; }
  else if (/退回|退件|退运|异常|失败|丢失|扣留|销毁|return|failed|exception|expired/i.test(s)) {
    bg = "#fef2f2"; color = "#dc2626";
  } else if (/派送|派件|运输|转运|已发出|出库|清关|离港|到港|到达|transit|out for delivery|departed|arrived/i.test(s)) {
    bg = "#eff6ff"; color = "#1d4ed8";
  } else if (/揽收|收寄|已收件|pick ?up|collected/i.test(s)) { bg = "#eef2ff"; color = "#4338ca"; }
  return `<span style="display:inline-block; padding:2px 9px; border-radius:9999px; font-size:0.72rem;
    font-weight:700; white-space:nowrap; background:${bg}; color:${color};">${escapeHtml(s)}</span>`;
}

/* ── 运单号跳转查询 (与运单管理页一致: 自动复制 + 打开对应网站) ── */
const SAGAWA_URL = "https://k2k.sagawa-exp.co.jp/p/sagawa/web/okurijoinput.jsp";

/* 是否佐川急便单号: 承运商命中, 或 日本目的地 + 12 位纯数字 (妙手尾程号特征) */
function isSagawaTracking(o) {
  const no = String(o.tracking_no || "").trim();
  const company = String(o.tracking_company || "");
  if (/佐川|sagawa/i.test(company)) return true;
  if (company) return false;
  return /^\d{12}$/.test(no) && String(o.dest_country || "").toUpperCase() === "JP";
}

/* 通用复制 (订单号/运单号等), 失败时退回 execCommand */
function copyTextValue(text, label) {
  const v = String(text || "").trim();
  if (!v) return;
  const tip = `${label || "内容"}: ${v}`;
  const done = () => showToast("已复制 " + tip);
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(v).then(done)
      .catch(() => fallbackCopyValue(v, tip));
  } else {
    fallbackCopyValue(v, tip);
  }
}

function fallbackCopyValue(v, tip) {
  const ta = document.createElement("textarea");
  ta.value = v;
  ta.style.cssText = "position:fixed; left:-9999px; top:0;";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  document.body.removeChild(ta);
  showToast(ok ? "已复制 " + tip : "复制失败，请手动选择", ok ? "success" : "error");
}

function copyTrackingNo(no) {
  copyTextValue(no, "运单号");
}

/* 上一次运单号 (人工修改前的值): 灰色删除线显示在当前单号下方 */
function prevTrackingLine(o) {
  const prev = String(o.prev_tracking_no || "").trim();
  const cur = String(o.tracking_no || "").trim();
  if (!prev || prev === cur) return "";
  return `<div style="font-size:0.68rem; color:#94a3b8; text-decoration:line-through;
    margin-top:2px; max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
    >${escapeHtml(prev)}</div>`;
}

/* 运单号单元格右侧的跳转图标: 自动复制单号并打开对应查询网站 */
function trackJumpCell(o) {
  const no = String(o.tracking_no || "").trim();
  if (!no) return `<span style="color:#cbd5e1;">—</span>`;
  const sagawa = isSagawaTracking(o);
  return `<span class="copy-chip" data-v="${escapeHtml(no)}"
      onclick="copyTrackingNo(this.dataset.v)">${escapeHtml(no)}</span>
    <button class="btn btn-outline btn-sm" type="button" data-no="${escapeHtml(no)}"
      data-site="${sagawa ? "sagawa" : "track17"}"
      style="padding:1px 6px; font-size:0.68rem; line-height:1.5; margin-left:4px; color:#2563eb; border-color:#bfdbfe;"
      onclick="jumpTrackingSite(this)">↗</button>`;
}

function jumpTrackingSite(btn) {
  const no = btn.dataset.no || "";
  if (!no) return;
  const url = btn.dataset.site === "sagawa"
    ? SAGAWA_URL
    : "https://t.17track.net/zh-cn#nums=" + encodeURIComponent(no);
  copyTrackingNo(no);
  window.open(url, "_blank");
}

/* 合单标记: 同一运单号下还有别的订单时, 状态旁只显示数量, 悬停列出合并的 amazon 订单号 */
function mergeChip(o) {
  const list = Array.isArray(o.merged_orders) ? o.merged_orders : [];
  if (!list.length) return "";
  const shown = list.slice(0, 5).join("、");
  const tip = `与 ${shown}${list.length > 5 ? ` 等 ${list.length} 单` : ""} 共用运单号 `
    + `${o.tracking_no || ""}（点击复制合并的订单号）`;
  return `<span title="${escapeHtml(tip)}" data-v="${escapeHtml(list.join(", "))}"
    onclick="copyTextValue(this.dataset.v, '合并订单号')"
    style="display:inline-block; margin-left:4px; padding:0 5px; border-radius:9999px;
    font-size:0.66rem; font-weight:700; background:#ede9fe; color:#6d28d9; white-space:nowrap;
    cursor:pointer;">${list.length}</span>`;
}

/* 补录状态: 采购日期 / 国内包裹数 / 国内单号 三项齐全才算已补录; 点击打开补录弹窗 */
function isSupplemented(o) {
  return !!(String(o.purchase_date || "").trim()
    && Number(o.domestic_package_count || 0) > 0
    && String(o.domestic_tracking_no || "").trim());
}

/* 最新轨迹单元格: 单行截断 + 时间, 点击打开时间线弹窗 */
function trackSummaryCell(o) {
  const desc = decodeEntities(String(o.track_desc || "").trim());
  const time = String(o.track_time || "").trim();
  if (!desc && !time) return `<span style="color:#cbd5e1;">—</span>`;
  return `<div style="cursor:pointer; max-width:260px;"
      onclick="openOrderTrack(${o.id})">
    <div style="font-size:0.76rem; color:#334155; line-height:1.4; white-space:nowrap; overflow:hidden;
      text-overflow:ellipsis;">${escapeHtml(desc || "—")}</div>
    ${time ? `<div style="font-size:0.68rem; color:#94a3b8; margin-top:2px;">🕐 ${escapeHtml(time)}</div>` : ""}
  </div>`;
}

/* 轨迹查询成功后回填当前行 (状态 / 最新轨迹 / 更新时间), 免刷新整页 */
function patchTrackRow(orderId, d) {
  const tr = document.querySelector(`#orderTableBody tr[data-oid="${orderId}"]`);
  if (!tr) return;
  const st = tr.querySelector(".js-track-status");
  if (st) st.innerHTML = trackChip(d.track_status_name);
  const desc = tr.querySelector(".js-track-desc");
  if (desc) desc.innerHTML = trackSummaryCell({
    id: orderId, track_desc: d.last_track_desc, track_time: d.last_track_time,
  });
  const at = tr.querySelector(".js-track-at");
  if (at) at.innerText = (d.track_refreshed_at || "").slice(0, 16) || "—";
}

/* 轨迹弹窗内的单号 (运单号/初岛号/跨境运单号): 统一样式, 点击复制 */
function trackNoItem(label, value) {
  const v = String(value || "").trim();
  if (!v) return "";
  return `${label} <b style="color:#0f172a; cursor:pointer;"
    data-v="${escapeHtml(v)}"
    onclick="copyTextValue(this.dataset.v, '${label}')">${escapeHtml(v)}</b>`;
}

async function openOrderTrack(orderId) {
  trackState.orderId = orderId;
  trackState.data = null;
  const modal = document.getElementById("orderTrackModal");
  const sub = document.getElementById("orderTrackSub");
  const bodyEl = document.getElementById("orderTrackBody");
  if (!modal || !bodyEl) return;
  sub.innerText = "正在查询初道轨迹...";
  bodyEl.innerHTML = `<div style="text-align:center; padding:34px; color:#94a3b8;">⏳ 查询中...</div>`;
  document.getElementById("orderTrackJumpBtn").disabled = true;
  modal.style.display = "flex";
  try {
    const res = await orderApi(`/api/orders/${orderId}/track`);
    const d = res.data || {};
    trackState.data = d;
    const crossNo = String(d.channel_hawbcode || "").trim();
    sub.innerHTML = [
      trackNoItem("运单号", d.tracking_no),
      trackNoItem("初岛号", d.chudao_no === d.tracking_no ? "" : d.chudao_no),
      trackNoItem("跨境运单号", crossNo),
      d.track_status_name ? trackChip(d.track_status_name) : "",   // 与列表「运单状态」列同为彩色胶囊
      d.tracking_company ? escapeHtml(d.tracking_company) : "",
    ].filter(Boolean).join(" · ") || "—";
    document.getElementById("orderTrackJumpBtn").disabled = !(crossNo || d.tracking_no);
    patchTrackRow(orderId, d);

    const details = d.details || [];
    if (!details.length) {
      bodyEl.innerHTML = `<div style="text-align:center; padding:34px; color:#94a3b8;">
        该运单暂无轨迹记录${d.last_track_desc ? `<div style="margin-top:8px; color:#64748b; font-size:0.82rem;">${escapeHtml(decodeEntities(d.last_track_desc))}</div>` : ""}</div>`;
      return;
    }
    bodyEl.innerHTML = `<div class="wb-timeline">` + details.map((t, i) => `
      <div class="wb-timeline-item">
        <div class="wb-timeline-time">🕐 ${escapeHtml(t.track_occur_date || "")}${t.track_location ? " · " + escapeHtml(t.track_location) : ""}
          ${i === 0 ? `<span style="display:inline-block; margin-left:6px; padding:0 6px; border-radius:9999px;
            background:#dbeafe; color:#1d4ed8; font-size:0.66rem; font-weight:700;">最新</span>` : ""}</div>
        <div class="wb-timeline-desc">${escapeHtml(decodeEntities(t.track_description) || "—")}</div>
      </div>`).join("") + `</div>`;
  } catch (e) {
    if (e.message === "未登录") return;
    sub.innerText = "查询失败";
    bodyEl.innerHTML = `<div style="text-align:center; padding:34px; color:#dc2626;">❌ 轨迹查询失败: ${escapeHtml(e.message)}</div>`;
  }
}

function closeOrderTrack() {
  const modal = document.getElementById("orderTrackModal");
  if (modal) modal.style.display = "none";
  trackState.orderId = 0;
  trackState.data = null;
}

function copyOrderTrack() {
  const d = trackState.data;
  if (!d) { showToast("暂无轨迹可复制", "error"); return; }
  const lines = [`运单号: ${d.tracking_no || "—"}`];
  if (d.chudao_no && d.chudao_no !== d.tracking_no) lines.push(`初岛号: ${d.chudao_no}`);
  if (d.channel_hawbcode) lines.push(`跨境运单号: ${d.channel_hawbcode}`);
  if (d.tracking_company) lines.push(`物流公司: ${d.tracking_company}`);
  if (d.track_status_name) lines.push(`运单状态: ${d.track_status_name}`);
  if (d.last_track_time) lines.push(`更新时间: ${d.last_track_time}`);
  lines.push("");
  (d.details || []).forEach(t => lines.push(
    `[${t.track_occur_date || ""}] ${decodeEntities(t.track_description) || ""}`.trim()));
  const text = lines.join("\n");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text)
      .then(() => showToast("轨迹已复制"))
      .catch(() => fallbackCopyTrack(text));
  } else {
    fallbackCopyTrack(text);
  }
}

function fallbackCopyTrack(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed; left:-9999px; top:0;";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  document.body.removeChild(ta);
  showToast(ok ? "轨迹已复制" : "复制失败，请手动选择文本", ok ? "success" : "error");
}

/* 17TRACK 查询: 优先用跨境运单号, 没有则退回运单号 */
function jumpOrderTrack() {
  const d = trackState.data || {};
  const no = String(d.channel_hawbcode || d.tracking_no || "").trim();
  if (!no) { showToast("该订单没有运单号", "error"); return; }
  window.open("https://t.17track.net/zh-cn#nums=" + encodeURIComponent(no), "_blank");
}

/* ───────────── 列表 ───────────── */
async function loadOrders() {
  const tbody = document.getElementById("orderTableBody");
  if (orderState.loading) return;
  orderState.loading = true;
  orderState.page_size = Number(document.getElementById("orderPageSize").value || 20);
  const params = new URLSearchParams({
    keyword: document.getElementById("orderKeyword").value.trim(),
    status: document.getElementById("orderStatus").value,
    shop_id: document.getElementById("orderShop").value,
    date_from: document.getElementById("orderDateFrom").value,
    date_to: document.getElementById("orderDateTo").value,
    page: orderState.page,
    page_size: orderState.page_size,
  });
  tbody.innerHTML = `<tr><td colspan="20" style="text-align:center; padding:40px; color:var(--text-muted);">⏳ 加载中...</td></tr>`;
  try {
    const body = await orderApi("/api/orders?" + params.toString());
    const d = body.data || {};
    orderState.total = d.total || 0;
    orderState.pages = d.pages || 0;
    renderOrderRows(tbody, d.rows || []);
    renderOrderPager();
  } catch (e) {
    if (e.message !== "未登录") {
      tbody.innerHTML = `<tr><td colspan="20" style="text-align:center; padding:40px; color:#dc2626;">
        ❌ 加载失败: ${escapeHtml(e.message)}</td></tr>`;
    }
  } finally {
    orderState.loading = false;
  }
}

/* 商品图单元格: 56×56 缩略图, 点击放大; 无图显示灰色占位框 */
function orderImgCell(o) {
  const big = o.cover_img_big || o.cover_img || "";
  if (!big) return orderImgPlaceholder();
  const thumb = o.cover_img || big;
  return `<img src="${escapeHtml(thumb)}" alt="" loading="lazy" data-big="${escapeHtml(big)}" data-thumb="${escapeHtml(thumb)}"
    style="width:36px; height:36px; object-fit:cover; border-radius:6px; border:1px solid #e2e8f0;
           background:#f8fafc; cursor:zoom-in; display:block; margin:0 auto;"
    onclick="openOrderImg(this.dataset.big, this.dataset.thumb)" onerror="orderImgFallback(this)">`;
}

function orderImgPlaceholder() {
  return `<div style="width:36px; height:36px; border-radius:6px; background:#f1f5f9;
    border:1px dashed #cbd5e1; display:flex; align-items:center; justify-content:center;
    color:#94a3b8; font-size:0.62rem; margin:0 auto;">无图</div>`;
}

function orderImgFallback(img) {
  const ph = document.createElement("div");
  ph.innerHTML = orderImgPlaceholder();
  img.replaceWith(ph.firstElementChild);
}

/* 商品标识: 列表显示 ≤5 字简版, 点击复制「完整标识」, 悬停 tooltip 显示完整版;
   未识别显示灰色待识别 (下次同步自动重试) */
function productCell(short, full) {
  const s = (short || "").trim() || (full || "").trim();
  const f = (full || "").trim() || s;
  if (!s) return `<span style="color:#cbd5e1; font-size:0.72rem;">待识别</span>`;
  const isUnknown = s === "未知";
  return `<span class="tag-badge" title="${escapeHtml(f)}（点击复制完整标识）" data-v="${escapeHtml(f)}"
    style="display:inline-block; padding:2px 9px; cursor:pointer;
    border-radius:9999px; font-size:0.72rem; font-weight:700; white-space:nowrap;
    border:1px solid ${isUnknown ? "#e2e8f0" : "#fed7aa"};
    background:${isUnknown ? "#f8fafc" : "#fff7ed"}; color:${isUnknown ? "#94a3b8" : "#c2410c"};"
    onclick="copyTextValue(this.dataset.v, '商品标识')"
    >${escapeHtml(s)}</span>`;
}

function openOrderImg(src, fallback) {
  if (!src) return;
  const modal = document.getElementById("orderImgModal");
  const img = document.getElementById("orderImgLarge");
  img.dataset.fallback = fallback || "";
  img.style.visibility = "visible";
  // 原图 (如亚马逊 CDN) 加载失败时退回缩略图; 再失败提示
  img.onerror = function () {
    const fb = this.dataset.fallback;
    if (fb && this.src !== fb) {
      this.dataset.fallback = "";
      this.src = fb;
      return;
    }
    this.style.visibility = "hidden";
    showToast("图片加载失败，可尝试刷新重试", "error");
  };
  img.src = src;
  modal.style.display = "flex";
}

function closeOrderImg() {
  const modal = document.getElementById("orderImgModal");
  if (modal) modal.style.display = "none";
  const img = document.getElementById("orderImgLarge");
  if (img) {
    img.onerror = null;              // 先解绑, 避免清空 src 时触发「图片加载失败」提示
    img.removeAttribute("src");
    img.dataset.fallback = "";
  }
}

/* 操作列图标 (内联 SVG, 线条风格): view=详情 edit=补录 copy=复制 track=轨迹 */
const ROW_ICONS = {
  view: `<path d="M4 2h5l3 3v9H4z"/><path d="M9 2v3h3"/>
         <path d="M5.8 8h4.4M5.8 10.4h4.4"/>`,
  edit: `<path d="m10.6 3.4 2 2L7 11l-2.6.6L5 9z"/><path d="M3 14h10"/>`,
  copy: `<rect x="5.2" y="5.2" width="7" height="7" rx="1.6"/>
         <path d="M10.8 3.6h-6a1.6 1.6 0 0 0-1.6 1.6v6"/>`,
  track: `<path d="M12.2 6.8c0 3.2-4.2 6.4-4.2 6.4S3.8 10 3.8 6.8a4.2 4.2 0 1 1 8.4 0z"/>
          <circle cx="8" cy="6.8" r="1.5"/>`,
};

/* 套装二: 彩色徽章底 (row-act-view/edit/copy/track, 配色见 app.css) */
function rowIconBtn(kind, title, onclick, extraClass = "") {
  /* 不设 title: 避免鼠标悬停出现浏览器原生浮框 (仅保留 aria-label 供读屏) */
  return `<button class="btn btn-outline btn-sm row-act row-act-${kind}${extraClass}" type="button"
    aria-label="${escapeHtml(title)}" onclick="${onclick}">
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor"
      stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${ROW_ICONS[kind] || ""}</svg>
  </button>`;
}

/* 复制按钮 + 悬停浮层: 仅复制 (保持原效果) / 复制跳转 (复制完打开货代在线链接) */
function copySplitBtn(orderId) {
  return `<span class="copy-split">
    ${rowIconBtn("copy", "复制整行（可直接粘贴到在线表格）", `copyOrderRow(${orderId})`)}
    <span class="copy-split-menu">
      <button type="button" class="copy-split-item" onclick="copyOrderRow(${orderId})">仅复制</button>
      <button type="button" class="copy-split-item jump" onclick="copyOrderRowAndJump(${orderId})">复制跳转</button>
    </span>
  </span>`;
}

function renderOrderRows(tbody, rows) {
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="20" style="text-align:center; padding:40px; color:var(--text-muted);">
      🧾 暂无订单数据，点击右上角「🔄 批量更新」拉取</td></tr>`;
    syncOrderSelectionUI();
    return;
  }
  tbody.innerHTML = rows.map(o => `
    <tr data-oid="${o.id}">
      <td style="text-align:center; padding:8px 4px;">
        <input type="checkbox" class="order-row-check" value="${o.id}"
          ${orderState.selected.has(o.id) ? "checked" : ""}
          style="width:14px; height:14px; cursor:pointer;">
      </td>
      <td style="white-space:nowrap;">
        ${o.order_sn ? `<span class="copy-chip" data-v="${escapeHtml(o.order_sn)}"
            style="font-weight:700; color:#0f172a; font-size:0.84rem;"
            onclick="copyTextValue(this.dataset.v, '订单号')">${escapeHtml(o.order_sn)}</span>`
          : `<span style="color:#cbd5e1;">—</span>`}
      </td>
      <td style="text-align:center;">${orderImgCell(o)}</td>
      <td style="text-align:center;">${productCell(o.product_label_short, o.product_label)}</td>
      <td style="font-size:0.76rem; color:#334155; max-width:108px; white-space:nowrap; text-align:center;">
        ${o.sku ? `<span class="copy-chip" title="${escapeHtml(o.sku)}" data-v="${escapeHtml(o.sku)}"
            style="display:inline-block; max-width:86px; overflow:hidden; text-overflow:ellipsis;
                   white-space:nowrap; vertical-align:bottom; cursor:pointer;"
            onclick="copyTextValue(this.dataset.v, 'SKU')">${escapeHtml(o.sku)}</span>`
          : `<span style="color:#cbd5e1;">—</span>`}
      </td>
      <td title="${escapeHtml(cnyTip(o.order_amount))}"
        style="text-align:right; font-size:0.76rem; color:#334155; white-space:nowrap;">${fmtMoney(o.order_amount, o.currency)}</td>
      <td style="font-size:0.78rem; color:#475569; white-space:nowrap;">${escapeHtml((o.gmt_order || "").slice(0, 16) || "—")}</td>
      <td style="text-align:center; white-space:nowrap;">${statusChip(o.package_status, o.package_status_text)}${mergeChip(o)}</td>
      <td style="font-size:0.78rem; white-space:nowrap;">
        ${o.tracking_no ? `${trackJumpCell(o)}
            ${prevTrackingLine(o)}
            ${o.tracking_company ? `<div style="font-size:0.68rem; color:#94a3b8; margin-top:2px;">${escapeHtml(o.tracking_company)}</div>` : ""}`
          : `<span style="color:#cbd5e1;">—</span>`}
      </td>
      <td class="js-track-status" style="text-align:center; white-space:nowrap;">${trackChip(o.track_status_name)}</td>
      <td class="js-track-desc track-desc-cell">${trackSummaryCell(o)}</td>
      <td class="js-track-at track-time-cell" style="font-size:0.72rem; color:#64748b; text-align:center;">
        ${escapeHtml((o.track_refreshed_at || "").slice(0, 16) || "—")}
      </td>
      ${DOC_TYPES.map(dt => `<td class="doc-cell">${docCell(o, dt.key)}</td>`).join("")}
      <td style="text-align:center; padding:2px 2px;">
        <div style="display:flex; flex-direction:column; gap:2px; align-items:center;">
          <div style="display:flex; gap:4px;">
            ${rowIconBtn("view", "查看订单详情", `openOrderDetail(${o.id})`)}
            ${rowIconBtn("edit", "补录信息（采购日期 / 国内包裹数量 / 国内单号）",
              `openOrderSupplement(${o.id})`,
              isSupplemented(o) ? "" : " supp-pending")}
          </div>
          <div style="display:flex; gap:4px;">
            ${copySplitBtn(o.id)}
            ${o.tracking_no ? rowIconBtn("track", "查看运单轨迹", `openOrderTrack(${o.id})`) : ""}
          </div>
        </div>
      </td>
    </tr>`).join("");
  syncOrderSelectionUI();
}

/* ───────── 批量选择 ───────── */
function syncOrderSelectionUI() {
  const bar = document.getElementById("orderSelBar");
  const hint = document.getElementById("orderSelHint");
  const count = orderState.selected.size;
  if (bar) bar.style.display = count ? "inline-flex" : "none";
  if (hint) hint.innerHTML = `已选 <b>${count}</b> 单`;
  const all = document.getElementById("orderCheckAll");
  const boxes = [...document.querySelectorAll("#orderTableBody .order-row-check")];
  if (all) {
    all.checked = boxes.length > 0 && boxes.every(b => b.checked);
    all.indeterminate = boxes.some(b => b.checked) && !all.checked;
  }
}

function renderOrderPager() {
  const { page, pages, total } = orderState;
  document.getElementById("orderPageInfo").innerText =
    total ? `第 ${page} / ${pages} 页 · 共 ${total} 单` : "共 0 单";
  document.getElementById("orderPrevBtn").disabled = page <= 1;
  document.getElementById("orderNextBtn").disabled = pages === 0 || page >= pages;
}

function gotoOrderPage(delta) {
  const target = orderState.page + delta;
  if (target < 1 || (orderState.pages && target > orderState.pages)) return;
  orderState.page = target;
  loadOrders();
}

function resetOrderFilters() {
  ["orderKeyword", "orderDateFrom", "orderDateTo"].forEach(id => document.getElementById(id).value = "");
  ["orderStatus", "orderShop"].forEach(id => document.getElementById(id).value = "");
  orderState.page = 1;
  loadOrders();
}

/* ───────────── 详情 ───────────── */
async function openOrderDetail(id) {
  const modal = document.getElementById("orderDetailModal");
  const bodyEl = document.getElementById("orderDetailBody");
  document.getElementById("orderDetailTitle").innerText = "订单详情";
  document.getElementById("orderDetailSub").innerText = "加载中...";
  bodyEl.innerHTML = `<div style="text-align:center; padding:36px; color:#94a3b8;">⏳ 正在加载...</div>`;
  modal.style.display = "flex";
  try {
    const body = await orderApi(`/api/orders/${id}`);
    const o = body.data || {};
    const items = o.items || [];
    const raw = o.raw || {};
    const orderInfo = raw.orderInfo || {};
    const consignee = raw.consigneeInfo || {};
    const logistics = raw.logisticsAgentProductInfo || {};

    document.getElementById("orderDetailTitle").innerText = o.order_sn || "订单详情";
    document.getElementById("orderDetailSub").innerHTML =
      `${escapeHtml(o.platform_name || o.platform || "")} · ${escapeHtml(clipShopName(o))} · ${statusChip(o.package_status, o.package_status_text)}`;

    const infoRow = (label, value) =>
      `<div style="display:flex; justify-content:space-between; gap:12px; padding:5px 0; border-bottom:1px dashed #e2e8f0;">
         <span style="color:#64748b; font-size:0.78rem;">${label}</span>
         <span style="font-size:0.8rem; color:#0f172a; text-align:right;">${value || "—"}</span>
       </div>`;

    const itemCards = items.map(it => `
      <div style="display:flex; gap:10px; padding:10px; border:1px solid #e2e8f0; border-radius:8px; margin-bottom:8px;">
        <img src="${escapeHtml(it.picUrl || it.originalPicUrl || "")}" alt=""
          style="width:56px; height:56px; object-fit:cover; border-radius:6px; background:#f1f5f9; flex-shrink:0;"
          onerror="this.style.visibility='hidden'">
        <div style="flex:1; min-width:0;">
          <div style="font-size:0.8rem; color:#0f172a; line-height:1.45;">${escapeHtml(it.title || "—")}</div>
          <div style="font-size:0.72rem; color:#94a3b8; margin-top:4px;">
            SKU: ${escapeHtml(it.platformOuterSkuId || it.platformItemId || "—")}
            ${it.skuSubName ? " · " + escapeHtml(it.skuSubName) : ""}
          </div>
        </div>
        <div style="text-align:right; flex-shrink:0;">
          <div style="font-size:0.8rem; font-weight:700; color:#0f172a;">${fmtMoney(it.originalPrice, o.currency)}</div>
          <div style="font-size:0.72rem; color:#64748b;">× ${it.quantity || 0}</div>
        </div>
      </div>`).join("");

    // 运单号: 当前值 + 上一次值(删除线), 支持在详情内直接修改
    const prevNo = String(o.prev_tracking_no || "").trim();
    const curNo = String(o.tracking_no || "").trim();
    const trackingRow = `
      <div style="padding:5px 0; border-bottom:1px dashed #e2e8f0;">
        <div style="display:flex; justify-content:space-between; gap:12px;">
          <span style="color:#64748b; font-size:0.78rem;">运单号</span>
          <span style="font-size:0.8rem; text-align:right;">
            ${prevNo && prevNo !== curNo ? `<span
              style="color:#94a3b8; text-decoration:line-through; margin-right:6px;">${escapeHtml(prevNo)}</span>` : ""}
            <span id="orderTrackingCurrent" data-v="${escapeHtml(curNo)}"
              style="color:#0f172a; font-weight:700;">${curNo ? escapeHtml(curNo) : "—"}</span>
            ${Number(o.tracking_no_manual) === 1 ? `<span title="人工修正过, 妙手同步不会覆盖"
              style="font-size:0.66rem; color:#b45309; background:#fef3c7; border-radius:9999px;
              padding:1px 6px; margin-left:4px;">人工</span>` : ""}
            <button class="btn btn-outline btn-sm" type="button"
              style="padding:0 6px; font-size:0.68rem; margin-left:6px;"
              onclick="startEditTrackingNo()">✏️ 修改</button>
          </span>
        </div>
        <div id="orderTrackingEditBox" style="display:none; align-items:center; gap:6px; margin-top:6px;">
          <input type="text" id="orderTrackingInput" class="form-input" placeholder="输入新的运单号"
            style="flex:1; padding:4px 8px; font-size:0.76rem;"
            onkeydown="if(event.key==='Enter'){saveTrackingNo(${o.id})}">
          <button class="btn btn-primary btn-sm" type="button" style="padding:3px 10px; font-size:0.72rem;"
            onclick="saveTrackingNo(${o.id})">保存</button>
          <button class="btn btn-outline btn-sm" type="button" style="padding:3px 10px; font-size:0.72rem;"
            onclick="cancelEditTrackingNo()">取消</button>
        </div>
      </div>`;

    bodyEl.innerHTML = `
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:0 24px;">
        <div>
          <div style="font-weight:700; font-size:0.85rem; color:#334155; margin-bottom:6px;">📋 订单信息</div>
          ${infoRow("平台订单号", escapeHtml(o.order_sn))}
          ${infoRow("妙手包裹号", escapeHtml(o.app_package_no))}
          ${infoRow("平台 / 站点", escapeHtml((o.platform_name || o.platform || "") + (o.site ? " · " + o.site : "")))}
          ${infoRow("店铺", escapeHtml(clipShopName(o)))}
          ${infoRow("商品标识", escapeHtml(o.product_label))}
          ${infoRow("简版标识", productCell(o.product_label_short, o.product_label))}
          ${infoRow("平台状态", escapeHtml(o.platform_status))}
          ${infoRow("下单时间", escapeHtml(o.gmt_order))}
          ${infoRow("支付时间", escapeHtml(o.gmt_pay))}
          ${infoRow("发货时间", escapeHtml(o.gmt_delivery))}
          ${infoRow("最迟发货", escapeHtml(o.gmt_last_delivery))}
        </div>
        <div>
          <div style="font-weight:700; font-size:0.85rem; color:#334155; margin-bottom:6px;">💰 金额 / 收货 / 物流</div>
          ${infoRow("订单金额", fmtMoney(o.order_amount, o.currency))}
          ${infoRow("支付金额", fmtMoney(o.pay_amount, o.currency))}
          ${infoRow("商品金额", fmtMoney(o.product_amount, o.currency))}
          ${infoRow("平台佣金", fmtMoney(o.commission_fee, o.currency))}
          ${infoRow("收货地区", escapeHtml([consignee.countryName || consignee.country, consignee.state].filter(Boolean).join(" / ")))}
          ${trackingRow}
          ${infoRow("物流公司", escapeHtml(logistics.logisticsCompany || logistics.productName || "—"))}
          ${infoRow("采购日期", escapeHtml(o.purchase_date))}
          ${infoRow("国内包裹数", o.domestic_package_count ? String(o.domestic_package_count) : "")}
          ${infoRow("国内单号", escapeHtml(o.domestic_tracking_no))}
          ${infoRow("买家留言", escapeHtml(orderInfo.buyerMessage))}
          ${infoRow("备注", escapeHtml(orderInfo.appNote || orderInfo.sellerNote))}
        </div>
      </div>
      <div style="margin-top:16px;">
        <div style="font-weight:700; font-size:0.85rem; color:#334155; margin-bottom:8px;">📦 商品明细（${items.length}）</div>
        ${itemCards || `<div style="color:#94a3b8; font-size:0.8rem;">无商品明细</div>`}
      </div>`;
  } catch (e) {
    if (e.message !== "未登录") {
      document.getElementById("orderDetailSub").innerText = "加载失败";
      bodyEl.innerHTML = `<div style="text-align:center; padding:36px; color:#dc2626;">❌ ${escapeHtml(e.message)}</div>`;
    }
  }
}

function closeOrderDetail() {
  document.getElementById("orderDetailModal").style.display = "none";
}

/* ───────── 一键复制整行 (TSV + HTML 表格, 可直接粘贴到在线表格) ───────── */
/* 采购日期统一输出 YYYYMMDD (2026-10-03 / 2026/10/03 → 20261003) */
function fmtPurchaseDateYmd(v) {
  const s = String(v == null ? "" : v).trim();
  if (!s) return "";
  const m = s.match(/(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})/);
  if (m) return `${m[1]}${m[2].padStart(2, "0")}${m[3].padStart(2, "0")}`;
  const digits = s.replace(/\D/g, "");
  return digits.length >= 8 ? digits.slice(0, 8) : digits;
}

/* 产品图片链接: 优先放大图 */
function clipImageUrl(o) {
  const it = (o.items || [])[0] || {};
  return it.originalPicUrl || it.picUrl || o.cover_img_big || o.cover_img || "";
}

/* 产品名称及备注: 第 1 行 SKU, 第 2 行商品标识全称 */
function clipProductName(o) {
  const it = (o.items || [])[0] || {};
  const sku = String(o.sku || it.platformOuterSkuId || it.platformItemId
    || it.platformSkuId || "").trim();
  const label = String(o.product_label || it.title || "").trim();
  return [sku, label].filter(Boolean).join("\n");
}

/* 店铺名替换: 复制到表格时用对外店铺简称 (妙手店铺名带卖家 ID 后缀, 如 A3IM82P5RF6MRV-fe-JP) */
const CLIP_SHOP_ALIAS = { "A3IM82P5RF6MRV": "金梧汇辰" };
function clipShopName(o) {
  const name = String(o.shop_name || "").trim();
  if (!name) return "";
  if (CLIP_SHOP_ALIAS[name]) return CLIP_SHOP_ALIAS[name];
  const hit = Object.keys(CLIP_SHOP_ALIAS).find(k => name.includes(k));
  return hit ? CLIP_SHOP_ALIAS[hit] : name;
}

/* 复制列的顺序: 与目标在线表格的列顺序一致 (无值自动留空) */
/* type: image=下载图片后内嵌单元格; multiline=单元格内换行 */
const CLIP_COLUMNS = [
  { label: "采购日期", value: o => fmtPurchaseDateYmd(o.purchase_date) },
  { label: "仓库发货日期", value: () => "" },
  { label: "产品图片", type: "image", value: o => clipImageUrl(o) },
  { label: "产品名称及备注", type: "multiline", value: o => clipProductName(o) },
  { label: "国内包裹数量", value: o => (Number(o.domestic_package_count || 0) || "") + "" },
  { label: "国内单号", value: o => o.domestic_tracking_no },
  { label: "国际单号", value: o => o.tracking_no },
  { label: "订单号", value: o => o.order_sn },
  { label: "收件人名字", value: o => {
      const c = (o.raw && o.raw.consigneeInfo) || {};
      return c.name || c.receiverName || c.consigneeName || "";
    } },
  { label: "亚马逊售卖单价", value: o => {
      const it = (o.items || [])[0] || {};
      return it.originalPrice == null ? "" : it.originalPrice;
    } },
  { label: "换单号", value: () => "" },
  { label: "采购订单号", value: () => "" },
  { label: "店铺", value: o => clipShopName(o) },
  { label: "备注", value: o => {
      const oi = (o.raw && o.raw.orderInfo) || {};
      return oi.appNote || oi.sellerNote || oi.buyerMessage || "";
    } },
  { label: "与客户沟通", value: () => "" },
  { label: "出库重量", value: () => "" },
];

/* 写入剪贴板: 同时放 text/html(表格) 与 text/plain(TSV), 在线表格两种都能识别
   html 可为 Promise<Blob|string>: 图片需先下载, 用 Promise 保证仍在用户点击手势内写入 */
async function writeRichClipboard(html, text) {
  const toBlob = h => (h instanceof Blob ? h : new Blob([String(h)], { type: "text/html" }));
  if (navigator.clipboard && window.ClipboardItem && window.isSecureContext) {
    try {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": html instanceof Promise ? html.then(toBlob) : toBlob(html),
        "text/plain": new Blob([text], { type: "text/plain" }),
      })]);
      return true;
    } catch (e) {
      // 回退: 部分浏览器不支持 ClipboardItem 的 Promise 值, 等 HTML 就绪后再写一次
      try {
        const ready = html instanceof Promise ? await html : html;
        await navigator.clipboard.write([new ClipboardItem({
          "text/html": toBlob(ready),
          "text/plain": new Blob([text], { type: "text/plain" }),
        })]);
        return true;
      } catch (e2) { /* 继续回退到纯文本 */ }
    }
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* 继续回退 */ }
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed; left:-9999px; top:0;";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  document.body.removeChild(ta);
  return ok;
}

/* 单个单元格 HTML: 图片放 https 外链图 (Excel/WPS 粘贴时会自动下载嵌入),
   多行文本用 <br> 换行; 所有单元格统一水平/垂直居中 (在线文档粘贴后即居中) */
const CLIP_TD_CENTER = `align="center" style="text-align:center; vertical-align:middle;"`;

function clipCellHtml(col, raw) {
  if (col.type === "image") {
    return raw ? `<td ${CLIP_TD_CENTER}><img src="${escapeHtml(raw)}"
        width="80" height="80" style="width:80px;height:80px;"></td>`
      : `<td ${CLIP_TD_CENTER}></td>`;
  }
  if (col.type === "multiline") {
    return `<td align="center" style="text-align:center; vertical-align:middle; white-space:pre-wrap;">${
      escapeHtml(raw).replace(/\r?\n/g, "<br>")}</td>`;
  }
  return `<td ${CLIP_TD_CENTER}>${escapeHtml(raw.replace(/\s*\n\s*/g, " ").trim())}</td>`;
}

/* 单行 HTML 表格 */
function buildClipRowHtml(values) {
  return `<table><tbody><tr>${CLIP_COLUMNS.map((col, i) =>
    clipCellHtml(col, values[i] || "")).join("")}</tr></tbody></table>`;
}

/* 剪贴板纯文本: 单元格内换行替换成空格 (TSV 里换行会被识别成新行) */
function clipCellText(v) {
  return String(v == null ? "" : v).replace(/\s*\n\s*/g, " ").trim();
}

/* 复制单行订单: 未补录先弹框提醒, 补录完整直接复制
   jump=true (复制跳转): 复制成功后打开货代管理默认货代的在线链接 */
async function copyOrderRow(orderId, jump = false) {
  try {
    const body = await orderApi(`/api/orders/${orderId}`);
    const o = body.data || {};
    const missing = suppMissingFields(o);
    if (missing.length) { openSuppWarnModal(o, missing, jump); return false; }
    const ok = await doCopyOrderRow(o);
    if (!ok) return false;
    if (jump) await jumpToForwarderLink();
    else showToast(lastCopyHint, "success");
    return true;
  } catch (e) {
    if (e.message !== "未登录") showToast("复制失败: " + e.message, "error");
    return false;
  }
}

/* 复制跳转 (操作列悬停菜单) */
async function copyOrderRowAndJump(orderId) {
  await copyOrderRow(orderId, true);
}

/* 复制: 仅复制已勾选的订单 → 纯数据行表格 (不含表头), 可直接粘贴到在线文档
   未勾选先提示选择; 勾选中有未补录的则弹框列出缺项, 确认后再复制 */
async function copyOrdersRows(jump = false) {
  const ids = [...orderState.selected];
  if (!ids.length) { showToast("请先勾选要复制的订单", "error"); return; }
  if (ids.length > 100) { showToast("单次最多复制 100 单，请减少勾选", "error"); return; }
  let orders = [];
  try {
    const results = await Promise.all(ids.map(id =>
      orderApi(`/api/orders/${id}`).then(b => b.data).catch(() => null)));
    orders = results.filter(Boolean);
  } catch (e) {
    if (e.message !== "未登录") showToast("复制失败: " + e.message, "error");
    return;
  }
  if (!orders.length) { showToast("订单数据加载失败，请重试", "error"); return; }

  const pending = orders.filter(o => suppMissingFields(o).length);
  if (pending.length) { openBatchSuppWarn(pending, orders, jump); return; }
  const ok = await writeOrdersRows(orders, jump);
  if (ok && jump) await jumpToForwarderLink();
}

/* 复制跳转 (顶部工具栏): 勾选订单复制后打开货代在线链接 */
async function copyOrdersRowsAndJump() {
  await copyOrdersRows(true);
}

/* 实际写入剪贴板: 多行订单 (无表头), 粘贴到在线表格即成一整块数据
   silent=true 时不弹复制结果提示 (交给跳转逻辑合并提示) */
async function writeOrdersRows(orders, silent = false) {
  const rows = orders.map(o => CLIP_COLUMNS.map(c => {
    let v = "";
    try { v = c.value(o); } catch (e) { v = ""; }
    return String(v == null ? "" : v);
  }));
  const bodyRows = rows.map(values =>
    `<tr>${CLIP_COLUMNS.map((col, i) => clipCellHtml(col, values[i] || "")).join("")}</tr>`).join("");
  const html = `<table><tbody>${bodyRows}</tbody></table>`;
  const text = rows.map(r => r.map(clipCellText).join("\t")).join("\n");

  const ok = await writeRichClipboard(html, text);
  const pending = orders.filter(o => suppMissingFields(o).length).length;
  const extra = pending ? `；其中 ${pending} 单未补录` : "";
  if (!ok) { showToast("复制失败，请检查浏览器剪贴板权限", "error"); return false; }
  lastCopyHint = `已复制 ${orders.length} 单${extra}`;
  if (!silent) showToast(lastCopyHint, "success");
  return true;
}

/* 申诉导出: 按亚马逊「フルフィルメント記録」模板导出已勾选订单 (未勾选先提示选择) */
function exportOrdersAppealXlsx() {
  const ids = [...orderState.selected];
  if (!ids.length) { showToast("请先勾选要导出的订单", "error"); return; }
  if (ids.length > 200) { showToast("单次最多导出 200 单，请减少勾选", "error"); return; }
  showToast(`正在导出申诉表格 ${ids.length} 单...`);
  window.location.href = `/api/orders/export-appeal-xlsx?ids=${ids.join(",")}`;
}

/* 补录缺项: 采购日期 / 国内包裹数量 / 国内单号 (空数组表示已补录) */
function suppMissingFields(o) {
  const miss = [];
  if (!String(o.purchase_date || "").trim()) miss.push("采购日期");
  if (!(Number(o.domestic_package_count || 0) > 0)) miss.push("国内包裹数量");
  if (!String(o.domestic_tracking_no || "").trim()) miss.push("国内单号");
  return miss;
}

let suppWarnOrder = null;
let suppWarnBatch = null;   // 批量复制待确认: {pending:[未补录订单], orders:[全部订单]}
let suppWarnJump = false;   // 单行复制: 点「仍要复制」后是否继续跳转货代在线链接
let lastCopyHint = "";      // 最近一次复制的结果文案 (拼进跳转提示)

/* 批量复制前的未补录提醒: 列出未补录订单及缺项, 确认后仍可复制 */
function openBatchSuppWarn(pending, orders, jump = false) {
  suppWarnOrder = null;
  suppWarnBatch = { pending: pending, orders: orders };
  suppWarnJump = !!jump;
  const modal = document.getElementById("orderSuppWarnModal");
  if (!modal) {   // 兜底: 弹窗不存在时用 toast 提醒, 不复制
    showToast(`有 ${pending.length} 单未补录，请先补录再复制`, "error");
    return;
  }
  document.getElementById("suppWarnSub").innerText =
    `已选 ${orders.length} 单，其中 ${pending.length} 单未补录`;
  document.getElementById("suppWarnMissing").innerHTML =
    pending.slice(0, 20).map(o => {
      const miss = suppMissingFields(o);
      return `<div style="flex-basis:100%; display:flex; align-items:center; gap:5px; flex-wrap:wrap;">
        <span style="font-size:0.76rem; font-weight:700; color:#0f172a;">${
          escapeHtml(o.order_sn || o.app_package_no || o.id)}</span>
        ${miss.map(m => `<span style="display:inline-block; padding:1px 7px; border-radius:9999px;
          font-size:0.68rem; font-weight:700; background:#fef2f2; color:#dc2626;
          border:1px solid #fecaca;">缺 ${escapeHtml(m)}</span>`).join("")}
      </div>`;
    }).join("") + (pending.length > 20
      ? `<div style="flex-basis:100%; font-size:0.72rem; color:#94a3b8;">
          … 另有 ${pending.length - 20} 单未补录</div>`
      : "");
  const goBtn = document.getElementById("suppWarnGoBtn");
  if (goBtn) goBtn.style.display = "none";   // 批量场景不提供单条「去补录」
  modal.style.display = "flex";
}

function openSuppWarnModal(o, missing, jump = false) {
  suppWarnOrder = o;
  suppWarnBatch = null;
  suppWarnJump = !!jump;
  const goBtn = document.getElementById("suppWarnGoBtn");
  if (goBtn) goBtn.style.display = "";
  const modal = document.getElementById("orderSuppWarnModal");
  if (!modal) {   // 兜底: 弹窗不存在时用 toast 提醒, 不复制
    showToast(`尚未补录（缺 ${missing.join(" / ")}），请先补录`, "error");
    return;
  }
  document.getElementById("suppWarnSub").innerText =
    `订单号 ${o.order_sn || o.app_package_no || o.id || "—"}`;
  document.getElementById("suppWarnMissing").innerHTML = missing.map(m =>
    `<span style="display:inline-block; padding:2px 10px; border-radius:9999px; font-size:0.72rem;
      font-weight:700; background:#fef2f2; color:#dc2626; border:1px solid #fecaca;">缺 ${escapeHtml(m)}</span>`
  ).join("");
  modal.style.display = "flex";
}

function closeSuppWarnModal() {
  const m = document.getElementById("orderSuppWarnModal");
  if (m) m.style.display = "none";
  suppWarnOrder = null;
  suppWarnBatch = null;
  suppWarnJump = false;
}

function suppWarnGoSupplement() {
  const id = suppWarnOrder && suppWarnOrder.id;
  closeSuppWarnModal();
  if (id) openOrderSupplement(id);
}

async function suppWarnCopyAnyway() {
  const o = suppWarnOrder;
  const batch = suppWarnBatch;
  const jump = suppWarnJump;
  closeSuppWarnModal();
  if (batch) {
    const ok = await writeOrdersRows(batch.orders, jump);
    if (ok && jump) await jumpToForwarderLink();
    return;
  }
  if (o) {
    const ok = await doCopyOrderRow(o);
    if (ok && jump) await jumpToForwarderLink();
    else if (ok) showToast(lastCopyHint, "success");
  }
}

/* 实际写入剪贴板: 按 CLIP_COLUMNS 生成一行数据; 返回是否复制成功 */
async function doCopyOrderRow(o) {
  try {
    const values = CLIP_COLUMNS.map(c => {
      let v = "";
      try { v = c.value(o); } catch (e) { v = ""; }
      return String(v == null ? "" : v);
    });
    // 图片下载完成前先用纯文本兜底, 保证复制不阻塞
    const html = buildClipRowHtml(values);
    const text = values.map(clipCellText).join("\t");
    const ok = await writeRichClipboard(html, text);
    if (!ok) { showToast("复制失败，请检查浏览器剪贴板权限", "error"); return false; }
    lastCopyHint = `已复制 ${values.length} 个字段`;
    return true;
  } catch (e) {
    if (e.message !== "未登录") showToast("复制失败: " + e.message, "error");
    return false;
  }
}

/* 复制跳转: 打开「货代管理」默认货代的在线链接 (新标签页) */
let forwarderLinkCache = null;   // 会话内缓存, 避免每次点击都请求
async function jumpToForwarderLink() {
  let link = forwarderLinkCache;
  if (!link) {
    try {
      const body = await orderApi("/api/forwarders/default-link");
      link = body.data || null;
    } catch (e) {
      if (e.message !== "未登录") showToast("获取货代在线链接失败: " + e.message, "error");
      return;
    }
    forwarderLinkCache = link;
  }
  if (!link || !link.url) {
    showToast(lastCopyHint + "，但货代管理还没有登记「在线链接」", "error");
    return;
  }
  const opened = window.open(link.url, "_blank", "noopener");
  if (!opened) {   // 被浏览器拦截时给出可点击兜底提示
    showToast(`${lastCopyHint}；跳转被浏览器拦截，请允许弹窗后重试`, "error");
    return;
  }
  showToast(`${lastCopyHint}，已打开「${link.forwarder_name || "货代"}」在线链接`, "success");
}

/* ───────── 补录信息 (采购日期 / 国内包裹数量 / 国内单号) ───────── */
let supplementOrderId = 0;

async function openOrderSupplement(orderId) {
  const modal = document.getElementById("orderSupplementModal");
  const sub = document.getElementById("orderSuppSub");
  if (!modal) return;
  supplementOrderId = Number(orderId) || 0;
  sub.innerText = "加载中...";
  modal.style.display = "flex";
  try {
    const body = await orderApi(`/api/orders/${supplementOrderId}`);
    const o = body.data || {};
    sub.innerText = o.order_sn || "—";
    document.getElementById("supPurchaseDate").value = o.purchase_date || "";
    document.getElementById("supPackageCount").value = o.domestic_package_count || "";
    document.getElementById("supTrackingNo").value = o.domestic_tracking_no || "";
  } catch (e) {
    if (e.message !== "未登录") showToast("加载失败: " + e.message, "error");
  }
}

function closeOrderSupplement() {
  const modal = document.getElementById("orderSupplementModal");
  if (modal) modal.style.display = "none";
  supplementOrderId = 0;
}

async function saveOrderSupplement() {
  if (!supplementOrderId) return;
  const btn = document.getElementById("suppSaveBtn");
  const payload = {
    purchase_date: document.getElementById("supPurchaseDate").value || "",
    domestic_package_count: Number(document.getElementById("supPackageCount").value || 0),
    domestic_tracking_no: (document.getElementById("supTrackingNo").value || "").trim(),
  };
  if (!payload.purchase_date) { showToast("请选择采购日期", "error"); return; }
  if (!(payload.domestic_package_count > 0)) { showToast("请填写国内包裹数量", "error"); return; }
  if (!payload.domestic_tracking_no) { showToast("请填写国内单号", "error"); return; }

  btn.disabled = true;
  try {
    const body = await orderApi(`/api/orders/${supplementOrderId}/supplement`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast(body.msg || "补录信息已保存", "success");
    closeOrderSupplement();
    await loadOrders();
  } catch (e) {
    if (e.message !== "未登录") showToast("保存失败: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

/* ───────── 运单号人工修改 (保留上一次单号用于对比) ───────── */
function startEditTrackingNo() {
  const box = document.getElementById("orderTrackingEditBox");
  const input = document.getElementById("orderTrackingInput");
  const cur = document.getElementById("orderTrackingCurrent");
  if (!box || !input) return;
  input.value = (cur && cur.dataset.v) || "";
  box.style.display = "flex";
  input.focus();
  input.select();
}

function cancelEditTrackingNo() {
  const box = document.getElementById("orderTrackingEditBox");
  if (box) box.style.display = "none";
}

async function saveTrackingNo(orderId) {
  const input = document.getElementById("orderTrackingInput");
  const no = ((input && input.value) || "").trim();
  if (!no) { showToast("请输入运单号", "error"); return; }
  try {
    const body = await orderApi(`/api/orders/${orderId}/tracking-no`, {
      method: "POST",
      body: JSON.stringify({ tracking_no: no }),
    });
    showToast(body.msg || "运单号已更新", "success");
    await openOrderDetail(orderId);   // 详情重载: 展示 旧值(删除线) → 当前值
    await loadOrders();               // 列表同步
  } catch (e) {
    showToast("修改失败: " + e.message, "error");
  }
}

/* ───────────── 批量更新 (妙手订单 + 运单轨迹) ───────────── */
const TRACK_BATCH_SIZE = 20;      // 每批轨迹查询单数 (避免单请求过久)
const TRACK_MAX_PER_RUN = 1000;   // 单次批量更新轨迹上限
let syncRunning = false;          // 批量更新进行中 (此时禁止关闭弹窗)

function openSyncModal() {
  const box = document.getElementById("syncStatusChecks");
  if (!orderStatusOptions.length) {
    orderStatusOptions = [
      { value: "unpaid", label: "未付款" }, { value: "wait_confirmed", label: "待审核" },
      { value: "wait_seller_send", label: "待发货" }, { value: "wait_receiver_confirm", label: "已发货" },
      { value: "finished", label: "已完成" }, { value: "cancelled", label: "未发货退款关闭" },
      { value: "returned", label: "已发货退款" }, { value: "refunding", label: "售后中" },
    ];
  }
  box.innerHTML = orderStatusOptions.map(s => `
    <label style="display:inline-flex; align-items:center; gap:5px; font-size:0.8rem; color:#334155; cursor:pointer;">
      <input type="checkbox" value="${s.value}" checked style="width:14px; height:14px;"> ${escapeHtml(s.label)}
    </label>`).join("");
  document.getElementById("syncProgress").style.display = "none";
  document.getElementById("syncProgress").innerHTML = "";
  document.getElementById("syncStartBtn").disabled = false;
  document.getElementById("syncStartBtn").innerText = "开始更新";
  document.getElementById("orderSyncModal").style.display = "flex";
}

function closeSyncModal() {
  if (syncRunning) { showToast("正在批量更新，请稍候…", "error"); return; }  // 更新中不允许关闭
  document.getElementById("orderSyncModal").style.display = "none";
}

/* 批量更新轨迹: 按批次调用 /api/orders/tracks/refresh, 进度写回弹窗 */
async function refreshTracksInBatches(ids, progEl) {
  const list = (ids || []).slice(0, TRACK_MAX_PER_RUN);
  if (!list.length) return "没有需要更新轨迹的订单";
  let ok = 0, fail = 0;
  for (let i = 0; i < list.length; i += TRACK_BATCH_SIZE) {
    const chunk = list.slice(i, i + TRACK_BATCH_SIZE);
    const done = Math.min(i + chunk.length, list.length);
    if (progEl) progEl.innerHTML = `② 正在更新运单轨迹 ${done} / ${list.length} …`;
    try {
      const res = await orderApi("/api/orders/tracks/refresh", {
        method: "POST", body: JSON.stringify({ ids: chunk }),
      });
      const d = res.data || {};
      ok += (d.refreshed || []).length;
      fail += (d.failed || []).length;
    } catch (e) {
      if (e.message === "未登录") return `轨迹更新中断：登录已失效（已完成 ${ok} 单）`;
      fail += chunk.length;
    }
  }
  let msg = `轨迹更新完成：成功 ${ok} 单${fail ? `，失败 ${fail} 单` : ""}`;
  if ((ids || []).length > list.length) msg += `（超过 ${TRACK_MAX_PER_RUN} 单的部分未处理）`;
  return msg;
}

async function startOrderSync() {
  const statuses = [...document.querySelectorAll("#syncStatusChecks input:checked")].map(x => x.value);
  if (!statuses.length) { showToast("请至少选择一个订单状态", "error"); return; }
  const days = Number(document.getElementById("syncDays").value || 0);
  const withTrack = !!(document.getElementById("syncWithTrack") || {}).checked;
  const btn = document.getElementById("syncStartBtn");
  const prog = document.getElementById("syncProgress");
  syncRunning = true;
  btn.disabled = true;
  btn.innerText = "⏳ 同步订单...";
  prog.style.display = "block";
  prog.innerHTML = `① 正在从妙手拉取 ${statuses.length} 个状态的订单（单页 200 条、间隔 1.1 秒）…`;
  try {
    const body = await orderApi("/api/orders/sync", {
      method: "POST",
      body: JSON.stringify({ statuses, days }),
    });
    const d = body.data || {};
    const ids = Array.isArray(d.ids) ? d.ids : [];
    const summary = `✅ 订单同步完成：新增 ${d.inserted || 0} / 更新 ${d.updated || 0}`;
    prog.innerHTML = summary + (withTrack ? `<div style="margin-top:4px;">② 准备更新运单轨迹…</div>` : "");

    let trackMsg = "";
    if (withTrack) {
      btn.innerText = "⏳ 更新轨迹...";
      trackMsg = await refreshTracksInBatches(ids, prog);
    }
    await loadOrderFilters();
    orderState.page = 1;
    await loadOrders();
    prog.innerHTML = summary + (trackMsg ? `<div style="margin-top:4px;">${escapeHtml(trackMsg)}</div>` : "");
    showToast(trackMsg || body.msg, (d.failed && d.failed.length) ? "error" : "success");
    btn.innerText = "完成";
    setTimeout(() => closeSyncModal(), 1600);
  } catch (e) {
    if (e.message !== "未登录") {
      prog.innerHTML = `❌ 批量更新失败: ${escapeHtml(e.message)}`;
      showToast("批量更新失败: " + e.message, "error");
    }
    btn.innerText = "重试";
  } finally {
    syncRunning = false;        // 结束即解除关闭限制 (成功/失败都要复位)
    btn.disabled = false;
  }
}

/* ───────────── 初始化 ───────────── */
(async function initOrdersPage() {
  // 行选择 (事件委托: 表格重渲染后仍生效)
  document.getElementById("orderTableBody").addEventListener("change", e => {
    const cb = e.target.closest(".order-row-check");
    if (!cb) return;
    const id = Number(cb.value);
    if (cb.checked) orderState.selected.add(id);
    else orderState.selected.delete(id);
    syncOrderSelectionUI();
  });
  // 当前页全选 / 取消
  document.getElementById("orderCheckAll").addEventListener("change", function () {
    const checked = this.checked;
    document.querySelectorAll("#orderTableBody .order-row-check").forEach(cb => {
      cb.checked = checked;
      const id = Number(cb.value);
      if (checked) orderState.selected.add(id);
      else orderState.selected.delete(id);
    });
    syncOrderSelectionUI();
  });

  // 附件弹窗: 勾选 / 全选
  document.getElementById("orderDocBody").addEventListener("change", e => {
    const cb = e.target.closest(".doc-row-check");
    if (!cb) return;
    const id = Number(cb.value);
    if (cb.checked) docState.selected.add(id);
    else docState.selected.delete(id);
    syncDocSelectionUI();
  });
  document.getElementById("orderDocCheckAll").addEventListener("change", function () {
    const checked = this.checked;
    document.querySelectorAll("#orderDocBody .doc-row-check").forEach(cb => {
      cb.checked = checked;
      const id = Number(cb.value);
      if (checked) docState.selected.add(id);
      else docState.selected.delete(id);
    });
    syncDocSelectionUI();
  });

  await loadOrderFilters();
  await loadOrders();
})();
