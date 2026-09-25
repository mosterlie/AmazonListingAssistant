/**
 * 告警中心页前端逻辑 (全员)
 * 顶部统计卡 + 过滤器 + 统一告警列表分页
 */

const acState = { page: 1, pageSize: 50, total: 0 };

function acEsc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function acToast(msg, type = "success") {
  if (typeof showToast === "function") { showToast(msg, type); return; }
  const toast = document.createElement("div");
  toast.className = `toast-msg toast-${type}`;
  toast.innerText = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ═══════════════════ 统计卡 ═══════════════════
async function loadSummary() {
  try {
    const res = await fetch("/api/alerts/summary");
    const result = await res.json();
    if (result.code !== 0 || !result.data) return;
    const d = result.data;

    const fwdN = document.getElementById("statFwdNum");
    if (fwdN) fwdN.innerText = d.forwarder?.today_alerts ?? 0;
    const fwdSub = document.getElementById("statFwdSub");
    const fl = d.forwarder?.last_log;
    if (fwdSub) {
      if (fl) {
        const stMap = { success: "成功", partial: "部分成功", failed: "失败", running: "运行中", skipped: "跳过" };
        fwdSub.innerText = `最近批次: ${fl.biz_date || ""} ${stMap[fl.status] || fl.status || "—"} · 采集 ${fl.docs_ok ?? 0}/${fl.docs_total ?? 0}`;
      } else {
        fwdSub.innerText = "最近批次: 无";
      }
    }

    const yN = document.getElementById("statYellowNum");
    if (yN) yN.innerText = d.dxm?.yellow ?? 0;
    const rN = document.getElementById("statRedNum");
    if (rN) rN.innerText = (d.dxm?.red ?? 0) + (d.dxm?.expired ?? 0);
    const dxmSub = document.getElementById("statDxmSub");
    const dl = d.dxm?.last_log;
    if (dxmSub) {
      if (dl) {
        const stMap = { success: "成功", partial: "部分成功", failed: "失败", running: "运行中", skipped: "跳过" };
        dxmSub.innerText = `最近批次: ${String(dl.started_at || "").slice(0, 16)} ${stMap[dl.status] || dl.status || "—"} · ${dl.orders_total ?? 0} 单`;
      } else {
        dxmSub.innerText = "最近批次: 无";
      }
    }
    const cSub = document.getElementById("statCancelledSub");
    if (cSub) cSub.innerText = `已取消订单: ${d.dxm?.cancelled ?? 0} (不参与预警)`;

    const dN = document.getElementById("statDigestNum");
    const dSub = document.getElementById("statDigestSub");
    const dg = d.digest?.last;
    if (dN && dSub) {
      if (dg) {
        dN.innerText = dg.date || "—";
        const ok = String(dg.status || "") === "sent";
        dN.style.color = ok ? "#15803d" : "#dc2626";
        dSub.innerText = `${dg.time || ""} · ${ok ? "✅ 发送成功" : dg.status || "—"}`;
      } else {
        dN.innerText = "未发送";
        dN.style.color = "#94a3b8";
        dSub.innerText = "每日汇总邮件尚未发送过";
      }
    }
  } catch (err) {
    acToast(`加载统计异常: ${err.message}`, "error");
  }
}

// ═══════════════════ 列表 ═══════════════════
function acFilters() {
  return {
    source: document.getElementById("acSourceSelect")?.value || "",
    biz_date: document.getElementById("acDateInput")?.value || "",
    alert_level: document.getElementById("acLevelSelect")?.value || "",
    keyword: (document.getElementById("acKeywordInput")?.value || "").trim()
  };
}

async function loadAlerts() {
  const f = acFilters();
  const qs = new URLSearchParams({
    page: acState.page, page_size: acState.pageSize,
    keyword: f.keyword
  });
  if (f.source) qs.set("source", f.source);
  if (f.biz_date) qs.set("biz_date", f.biz_date);
  if (f.alert_level !== "") qs.set("alert_level", f.alert_level);

  const tbody = document.getElementById("acTableBody");
  if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text-muted);">⏳ 加载中...</td></tr>`;
  try {
    const res = await fetch(`/api/alerts/list?${qs.toString()}`);
    const result = await res.json();
    if (result.code !== 0 || !result.data) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:#dc2626;">加载失败: ${acEsc(result.msg || "未知错误")}</td></tr>`;
      return;
    }
    const data = result.data;
    acState.total = data.total || 0;
    const totalBadge = document.getElementById("acTotalBadge");
    if (totalBadge) totalBadge.innerText = `共 ${acState.total} 条`;
    const totalPages = Math.max(1, Math.ceil(acState.total / acState.pageSize));
    if (acState.page > totalPages) acState.page = totalPages;
    const pageInfo = document.getElementById("acPageInfo");
    if (pageInfo) pageInfo.innerText = `第 ${acState.page} / ${totalPages} 页`;

    if (!tbody) return;
    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:28px; color:var(--text-muted);">✅ 暂无符合条件的告警信息</td></tr>`;
      return;
    }
    tbody.innerHTML = data.items.map((it) => {
      const lv = it.level === 2 ? "lv2" : "lv1";
      const lvText = it.source === "dxm" ? (it.type || "预警") : "🔴 超期未发货";
      const srcCls = it.source === "forwarder" ? "fwd" : "dxm";
      const srcIcon = it.source === "forwarder" ? "🚢" : "📦";
      let detail = "";
      if (it.source === "forwarder") {
        detail = `货代: ${acEsc(it.detail?.forwarder_name || "—")} · 采购日期 ${acEsc(it.detail?.purchase_date || "—")} ·
          <b style="color:#dc2626;">未发货 ${acEsc(it.detail?.days_elapsed ?? "—")} 天</b> · 表: ${acEsc(it.detail?.sheet_name || "—")}`;
      } else {
        detail = `店铺: ${acEsc(it.detail?.shop_name || "—")} · 站点 ${acEsc(it.detail?.site || "—")} ·
          <b style="color:${it.level === 2 ? "#dc2626" : "#d97706"};">剩余 ${acEsc(it.detail?.remaining || "—")}</b> · 截止 ${acEsc(it.detail?.deadline_at || "—")} · ${acEsc(it.detail?.order_status || "")}`;
      }
      return `<tr>
        <td style="text-align:center;"><span class="source-chip ${srcCls}">${srcIcon} ${acEsc(it.source_name || "")}</span></td>
        <td style="text-align:center;"><span class="level-chip ${lv}">${acEsc(lvText)}</span></td>
        <td style="font-weight:600; color:#0f172a; max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${acEsc(it.title)}">${acEsc(it.title)}</td>
        <td style="color:#475569; font-size:0.8rem; max-width:380px;">${detail}</td>
        <td style="text-align:center; color:#64748b;">${acEsc(it.biz_date || "—")}</td>
        <td style="text-align:center; color:#64748b; font-size:0.8rem;">${acEsc(String(it.ts || "—").slice(0, 16))}</td>
      </tr>`;
    }).join("");
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:#dc2626;">加载异常: ${acEsc(err.message)}</td></tr>`;
  }
}

// ═══════════════════ 初始化 ═══════════════════
document.addEventListener("DOMContentLoaded", () => {
  loadSummary();
  loadAlerts();

  document.getElementById("acRefreshBtn")?.addEventListener("click", () => {
    loadSummary();
    loadAlerts();
  });
  document.getElementById("acSearchBtn")?.addEventListener("click", () => {
    acState.page = 1;
    loadAlerts();
  });
  document.getElementById("acResetBtn")?.addEventListener("click", () => {
    const s = document.getElementById("acSourceSelect");
    const d = document.getElementById("acDateInput");
    const l = document.getElementById("acLevelSelect");
    const k = document.getElementById("acKeywordInput");
    if (s) s.value = "";
    if (d) d.value = "";
    if (l) l.value = "";
    if (k) k.value = "";
    acState.page = 1;
    loadAlerts();
  });
  document.getElementById("acPrevBtn")?.addEventListener("click", () => {
    if (acState.page > 1) { acState.page--; loadAlerts(); }
  });
  document.getElementById("acNextBtn")?.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil(acState.total / acState.pageSize));
    if (acState.page < totalPages) { acState.page++; loadAlerts(); }
  });
  document.getElementById("acKeywordInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); acState.page = 1; loadAlerts(); }
  });
});
