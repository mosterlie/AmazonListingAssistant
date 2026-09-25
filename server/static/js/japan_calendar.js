/**
 * 日本节假日日历页前端逻辑
 * 月历渲染 (节假日/周末/连休标注) + 临近节日列表 + 提醒配置 (仅管理员)
 */
(function () {
  "use strict";

  const isAdmin = document.getElementById("jcSyncBtn") !== null;
  const state = { year: 0, month: 0 };

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
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

  // ═══════════════════ 月历 (6个月并排, 2行×3列) ═══════════════════
  const MONTH_COUNT = 6;
  function addMonths(y, m, delta) {
    let t = y * 12 + (m - 1) + delta;
    return { year: Math.floor(t / 12), month: (t % 12 + 12) % 12 + 1 };
  }
  // 连休分组: 法定祝日或周末相邻连续, 总天数 ≥3 (含3日) 且组内至少含 1 个法定祝日 → 连休
  // (纯周末2天不算连休; 周末+祝日连成 3 天以上即为一目了然的连续休假)
  function calcBreaks(days) {
    const brkSet = new Set();       // 属于连休组的全部日期
    const brkStart = new Map();     // 组首日期 -> 连休总天数
    let run = [];
    const flush = () => {
      if (run.length >= 3 && run.some(x => x.holiday_name)) {
        run.forEach(x => brkSet.add(x.date));
        brkStart.set(run[0].date, run.length);
      }
      run = [];
    };
    for (const day of (days || [])) {
      if (day.holiday_name || day.is_weekend) run.push(day);
      else flush();
    }
    flush();
    return { brkSet, brkStart };
  }
  function renderMonth(index, year, month) {
    const grid = document.getElementById(`jcDaysGrid_${index}`);
    const title = document.getElementById(`jcMonthTitle_${index}`);
    if (!grid) return;
    return api(`/api/jp-holidays/calendar?year=${year}&month=${month}`)
      .then(result => {
        const d = result.data || {};
        title.innerText = `${d.year} 年 ${d.month} 月`;
        const tKey = todayKey();
        const { brkSet, brkStart } = calcBreaks(d.days);
        let html = "";
        for (let i = 0; i < (d.first_weekday || 0); i++) html += `<div class="jc-day" style="border:none; background:transparent;"></div>`;
        html += (d.days || []).map(day => {
          const cls = ["jc-day"];
          if (day.is_weekend) cls.push("jc-weekend");
          if (day.holiday_name) cls.push("jc-holiday");
          if (brkSet.has(day.date)) cls.push("jc-brk");
          const isToday = day.date === tKey;
          if (isToday) cls.push("jc-big-day");
          const isBrkStart = brkStart.has(day.date);
          if (isBrkStart) cls.push("jc-brk-start");
          const holEn = day.holiday_name && !/^[\u0000-\u00ff\u3000-\u9fff\uf900-\ufaff]+$/.test(day.holiday_name)
            ? `<div class="jc-hol-en">${esc(day.holiday_name)}</div>` : "";
          const brkBadge = (isBrkStart && !isToday)
            ? `<div class="jc-break-badge">連休${brkStart.get(day.date)}天</div>` : "";
          return `<div class="${cls.join(" ")}">
            <div class="jc-num">${parseInt(day.date.slice(8), 10)}</div>
            ${isToday ? `<div class="jc-today-badge">今</div>` : ""}
            ${brkBadge}
            ${day.holiday_name ? `<div class="jc-hol-name">${esc(day.holiday_name)}</div>${holEn}` : ""}
          </div>`;
        }).join("");
        grid.innerHTML = html;
      })
      .catch(e => {
        grid.innerHTML = `<div style="grid-column:1/-1; color:#dc2626; font-size:0.8rem;">加载失败: ${esc(e.message)}</div>`;
      });
  }
  async function loadCalendar() {
    const jobs = [];
    let { year, month } = state;
    for (let i = 0; i < MONTH_COUNT; i++) {
      jobs.push(renderMonth(i, year, month));
      const next = addMonths(year, month, 1);
      year = next.year; month = next.month;
    }
    await Promise.all(jobs);
  }

  function shiftMonth(delta) {
    const next = addMonths(state.year, state.month, delta);
    state.year = next.year; state.month = next.month;
    loadCalendar();
  }

  // 整页翻页: 前移/后移一次翻 6 个月 (一整个页面)
  function shiftPage(delta) { shiftMonth(delta * MONTH_COUNT); }

  // ═══════════════════ 同步 (管理员) ═══════════════════
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
  document.getElementById("jcPrevMonth").addEventListener("click", () => shiftPage(-1));
  document.getElementById("jcNextMonth").addEventListener("click", () => shiftPage(1));
  document.getElementById("jcThisMonth").addEventListener("click", () => {
    state.year = now.getFullYear(); state.month = now.getMonth() + 1; loadCalendar();
  });
  document.getElementById("jcRefreshBtn").addEventListener("click", () => { loadStatus(); loadCalendar(); });
  if (isAdmin) {
    document.getElementById("jcSyncBtn").addEventListener("click", syncNow);
  }
  loadStatus();
  loadCalendar();
})();
