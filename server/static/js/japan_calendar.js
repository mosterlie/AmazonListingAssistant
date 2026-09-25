/**
 * 日本节假日日历页前端逻辑
 * 月历渲染 (节假日/周末/连休标注) + 临近节日列表 + 提醒配置 (仅管理员)
 */
(function () {
  "use strict";

  const isAdmin = document.getElementById("jcSaveBtn") !== null;
  const state = { year: 0, month: 0 };

  function esc(s) {
    return String(s === null || s === undefined ? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function toast(msg, type = "success") {
    if (typeof showToast === "function") { showToast(msg, type); return; }
    const t = document.createElement("div");
    t.className = `toast-msg toast-${type}`;
    t.innerText = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3500);
  }

  async function api(url, options) {
    const res = await fetch(url, options || {});
    if (res.status === 401) { location.href = "/login"; throw new Error("未登录"); }
    const result = await res.json();
    if (result.detail) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail));
    return result;
  }

  function pad(n) { return String(n).padStart(2, "0"); }
  function todayKey() {
    const d = new Date();
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  // ═══════════════════ 状态条 ═══════════════════
  async function loadStatus() {
    try {
      const result = await api("/api/jp-holidays/status");
      const d = result.data || {};
      document.getElementById("jcTotalNum").innerText = d.total ?? 0;
      const years = (d.years || []).map(y => `${y.y}年 ${y.n} 条`).join(" · ");
      document.getElementById("jcYearBreakdown").innerText = years ? `(${years})` : "";
      const ls = d.last_sync;
      document.getElementById("jcLastSync").innerText =
        ls ? `${ls.date || ""} ${String(ls.time || "").slice(11, 16)}`.trim() : "未同步";
      const lr = d.last_reminder;
      document.getElementById("jcLastReminder").innerText =
        lr ? `${lr.date || ""} ${String(lr.time || "").slice(11, 16)} (${lr.status || lr.trigger || "—"})`.trim() : "未发送";
      document.getElementById("jcUpCount").innerText = (d.upcoming || []).length;

      renderUpcoming(d.upcoming || []);
      if (isAdmin && d.config) {
        document.getElementById("jcEmailEnabled").checked = !!d.config.email_enabled;
        document.getElementById("jcAdvanceDays").value = d.config.advance_days ?? 7;
        document.getElementById("jcMailTo").value = (d.config.mail_to || []).join(", ");
      }
    } catch (e) {
      toast(`加载状态失败: ${e.message}`, "error");
    }
  }

  // ═══════════════════ 临近节日列表 ═══════════════════
  function renderUpcoming(items) {
    const box = document.getElementById("jcUpList");
    if (!items.length) {
      box.innerHTML = `<p style="color:var(--text-muted); font-size:0.82rem; margin:0;">✅ 未来 90 天内无法定节假日</p>`;
      return;
    }
    box.innerHTML = items.map(x => {
      const chip = x.is_major
        ? `<span class="jc-up-chip major">大节日 · 连休${x.break_days}天</span>`
        : (x.break_days > 1 ? `<span class="jc-up-chip break">连休${x.break_days}天</span>`
                            : `<span class="jc-up-chip single">单日</span>`);
      const range = x.break_days > 1 ? `${x.break_start} ~ ${x.break_end}` : x.date;
      return `<div class="jc-up-item ${x.is_major ? "jc-major" : ""}">
        <span class="jc-up-date">${esc(x.date.slice(5))}</span>
        <span style="font-size:0.78rem; color:var(--text-muted); white-space:nowrap;">${esc(x.weekday)}</span>
        <div style="flex:1; min-width:0;">
          <div style="font-weight:700; font-size:0.86rem;">${esc(x.local_name || x.name)}</div>
          <div style="font-size:0.72rem; color:#94a3b8;">${esc(range)} · ${esc(x.name)}</div>
        </div>
        ${chip}
      </div>`;
    }).join("");
  }

  // ═══════════════════ 月历 ═══════════════════
  async function loadCalendar() {
    const grid = document.getElementById("jcDaysGrid");
    try {
      const result = await api(`/api/jp-holidays/calendar?year=${state.year}&month=${state.month}`);
      const d = result.data || {};
      document.getElementById("jcMonthTitle").innerText = `${d.year} 年 ${d.month} 月`;
      const tKey = todayKey();
      const blanks = d.first_weekday; // 周一为第 0 列
      let html = "";
      for (let i = 0; i < blanks; i++) html += `<div class="jc-day" style="border:none; background:transparent;"></div>`;
      grid.innerHTML = html + (d.days || []).map(day => {
        const cls = ["jc-day"];
        if (day.is_weekend) cls.push("jc-weekend");
        if (day.holiday_name) cls.push("jc-holiday");
        if (day.date === tKey) cls.push("jc-today");
        const holEn = day.holiday_name && !/^[\u0000-\u00ff\u3000-\u9fff\uf900-\ufaff]+$/.test(day.holiday_name)
          ? `<div class="jc-hol-en">${esc(day.holiday_name)}</div>` : "";
        return `<div class="${cls.join(" ")}">
          <div class="jc-num">${parseInt(day.date.slice(8), 10)}</div>
          ${day.holiday_name ? `<div class="jc-hol-name">${esc(day.holiday_name)}</div>${holEn}` : ""}
        </div>`;
      }).join("");
    } catch (e) {
      grid.innerHTML = `<div style="grid-column:1/-1; color:#dc2626; font-size:0.85rem;">日历加载失败: ${esc(e.message)}</div>`;
    }
  }

  function shiftMonth(delta) {
    let m = state.month + delta, y = state.year;
    if (m < 1) { m = 12; y--; }
    if (m > 12) { m = 1; y++; }
    state.year = y; state.month = m;
    loadCalendar();
  }

  // ═══════════════════ 配置操作 (管理员) ═══════════════════
  async function saveConfig() {
    const payload = {
      email_enabled: document.getElementById("jcEmailEnabled").checked,
      advance_days: parseInt(document.getElementById("jcAdvanceDays").value, 10) || 7,
      mail_to: document.getElementById("jcMailTo").value.trim(),
    };
    try {
      await api("/api/jp-holidays/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      toast("提醒配置已保存");
    } catch (e) {
      toast(`保存失败: ${e.message}`, "error");
    }
  }

  async function testEmail() {
    const btn = document.getElementById("jcTestBtn");
    btn.disabled = true; btn.innerText = "发送中...";
    try {
      const payload = {
        config: {
          email_enabled: true,
          advance_days: parseInt(document.getElementById("jcAdvanceDays").value, 10) || 7,
          mail_to: document.getElementById("jcMailTo").value.trim(),
        }
      };
      const result = await api("/api/jp-holidays/test-email", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      toast(result.msg || "测试邮件已发送");
    } catch (e) {
      toast(`测试邮件失败: ${e.message}`, "error");
    } finally {
      btn.disabled = false; btn.innerText = "📧 测试邮件";
    }
  }

  async function syncNow() {
    const btn = document.getElementById("jcSyncBtn");
    btn.disabled = true; btn.innerText = "同步中...";
    try {
      const result = await api("/api/jp-holidays/sync", { method: "POST" });
      toast(result.msg || "日历已同步");
      loadStatus(); loadCalendar();
    } catch (e) {
      toast(`同步失败: ${e.message}`, "error");
    } finally {
      btn.disabled = false; btn.innerText = "🔄 立即同步";
    }
  }

  // ═══════════════════ 初始化 ═══════════════════
  const now = new Date();
  state.year = now.getFullYear();
  state.month = now.getMonth() + 1;
  document.getElementById("jcPrevMonth").addEventListener("click", () => shiftMonth(-1));
  document.getElementById("jcNextMonth").addEventListener("click", () => shiftMonth(1));
  document.getElementById("jcThisMonth").addEventListener("click", () => {
    state.year = now.getFullYear(); state.month = now.getMonth() + 1; loadCalendar();
  });
  document.getElementById("jcRefreshBtn").addEventListener("click", () => { loadStatus(); loadCalendar(); });
  if (isAdmin) {
    document.getElementById("jcSaveBtn").addEventListener("click", saveConfig);
    document.getElementById("jcTestBtn").addEventListener("click", testEmail);
    document.getElementById("jcSyncBtn").addEventListener("click", syncNow);
  }
  loadStatus();
  loadCalendar();
})();
