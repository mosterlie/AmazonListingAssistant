/* 店小秘订单发货截止预警页逻辑: 状态栏 + 预警列表 + 30s 自动刷新 */
"use strict";

let dxmFilterMode = "all";
let dxmStatusCache = null;
let dxmTimer = null;

// ───────────────── 工具 ─────────────────
function dxmEsc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function dxmFmtRemaining(minutes) {
  if (minutes === null || minutes === undefined || minutes < 0) return "未知";
  if (minutes <= 0) return "已超时";
  const d = Math.floor(minutes / 1440), h = Math.floor((minutes % 1440) / 60), m = minutes % 60;
  if (d > 0) return `${d}天${h}小时`;
  if (h > 0) return `${h}小时${m}分`;
  return `${m}分钟`;
}

function dxmFmtTime(ts) {
  if (!ts) return "-";
  const d = new Date(ts.replace(" ", "T"));
  if (isNaN(d)) return ts;
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// ───────────────── 筛选 ─────────────────
function setDxmFilter(mode, el) {
  dxmFilterMode = mode;
  document.querySelectorAll(".dxm-filter").forEach(x => x.classList.remove("active"));
  if (el) el.classList.add("active");
  loadDxmOrders();
}

// ───────────────── 状态栏 ─────────────────
async function loadDxmStatus() {
  try {
    const res = await fetch("/api/dxm-orders/status");
    const result = await res.json();
    if (result.code !== 0 || !result.data) return;
    const st = result.data;
    dxmStatusCache = st;

    const statusEl = document.getElementById("dxmStatusText");
    const loginBadge = document.getElementById("dxmLoginBadge");
    const banner = document.getElementById("dxmLoginBanner");
    const last = st.last_log;

    let line = "";
    if (st.running) {
      line = `📡 采集中 (${st.running_trigger})...`;
    } else if (last) {
      line = `最近采集: ${dxmFmtTime(last.started_at)} · 订单 ${last.orders_total} 单 · ${last.status}`;
      if (last.message) line += ` · ${last.message.slice(0, 60)}`;
      // 下轮倒计时
      if (st.config && st.config.scan_enabled && last.status === "success") {
        const nextMs = new Date(last.started_at.replace(" ", "T")).getTime() + (st.config.scan_interval_minutes || 60) * 60000;
        const mins = Math.max(0, Math.round((nextMs - Date.now()) / 60000));
        line += ` · 下轮约 ${mins} 分钟后`;
      }
    } else {
      line = "尚未采集过 (启动后自动按间隔采集)";
    }
    statusEl.innerText = line;

    // 登录状态徽章 + 横幅
    const loginOk = !last || !String(last.login_status || "").startsWith("failed");
    loginBadge.style.display = "inline-flex";
    if (loginOk) {
      loginBadge.className = "dxm-badge ok";
      loginBadge.innerText = "🟢 店小秘登录态正常";
      banner.style.display = "none";
    } else {
      loginBadge.className = "dxm-badge red";
      loginBadge.innerText = "🔴 需人工登录";
      document.getElementById("dxmLoginBannerText").innerText = String(last.login_status || "").replace("failed: ", "");
      banner.style.display = "block";
    }

    // 预警统计
    const c = st.counts || {};
    dxmSetBadge("dxmCountRed", c.red, `🔴 红色 ${c.red}`);
    dxmSetBadge("dxmCountYellow", c.yellow, `🟡 黄色 ${c.yellow}`);
    dxmSetBadge("dxmCountExpired", c.expired, `⚫ 已超时 ${c.expired}`);
  } catch (err) {
    document.getElementById("dxmStatusText").innerText = `状态加载失败: ${err.message}`;
  }
}

function dxmSetBadge(id, n, text) {
  const el = document.getElementById(id);
  if (!el) return;
  if (n > 0) { el.style.display = "inline-flex"; el.innerText = text; }
  else { el.style.display = "none"; }
}

// ───────────────── 订单列表 ─────────────────
async function loadDxmOrders() {
  const tbody = document.getElementById("dxmOrdersBody");
  try {
    const params = new URLSearchParams();
    if (dxmFilterMode === "alert") { params.set("pending_only", "true"); }
    if (dxmFilterMode === "yellow") params.set("alert_level", "1");
    if (dxmFilterMode === "red") params.set("alert_level", "2");
    if (dxmFilterMode === "expired") params.set("alert_level", "2");
    const kw = (document.getElementById("dxmKeyword")?.value || "").trim();
    if (kw) params.set("keyword", kw);
    params.set("page_size", "200");
    const res = await fetch(`/api/dxm-orders/list?${params.toString()}`);
    const result = await res.json();
    if (result.code !== 0 || !result.data) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:#dc2626; padding:24px;">加载失败: ${dxmEsc(result.msg || "未知错误")}</td></tr>`;
      return;
    }
    let items = result.data.items || [];
    // 客户端二级筛选: 仅预警 / 已超时
    if (dxmFilterMode === "alert") items = items.filter(x => x.alert_level >= 1);
    if (dxmFilterMode === "expired") items = items.filter(x => x.remaining_minutes_now <= 0);
    document.getElementById("dxmTotal").innerText = result.data.total || 0;

    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:#94a3b8; padding:24px;">暂无符合条件的订单</td></tr>`;
      return;
    }
    const warnH = (dxmStatusCache && dxmStatusCache.config && dxmStatusCache.config.warn_hours) || 24;
    const dangerH = (dxmStatusCache && dxmStatusCache.config && dxmStatusCache.config.danger_hours) || 6;
    const warnMin = warnH * 60, dangerMin = dangerH * 60;

    tbody.innerHTML = items.map(x => {
      const rem = x.remaining_minutes_now;
      const expired = rem !== undefined && rem !== null && rem <= 0;
      let rowCls = "", remColor = "#16a34a", levelHtml = `<span class="dxm-badge ok">正常</span>`;
      if (expired) {
        rowCls = "dxm-row-expired"; remColor = "#94a3b8";
        levelHtml = `<span class="dxm-badge grey">⚫ 已超时</span>`;
      } else if (x.alert_level === 2) {
        rowCls = "dxm-row-red"; remColor = "#dc2626";
        levelHtml = `<span class="dxm-badge red">🔴 红色</span>`;
      } else if (x.alert_level === 1) {
        rowCls = "dxm-row-yellow"; remColor = "#d97706";
        levelHtml = `<span class="dxm-badge yellow">🟡 黄色</span>`;
      } else if (rem < warnMin) {
        remColor = "#d97706";
      }
      return `<tr class="${rowCls}">
        <td style="font-weight:600; color:#1e293b;">${dxmEsc(x.order_no)}</td>
        <td>${dxmEsc(x.shop_name)}</td>
        <td style="text-align:center;">${dxmEsc(x.site)}</td>
        <td>${dxmEsc(x.order_status)}</td>
        <td><span class="dxm-remaining" style="color:${remColor};">${dxmFmtRemaining(rem)}</span></td>
        <td>${dxmEsc(x.deadline_at || "-")}</td>
        <td style="text-align:center;">${levelHtml}</td>
        <td style="color:#94a3b8; font-size:0.76rem;">${dxmFmtTime(x.last_seen_at)}</td>
      </tr>`;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:#dc2626; padding:24px;">加载异常: ${dxmEsc(err.message)}</td></tr>`;
  }
}

// ───────────────── 立即采集 ─────────────────
async function runDxmSync() {
  const btn = document.getElementById("dxmRunBtn");
  if (btn) { btn.disabled = true; btn.innerText = "⏳ 启动中..."; }
  try {
    const res = await fetch("/api/dxm-orders/run", { method: "POST" });
    const result = await res.json();
    if (result.code === 0) {
      showToast("📡 采集批次已启动, 请稍候刷新查看结果", "success");
      setTimeout(() => { loadDxmStatus(); loadDxmOrders(); }, 15000);
    } else {
      showToast(result.msg || "启动失败", "error");
    }
  } catch (err) {
    showToast(`启动异常: ${err.message}`, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = `<span>📡</span> 立即采集`; }
  }
}

// ───────────────── 入口 ─────────────────
function loadDxmAll() { loadDxmStatus(); loadDxmOrders(); }

document.addEventListener("DOMContentLoaded", () => {
  loadDxmAll();
  if (dxmTimer) clearInterval(dxmTimer);
  dxmTimer = setInterval(loadDxmAll, 30000);   // 30s 自动刷新
});
