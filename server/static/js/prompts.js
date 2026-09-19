/**
 * 提示词模板管理前端逻辑 (知识库子菜单: 提示词模板)
 * 管理员维护多套提示词模板 (增删改)；所有用户可查阅、查看全文、一键复制
 * 注意: 本页面同时加载 knowledge.js (已定义全局 showToast), 此处使用独立命名避免覆盖
 */

const promptsState = {
  templates: [],
  editingId: null, // null=新增模式, 数字=编辑模式
  paramValues: {} // { [模板id]: { 参数名: 已填值 } } 行内填参缓存
};

function promptToast(msg, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast-msg toast-${type}`;
  toast.innerText = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ============================================================================
// 子菜单切换 (网站导航 | 提示词模板)
// ============================================================================
function initKbSubnav() {
  const nav = document.getElementById("kbSubnav");
  if (!nav) return;
  nav.addEventListener("click", (e) => {
    const btn = e.target.closest(".kb-subnav-item");
    if (!btn || !btn.dataset.tab) return;
    document.querySelectorAll(".kb-subnav-item").forEach(b => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".kb-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === btn.dataset.tab));
    if (btn.dataset.tab === "prompts" && promptsState.templates.length === 0) loadPrompts();
  });
}

// ============================================================================
// 加载与渲染
// ============================================================================
async function loadPrompts() {
  try {
    const res = await fetch("/api/prompts");
    const result = await res.json();
    if (result.code === 0 && Array.isArray(result.data)) {
      promptsState.templates = result.data;
      renderPromptTable();
    } else {
      throw new Error(result.msg || "接口返回异常");
    }
  } catch (err) {
    const tbody = document.getElementById("promptTableBody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:24px; color:#ef4444;">❌ 加载提示词模板失败: ${err.message}</td></tr>`;
  }
}

function renderPromptTable() {
  const tbody = document.getElementById("promptTableBody");
  const badge = document.getElementById("promptCountBadge");
  if (!tbody) return;

  const isAdmin = !!window.IS_ADMIN;
  tbody.innerHTML = "";
  if (badge) badge.innerText = `共 ${promptsState.templates.length} 套模板`;

  if (promptsState.templates.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:28px; color:var(--text-muted);">${isAdmin ? "暂无提示词模板，请点击右上角「➕ 新增模板」添加" : "暂无提示词模板，请联系管理员维护"}</td></tr>`;
    return;
  }

  promptsState.templates.forEach((item, idx) => {
    const tr = document.createElement("tr");
    const contentEscaped = escapeHtml(item.content);
    const varNames = extractPromptVars(item.content);
    const hasVars = varNames.length > 0;
    const varBadge = hasVars ? `<span class="tag-badge" style="background:#fdf4ff; color:#9333ea; border-color:#f0abfc; font-size:0.72rem; padding:1px 6px; margin-left:6px;">🧩 ${varNames.length} 参数</span>` : "";

    // 含参模板: 内容行即实时生成预览 (红色占位/绿色已填) + 参数输入行, 共两行
    const savedVals = promptsState.paramValues[item.id] || {};
    const paramInputsHtml = hasVars ? `
      <div style="display:flex; flex-wrap:wrap; gap:6px 10px; margin-top:6px; align-items:center;">
        ${varNames.map(name => `
          <label style="display:inline-flex; align-items:center; gap:5px; margin:0;">
            <span style="color:#dc2626; font-weight:700; font-size:0.78rem; white-space:nowrap;">${escapeHtml(name)}:</span>
            <input type="text" class="form-input prompt-row-var-input" data-pid="${item.id}" data-var="${escapeHtml(name)}"
              value="${escapeHtml(savedVals[name] || "")}" placeholder="填入${escapeHtml(name)}"
              style="width:150px; font-size:0.8rem; padding:4px 8px; border:1.5px solid #f0abfc; background:#fffafa;">
          </label>`).join("")}
      </div>` : "";

    const contentHtml = hasVars
      ? `<div class="prompt-gen-preview prompt-clamp" data-pid="${item.id}" style="font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size:0.84rem; line-height:1.6; color:#334155; word-break:break-word;"></div>`
      : `<span class="prompt-clamp" title="${escapeHtml(item.content)}" style="color:#475569; font-size:0.85rem; font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; line-height:1.5; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; max-width:520px;">${contentEscaped}</span>`;

    tr.innerHTML = `
      <td style="text-align:center; font-weight:600; color:#64748b;">${idx + 1}</td>
      <td><span class="prompt-name-cell">📝 ${escapeHtml(item.name)}${varBadge}</span></td>
      <td style="color:#475569; font-size:0.85rem;">${escapeHtml(item.description || "—")}</td>
      <td>
        ${contentHtml}
        ${paramInputsHtml}
      </td>
      <td class="prompt-action-cell">
        <button class="btn btn-primary btn-sm" style="padding:4px 10px; font-size:0.78rem; background:#8b5cf6; border-color:#8b5cf6; font-weight:700;" onclick="copyGeneratedPrompt(${item.id})" title="${hasVars ? "按行内已填参数生成并复制完整提示词" : "复制提示词全文"}">📋 复制使用</button>
        ${isAdmin ? `
        <button class="btn btn-outline btn-sm" style="padding:3px 8px; font-size:0.75rem; color:#6366f1; border-color:#c7d2fe;" onclick="openPromptEditor(${item.id})" title="编辑模板">✏️ 编辑</button>
        <button class="btn btn-outline btn-sm" style="padding:3px 8px; font-size:0.75rem; color:var(--danger); border-color:#fecaca;" onclick="removePrompt(${item.id})" title="删除模板">🗑️</button>
        ` : ""}
      </td>
    `;
    tbody.appendChild(tr);
  });

  // 渲染各行初始生成预览 (含缓存的已填参数)
  tbody.querySelectorAll(".prompt-gen-preview").forEach(renderPreviewInto);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

// ============================================================================
// 参数变量解析: 模板内容中 {参数名} 即为变量占位符
// ============================================================================
function extractPromptVars(content) {
  const vars = [];
  const re = /\{([^{}\n]+)\}/g;
  let m;
  while ((m = re.exec(content || "")) !== null) {
    const name = m[1].trim();
    if (name && !vars.includes(name)) vars.push(name);
  }
  return vars;
}

// 按参数值生成完整提示词纯文本: 已填替换, 未填保留 {参数名} 占位
function generatePromptText(content, values) {
  return (content || "").replace(/\{([^{}\n]+)\}/g, (full, rawName) => {
    const name = rawName.trim();
    const val = (values[name] || "").trim();
    return val ? val : `{${name}}`;
  });
}

// 按参数值渲染生成结果 HTML: 已填绿色高亮, 未填红色醒目占位
function renderGeneratedPrompt(content, values) {
  const esc = escapeHtml(content);
  return esc.replace(/\{([^{}\n]+)\}/g, (full, rawName) => {
    const name = rawName.trim();
    const val = (values[name] || "").trim();
    if (val) {
      return `<span style="background:#f0fdf4; color:#15803d; font-weight:700; border:1px solid #86efac; border-radius:4px; padding:0 4px;">${escapeHtml(val)}</span>`;
    }
    return `<span style="background:#fef2f2; color:#dc2626; border:1px solid #ef4444; border-radius:4px; padding:0 4px; font-weight:800;">{${escapeHtml(name)}}</span>`;
  });
}

// 将指定模板的实时生成预览渲染到行内预览容器 (悬浮 title = 拼接后完整提示词)
function renderPreviewInto(el) {
  const pid = parseInt(el.dataset.pid, 10);
  const item = promptsState.templates.find(t => t.id === pid);
  if (!item) return;
  const values = promptsState.paramValues[pid] || {};
  el.innerHTML = renderGeneratedPrompt(item.content, values);
  el.title = generatePromptText(item.content, values);
}

// ============================================================================
// 行内填参生成 & 一键复制
// ============================================================================
// 行内参数输入: 委托监听, 输入即缓存并实时刷新本行生成预览
document.addEventListener("input", (e) => {
  const inp = e.target.closest(".prompt-row-var-input");
  if (!inp) return;
  const pid = inp.dataset.pid;
  const varName = inp.dataset.var;
  if (!pid || !varName) return;
  if (!promptsState.paramValues[pid]) promptsState.paramValues[pid] = {};
  promptsState.paramValues[pid][varName] = inp.value;
  const preview = document.querySelector(`.prompt-gen-preview[data-pid="${pid}"]`);
  if (preview) renderPreviewInto(preview);
});

function copyGeneratedPrompt(id) {
  const item = promptsState.templates.find(t => t.id === id);
  if (!item) return;
  const values = promptsState.paramValues[id] || {};
  copyPromptText(generatePromptText(item.content, values));
}

function copyPromptText(text, afterCb) {
  if (typeof copyTextToClipboard === "function") {
    copyTextToClipboard(text, false);
    promptToast("✨ 提示词已复制到剪贴板，可直接粘贴使用！");
    if (afterCb) afterCb();
  } else {
    navigator.clipboard.writeText(text).then(() => {
      promptToast("✨ 提示词已复制到剪贴板，可直接粘贴使用！");
      if (afterCb) afterCb();
    }).catch(err => promptToast(`复制失败: ${err.message}`, "error"));
  }
}

// ============================================================================
// 管理员新增 / 编辑 / 删除
// ============================================================================
function openPromptEditor(id = null) {
  const container = document.getElementById("promptEditorContainer");
  if (!container || !window.IS_ADMIN) return;
  promptsState.editingId = id;

  const isEdit = id !== null;
  const item = isEdit ? promptsState.templates.find(t => t.id === id) : null;

  container.innerHTML = `
    <div class="edit-row-card" style="border-color:#8b5cf6; margin-bottom:14px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <div style="font-weight:700; color:#6d28d9; font-size:0.92rem;">${isEdit ? "✏️ 编辑提示词模板" : "➕ 新增提示词模板"}</div>
        <button class="btn btn-outline btn-sm" onclick="closePromptEditor()" style="padding:3px 10px;">✕ 取消</button>
      </div>
      <div style="display:grid; grid-template-columns:1fr 1fr 110px; gap:12px; margin-bottom:12px;">
        <div>
          <label class="form-label required" style="font-size:0.82rem;">模板名称</label>
          <input type="text" class="form-input" id="promptNameInput" placeholder="如: 五点描述生成提示词" value="${isEdit ? escapeHtml(item.name) : ""}" maxlength="128">
        </div>
        <div>
          <label class="form-label" style="font-size:0.82rem;">用途说明 (可选)</label>
          <input type="text" class="form-input" id="promptDescInput" placeholder="如: 输入商品特性生成五点描述" value="${isEdit ? escapeHtml(item.description) : ""}" maxlength="256">
        </div>
        <div>
          <label class="form-label" style="font-size:0.82rem;">排序 (越小越靠前)</label>
          <input type="number" class="form-input" id="promptSortInput" value="${isEdit ? (item.sort_order || 0) : 0}">
        </div>
      </div>
      <div style="margin-bottom:14px;">
        <label class="form-label required" style="font-size:0.82rem;">提示词内容</label>
        <textarea class="form-input" id="promptContentInput" rows="10" placeholder="输入提示词全文。支持 {参数名} 占位符，使用时填参自动生成完整提示词，如: 请为商品「{商品名称}」生成{数量}条五点描述" style="font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size:0.85rem; line-height:1.6; resize:vertical;">${isEdit ? escapeHtml(item.content) : ""}</textarea>
      </div>
      <div style="display:flex; justify-content:flex-end;">
        <button class="btn btn-primary" id="savePromptBtn" type="button" style="background:#8b5cf6; border-color:#8b5cf6;">💾 ${isEdit ? "保存修改" : "保存模板"}</button>
      </div>
    </div>
  `;
  container.style.display = "block";
  container.scrollIntoView({ behavior: "smooth", block: "nearest" });

  document.getElementById("savePromptBtn").addEventListener("click", savePrompt);
  document.getElementById("promptNameInput").focus();
}

function closePromptEditor() {
  const container = document.getElementById("promptEditorContainer");
  if (container) {
    container.style.display = "none";
    container.innerHTML = "";
  }
  promptsState.editingId = null;
}

async function savePrompt() {
  const nameInp = document.getElementById("promptNameInput");
  const descInp = document.getElementById("promptDescInput");
  const sortInp = document.getElementById("promptSortInput");
  const contentInp = document.getElementById("promptContentInput");
  if (!nameInp || !contentInp) return;

  const name = nameInp.value.trim();
  const content = contentInp.value.trim();
  if (!name) { promptToast("请输入模板名称！", "error"); nameInp.focus(); return; }
  if (!content) { promptToast("提示词内容不能为空！", "error"); contentInp.focus(); return; }

  const payload = {
    name: name,
    content: content,
    description: (descInp?.value || "").trim(),
    sort_order: parseInt(sortInp?.value, 10) || 0
  };

  const isEdit = promptsState.editingId !== null;
  const url = isEdit ? `/api/prompts/${promptsState.editingId}` : "/api/prompts";
  const method = isEdit ? "PUT" : "POST";

  try {
    const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const result = await res.json();
    if (result.code === 0) {
      promptToast(isEdit ? "✏️ 提示词模板已更新！" : "✨ 提示词模板添加成功！");
      closePromptEditor();
      loadPrompts();
    } else {
      throw new Error(result.detail || result.msg || "保存失败");
    }
  } catch (err) {
    promptToast(`保存失败: ${err.message}`, "error");
  }
}

async function removePrompt(id) {
  const item = promptsState.templates.find(t => t.id === id);
  if (!item) return;
  if (!confirm(`确定要删除提示词模板「${item.name}」吗？删除后不可恢复！`)) return;

  try {
    const res = await fetch(`/api/prompts/${id}`, { method: "DELETE" });
    const result = await res.json();
    if (result.code === 0) {
      promptToast(result.msg || "已删除");
      if (promptsState.editingId === id) closePromptEditor();
      loadPrompts();
    } else {
      throw new Error(result.detail || result.msg || "删除失败");
    }
  } catch (err) {
    promptToast(`删除失败: ${err.message}`, "error");
  }
}

// ============================================================================
// 初始化
// ============================================================================
document.addEventListener("DOMContentLoaded", () => {
  initKbSubnav();
  const addBtn = document.getElementById("openAddPromptBtn");
  if (addBtn) addBtn.addEventListener("click", () => openPromptEditor(null));
});
