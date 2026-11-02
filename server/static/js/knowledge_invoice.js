/**
 * 知识库 · 发票解析面板前端逻辑
 * 同时被知识库页面的「🧾 发票解析」子菜单面板与独立页面 /knowledge/invoice-parse 复用
 * 页面结构见 templates/partials/knowledge_invoice_panel.html
 */

const INV_ALLOWED = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".pdf"];
const INV_MAX_SIZE = 20 * 1024 * 1024;
const invState = { file: null, parsing: false, timer: null, startedAt: 0 };

function pickInvoiceFile() {
  if (invState.parsing) return;
  const input = document.getElementById("invInput");
  input.value = "";
  input.click();
}

function invExt(name) {
  const i = String(name || "").lastIndexOf(".");
  return i < 0 ? "" : String(name).slice(i).toLowerCase();
}

function invSizeText(bytes) {
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(2) + " MB";
  if (bytes >= 1024) return (bytes / 1024).toFixed(0) + " KB";
  return bytes + " B";
}

function setInvoiceFile(file) {
  if (!file) return;
  const ext = invExt(file.name);
  if (!INV_ALLOWED.includes(ext)) {
    showInvoiceError("「" + file.name + "」格式不支持，请上传发票图片(jpg/png/webp)或 PDF");
    return;
  }
  if (file.size > INV_MAX_SIZE) {
    showInvoiceError("「" + file.name + "」超过 20MB 上限");
    return;
  }
  clearBanner();
  invState.file = file;
  document.getElementById("invDrop").style.display = "none";
  document.getElementById("invFile").style.display = "flex";
  document.getElementById("invFileName").innerText = file.name;
  document.getElementById("invFileMeta").innerText = ext.toUpperCase().replace(".", "") +
    " · " + invSizeText(file.size);
  const thumb = document.getElementById("invFileThumb");
  if (ext === ".pdf") {
    thumb.innerHTML = `<div class="inv-file-ico">📄</div>`;
  } else {
    const url = URL.createObjectURL(file);
    thumb.innerHTML = `<img src="${url}" alt="">`;
  }
  document.getElementById("invParseBtn").disabled = false;
  document.getElementById("invResultCard").style.display = "none";
}

function clearInvoiceFile() {
  if (invState.parsing) return;
  invState.file = null;
  document.getElementById("invFile").style.display = "none";
  document.getElementById("invFileThumb").innerHTML = "";
  document.getElementById("invDrop").style.display = "block";
  document.getElementById("invParseBtn").disabled = true;
  clearBanner();
}

function clearBanner() {
  const b = document.getElementById("invBanner");
  b.className = "inv-banner";
  b.innerHTML = "";
}

function showInvoiceError(msg) {
  const b = document.getElementById("invBanner");
  b.className = "inv-banner error";
  b.innerHTML = "❌ " + escapeInvoiceHtml(msg);
}

function escapeInvoiceHtml(text) {
  return String(text == null ? "" : text).replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function startInvTimer() {
  invState.startedAt = Date.now();
  const b = document.getElementById("invBanner");
  const tick = () => {
    const sec = Math.round((Date.now() - invState.startedAt) / 1000);
    b.className = "inv-banner loading";
    b.innerHTML = `⏳ 正在识别发票… 已用 ${sec} 秒（模型识图通常 3~15 秒，请勿关闭页面）`;
  };
  tick();
  invState.timer = setInterval(tick, 500);
}

function stopInvTimer() {
  if (invState.timer) { clearInterval(invState.timer); invState.timer = null; }
}

async function startInvoiceParse() {
  if (invState.parsing || !invState.file) return;
  const btn = document.getElementById("invParseBtn");
  invState.parsing = true;
  btn.disabled = true;
  btn.innerText = "⏳ 识别中...";
  document.getElementById("invResultCard").style.display = "none";
  clearBanner();
  startInvTimer();

  const fd = new FormData();
  fd.append("file", invState.file);
  try {
    const resp = await fetch("/api/invoices/parse", { method: "POST", body: fd });
    if (resp.status === 401) { window.location.href = "/login"; return; }
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok || body.code !== 0) {
      throw new Error(body.detail || body.msg || ("解析失败 HTTP " + resp.status));
    }
    renderInvoiceResult(body.data || {});
    clearBanner();
  } catch (e) {
    showInvoiceError(e.message || "解析失败，请重试");
  } finally {
    stopInvTimer();
    invState.parsing = false;
    btn.disabled = false;
    btn.innerText = "开始解析";
  }
}

function invMoney(value, currency) {
  const num = Number(value || 0);
  const text = num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (currency ? currency + " " : "") + text;
}

function renderInvoiceResult(data) {
  const inv = data.invoice || {};
  const cur = inv.currency || "";
  const rows = [
    ["发票类型", inv.doc_type],
    ["发票代码", inv.invoice_code],
    ["发票号码", inv.invoice_number],
    ["开票日期", inv.invoice_date],
    ["销售方", inv.seller_name],
    ["销售方税号", inv.seller_tax_id],
    ["购买方", inv.buyer_name],
    ["购买方税号", inv.buyer_tax_id],
    ["金额(不含税)", invMoney(inv.amount_excl_tax, cur), "money"],
    ["税额", invMoney(inv.tax_amount, cur), "money"],
    ["价税合计", invMoney(inv.total_amount, cur), "money"],
    ["价税合计(大写)", inv.total_in_words],
    ["备注", inv.remark],
  ];
  document.getElementById("invKv").innerHTML = rows.map(([label, value, cls]) =>
    `<div class="inv-kv-item">
      <span class="inv-kv-label">${escapeInvoiceHtml(label)}</span>
      <span class="inv-kv-value ${cls || ""}">${value ? escapeInvoiceHtml(value) : "—"}</span>
    </div>`).join("");

  const items = data.items || [];
  const table = document.getElementById("invItemsTable");
  if (!items.length) {
    table.innerHTML = `<tr><td style="color:#94a3b8; padding:14px 8px;">发票中未解析到明细行</td></tr>`;
  } else {
    table.innerHTML = `
      <thead><tr>
        <th style="width:32px;">#</th><th>货物或应税劳务名称</th><th>规格型号</th>
        <th>单位</th><th style="text-align:right;">数量</th>
        <th style="text-align:right;">单价</th><th style="text-align:right;">金额</th><th>税率</th>
      </tr></thead>
      <tbody>${items.map((it, i) => `
        <tr>
          <td>${i + 1}</td>
          <td>${escapeInvoiceHtml(it.name || "—")}</td>
          <td>${escapeInvoiceHtml(it.spec || "—")}</td>
          <td>${escapeInvoiceHtml(it.unit || "—")}</td>
          <td class="num">${Number(it.quantity || 0).toLocaleString("zh-CN")}</td>
          <td class="num">${Number(it.unit_price || 0).toFixed(2)}</td>
          <td class="num">${invMoney(it.amount, "")}</td>
          <td>${escapeInvoiceHtml(it.tax_rate || "—")}</td>
        </tr>`).join("")}</tbody>`;
  }

  try {
    document.getElementById("invRaw").innerText = JSON.stringify(data, null, 2);
  } catch (e) {
    document.getElementById("invRaw").innerText = String(data.raw_text || "");
  }
  document.getElementById("invResultMeta").innerText =
    `${data.pages || 1} 页 · ${data.model || "workbuddy"} · ${(data.duration_ms || 0) / 1000}s`;
  document.getElementById("invResultCard").style.display = "block";
}

// ============================================================================
// 初始化: 绑定文件选择与拖拽上传 (面板可能位于隐藏的子菜单中, 不影响事件绑定)
// ============================================================================
function initInvoicePanel() {
  const input = document.getElementById("invInput");
  const drop = document.getElementById("invDrop");
  if (!input || !drop || input.dataset.bound === "1") return;
  input.dataset.bound = "1";

  input.addEventListener("change", function () {
    if (this.files && this.files[0]) setInvoiceFile(this.files[0]);
  });

  ["dragenter", "dragover"].forEach(evt => drop.addEventListener(evt, e => {
    e.preventDefault();
    drop.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach(evt => drop.addEventListener(evt, e => {
    e.preventDefault();
    drop.classList.remove("dragging");
  }));
  drop.addEventListener("drop", e => {
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) setInvoiceFile(file);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initInvoicePanel);
} else {
  initInvoicePanel();
}
