/**
 * 通用任务卡片渲染器 (告警任务/提醒任务共用统一配置模板)
 * 卡片结构由后端下发的 form 模板 (sections → fields) 驱动:
 * 新增任务/提醒类型只需在后端 TASK_FORMS / REMINDER_FORMS 登记, 前端零改动。
 * 页面侧只需: createTaskCards({wrapId, apiPath, presentation, showRun}) + 个性化展示声明。
 */

// ───── 通用工具 ─────
function atEsc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function atToast(msg, type = "success") {
  if (typeof showToast === "function") { showToast(msg, type); return; }
  const toast = document.createElement("div");
  toast.className = `toast-msg toast-${type}`;
  toast.innerText = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

function togglePwVisibility(btn, inputId) {
  const inp = document.getElementById(inputId);
  if (!inp) return;
  const show = inp.type === "password";
  inp.type = show ? "text" : "password";
  btn.textContent = show ? "🙈" : "👁";
}

function fmtLogTime(s) {
  if (!s) return "—";
  return String(s).replace("T", " ").slice(0, 19);
}

function runBadgeText(running, trigger) {
  if (running) return `🟢 运行中 (${trigger === "manual" ? "手动" : trigger === "scheduled" ? "定时" : trigger || "?"})`;
  return "⚪ 空闲";
}

function batchStatusText(st) {
  const map = { success: "✅ 成功", partial: "🟡 部分成功", failed: "❌ 失败", running: "⏳ 运行中", skipped: "⏭ 跳过", sent: "✅ 已发送" };
  return map[st] || (st || "—");
}

const BADGE_TONE_STYLE = {
  run: "background:#f0fdf4; color:#15803d; border-color:#bbf7d0;",
  ok: "background:#f0fdf4; color:#15803d; border-color:#bbf7d0;",
  warn: "background:#fffbeb; color:#b45309; border-color:#fde68a;",
  danger: "background:#fef2f2; color:#b91c1c; border-color:#fecaca;",
  muted: "background:#f1f5f9; color:#64748b; border-color:#cbd5e1;",
  idle: "background:#f1f5f9; color:#475569; border-color:#cbd5e1;"
};

function badgeHtml(b) {
  return `<span class="tag-badge" style="${BADGE_TONE_STYLE[b.tone] || BADGE_TONE_STYLE.idle}">${b.text}</span>`;
}

// ═══════════════════ 任务卡片工厂 ═══════════════════
function createTaskCards(opts) {
  const { wrapId, apiPath, presentation = {}, showRun = false } = opts;
  const state = { tasks: [] };
  const presentOf = (key) => presentation[key] || {};
  const taskName = (key) => state.tasks.find(x => x.key === key)?.name || key;
  const fieldId = (key, fieldKey) => `at-${key}-${fieldKey}`;

  function fieldsOf(key) {
    const t = state.tasks.find(x => x.key === key);
    return (((t || {}).form || {}).sections || []).flatMap(sec => sec.fields || []);
  }

  function findFieldByRole(key, role) {
    return fieldsOf(key).find(f => f.role === role) || null;
  }

  // ───── 渲染 ─────
  function fieldHtml(t, f, inlineSwitch) {
    const id = fieldId(t.key, f.key);
    const w = "width:100%;";

    if (f.type === "switch") {
      const box = `<label class="switch-label"${f.title ? ` title="${atEsc(f.title)}"` : ""}>` +
        `<input type="checkbox" id="${id}"> ${inlineSwitch ? atEsc(f.label || "") : atEsc(f.switch_text || "")}</label>`;
      if (inlineSwitch) {
        return box + (f.hint ? `<small style="color:var(--text-muted); font-size:0.8rem;">${atEsc(f.hint)}</small>` : "");
      }
      return `<div class="form-group" style="margin-bottom:8px;"><label class="form-label">${atEsc(f.label || "")}</label>${box}</div>`;
    }

    let ctrl;
    if (f.type === "select") {
      ctrl = `<select class="form-input" id="${id}" style="${w}">` +
        (f.options || []).map(o => `<option value="${atEsc(o[0])}">${atEsc(o[1])}</option>`).join("") + `</select>`;
    } else if (f.type === "password") {
      const acts = f.actions || [];
      const btns = [];
      if (acts.includes("toggle")) {
        btns.push(`<button type="button" class="btn btn-outline btn-sm" onclick="togglePwVisibility(this, '${id}')" title="显示/隐藏" style="padding:6px 10px;">👁</button>`);
      }
      if (acts.includes("test_login")) {
        btns.push(`<button type="button" class="btn btn-outline btn-sm" data-action="test_login" data-key="${t.key}" style="padding:8px 14px; white-space:nowrap;">🔐 测试登录</button>`);
      }
      ctrl = `<div style="display:flex; gap:8px; align-items:center;">` +
        `<input type="password" class="form-input" id="${id}" autocomplete="new-password" style="flex:1;">${btns.join("")}</div>`;
    } else {
      const type = f.type === "number" ? "number" : (f.type === "time" ? "time" : "text");
      const attrs = [f.min != null ? `min="${f.min}"` : "", f.max != null ? `max="${f.max}"` : "",
        f.step != null ? `step="${f.step}"` : ""].filter(Boolean).join(" ");
      const withBtn = (f.actions || []).includes("test_email");
      const inp = `<input type="${type}" class="form-input" id="${id}" ${attrs} placeholder="${atEsc(f.placeholder || "")}" style="${withBtn ? "flex:1;" : w}">`;
      ctrl = withBtn
        ? `<div style="display:flex; gap:8px; align-items:center;">${inp}<button type="button" class="btn btn-outline btn-sm" data-action="test_email" data-key="${t.key}" style="padding:8px 14px; white-space:nowrap;">📨 测试邮件</button></div>`
        : inp;
    }
    return `<div class="form-group"><label class="form-label">${atEsc(f.label || "")}</label>${ctrl}</div>`;
  }

  function sectionHtml(t, sec) {
    const isGrid = !!sec.cols;
    const layout = isGrid
      ? `display:grid; grid-template-columns:${typeof sec.cols === "number" ? `repeat(${sec.cols}, 1fr)` : sec.cols}; gap:14px;`
      : `display:flex; gap:14px; align-items:center; flex-wrap:wrap; margin-bottom:6px;`;
    const fields = (sec.fields || []).map(f => fieldHtml(t, f, !isGrid)).join("");
    return `<div style="font-weight:700; font-size:0.9rem; margin:10px 0 8px;">${atEsc(sec.title || "")}</div>` +
      `<div style="${layout}">${fields}</div>` +
      (sec.help ? `<small style="color:var(--text-muted); font-size:0.78rem; display:block; margin-bottom:12px;">${atEsc(sec.help)}</small>` : "");
  }

  function taskCardHtml(t) {
    const present = presentOf(t.key);
    const desc = present.descHtml || atEsc(t.desc || "");
    const sections = ((t.form || {}).sections || []).map(sec => sectionHtml(t, sec)).join("");
    return `<div class="form-card alert-task-card" id="task-${t.key}">
      <div class="card-header">
        <div class="card-title">
          <div class="card-title-icon">${t.icon || "🔔"}</div>
          <span>${atEsc(t.name || t.key)}</span>
        </div>
        <div class="task-status-row" id="badges-${t.key}"></div>
      </div>
      <div class="card-body">
        <p style="font-size:0.84rem; color:var(--text-muted); margin-bottom:14px;">${desc}</p>
        ${sections}
        <div class="last-log-box" id="log-${t.key}" style="display:none;"></div>
        <div style="display:flex; gap:10px; align-items:center; margin-top:14px; flex-wrap:wrap;">
          <button class="btn btn-primary" type="button" data-action="save" data-key="${t.key}">💾 保存配置</button>
          ${showRun ? `<button class="btn btn-outline" type="button" data-action="run" data-key="${t.key}">▶️ 立即执行采集</button>` : ""}
          ${t.email_note ? `<small style="color:var(--text-muted); font-size:0.78rem;">📧 ${atEsc(t.email_note)}</small>` : ""}
        </div>
      </div>
    </div>`;
  }

  function commonLogHtml(last, metricsFn) {
    const trigger = last.trigger_type ? ` · ${last.trigger_type === "manual" ? "手动" : "定时"}` : "";
    const dur = last.duration_ms ? ` · 耗时 ${(last.duration_ms / 1000).toFixed(1)}s` : "";
    const metrics = metricsFn ? ` · ${metricsFn(last)}` : "";
    return `<b>最近批次</b> (#${last.id} · ${batchStatusText(last.status)}${trigger}) · ` +
      `开始 ${fmtLogTime(last.started_at)} · 结束 ${fmtLogTime(last.finished_at)}${dur}${metrics}` +
      (last.message ? `<br><span style="color:#94a3b8;">${atEsc(String(last.message).slice(0, 200))}</span>` : "");
  }

  function fillTask(t) {
    const present = presentOf(t.key);

    const row = document.getElementById(`badges-${t.key}`);
    if (row) row.innerHTML = (present.badges ? present.badges(t) : []).map(badgeHtml).join("");

    for (const f of fieldsOf(t.key)) {
      const el = document.getElementById(fieldId(t.key, f.key));
      if (!el) continue;
      const v = (t.config || {})[f.key];
      if (f.type === "switch") {
        el.checked = (v === undefined || v === null) ? (f.def !== false) : !!v;
      } else {
        el.value = (v === undefined || v === null) ? (f.def !== undefined ? f.def : "") : v;
      }
    }

    const box = document.getElementById(`log-${t.key}`);
    if (box) {
      let html = "";
      if (present.logHtml) {
        html = present.logHtml(t) || "";
      } else {
        const last = (t.status || {}).last_log;
        html = last ? commonLogHtml(last, present.logMetrics) : "";
      }
      box.style.display = html ? "block" : "none";
      box.innerHTML = html;
    }
  }

  // ───── 收集 / 保存 / 执行 / 测试 ─────
  function collectTask(key) {
    const out = {};
    for (const f of fieldsOf(key)) {
      const el = document.getElementById(fieldId(key, f.key));
      if (!el) continue;
      if (f.type === "switch") {
        out[f.key] = !!el.checked;
      } else if (f.type === "number") {
        const n = parseFloat(el.value);
        out[f.key] = isNaN(n) ? (f.def !== undefined ? f.def : 0) : n;
      } else {
        out[f.key] = (el.value || "").trim();
      }
    }
    return out;
  }

  async function saveTaskConfig(key, config, btn) {
    const origin = btn ? btn.innerText : "";
    if (btn) { btn.disabled = true; btn.innerText = "⏳ 保存中..."; }
    try {
      const res = await fetch(`${apiPath}/${key}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config })
      });
      const result = await res.json();
      if (res.ok && result.code === 0) {
        atToast(`✅ ${taskName(key)}配置已保存`);
        load();
      } else {
        atToast(`保存失败: ${result.detail || result.msg || "未知错误"}`, "error");
      }
    } catch (err) {
      atToast(`保存异常: ${err.message}`, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.innerText = origin; }
    }
  }

  async function runTaskNow(key, btn) {
    const origin = btn ? btn.innerText : "";
    if (btn) { btn.disabled = true; btn.innerText = "⏳ 启动中..."; }
    try {
      const res = await fetch(`${apiPath}/${key}/run`, { method: "POST" });
      const result = await res.json();
      if (res.ok && result.code === 0) {
        atToast(`▶️ ${result.msg || "采集批次已启动"} (稍后刷新查看进度)`);
        setTimeout(load, 2500);
      } else {
        atToast(result.msg || result.detail || "启动失败", "error");
      }
    } catch (err) {
      atToast(`启动异常: ${err.message}`, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.innerText = origin; }
    }
  }

  async function testTaskLogin(key, btn) {
    const origin = btn ? btn.innerText : "";
    if (btn) { btn.disabled = true; btn.innerText = "⏳ 检测中..."; }
    try {
      const res = await fetch(`${apiPath}/${key}/test-login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: collectTask(key) })
      });
      const result = await res.json();
      if (res.ok && result.code === 0) {
        atToast(`✅ ${result.msg || "登录态正常"}`);
      } else {
        atToast(`⚠️ ${result.msg || result.detail || "登录失败"}`, "error");
      }
    } catch (err) {
      atToast(`测试登录异常: ${err.message}`, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.innerText = origin; }
    }
  }

  async function testTaskEmail(key, btn) {
    const cfg = collectTask(key);
    const mailToField = findFieldByRole(key, "mail_to");
    const to = mailToField ? (cfg[mailToField.key] || "").trim() : "";
    if (!to) { atToast("请先填写提醒收件人再发送测试邮件", "error"); return; }
    const origin = btn ? btn.innerText : "";
    if (btn) { btn.disabled = true; btn.innerText = "⏳ 发送中..."; }
    const enableField = findFieldByRole(key, "enable");
    if (enableField) cfg[enableField.key] = true;  // 测试时强制开启, 不落库
    try {
      const res = await fetch(`${apiPath}/${key}/test-email`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: cfg })
      });
      const result = await res.json();
      if (res.ok && result.code === 0) {
        atToast(`📨 测试邮件已发送至 ${to} (测试通过后请记得点「保存配置」)`);
      } else {
        atToast(`发送失败: ${result.detail || result.msg || "未知错误"}`, "error");
      }
    } catch (err) {
      atToast(`发送异常: ${err.message}`, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.innerText = origin; }
    }
  }

  async function onCardAction(e) {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const key = btn.dataset.key, action = btn.dataset.action;
    if (action === "save") await saveTaskConfig(key, collectTask(key), btn);
    else if (action === "run") await runTaskNow(key, btn);
    else if (action === "test_login") await testTaskLogin(key, btn);
    else if (action === "test_email") await testTaskEmail(key, btn);
  }

  async function load() {
    try {
      const res = await fetch(apiPath);
      const result = await res.json();
      if (result.code !== 0 || !Array.isArray(result.data)) {
        atToast(`加载失败: ${result.msg || "未知错误"}`, "error");
        return;
      }
      state.tasks = result.data;
      const wrap = document.getElementById(wrapId);
      if (wrap) wrap.innerHTML = state.tasks.map(taskCardHtml).join("");
      state.tasks.forEach(fillTask);
    } catch (err) {
      atToast(`加载异常: ${err.message}`, "error");
    }
  }

  document.getElementById(wrapId)?.addEventListener("click", onCardAction);

  return { state, load, taskName, collectTask };
}
