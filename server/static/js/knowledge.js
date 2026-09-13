/**
 * 知识库与常用工具导航前端交互逻辑
 * 支持 5 段分段网址拼接配置、输入参数实时随动替换网址内容、{var} 红色醒目高亮、管理员增删改查
 */

const knowledgeState = {
  sites: [],
  editingId: null,
  isAdding: false
};

function showToast(msg, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast-msg toast-${type}`;
  toast.innerText = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ============================================================================
// 数据加载与表格渲染
// ============================================================================

async function loadKnowledgeSites() {
  try {
    const res = await fetch("/api/knowledge");
    const result = await res.json();
    if (result.code === 0) {
      knowledgeState.sites = result.data || [];
      const badge = document.getElementById("siteCountBadge");
      if (badge) badge.innerText = `共 ${knowledgeState.sites.length} 个网址`;
      renderKnowledgeTable();
    } else {
      showToast(`加载知识库失败: ${result.msg || result.detail}`, "error");
    }
  } catch (err) {
    showToast(`网络请求异常: ${err.message}`, "error");
  }
}

function formatUrlForHref(url) {
  if (!url) return "#";
  const trimmed = String(url).trim();
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }
  return `https://${trimmed}`;
}

let globalDescTooltip = null;
let hideTooltipTimer = null;

function initDescTooltip() {
  if (globalDescTooltip) return;
  globalDescTooltip = document.createElement("div");
  globalDescTooltip.className = "knowledge-floating-tooltip";
  globalDescTooltip.style.cssText = `
    position: fixed;
    display: none;
    z-index: 99999;
    width: max-content;
    min-width: 140px;
    max-width: min(500px, calc(100vw - 32px));
    max-height: 420px;
    overflow-y: auto;
    background: #0f172a;
    color: #f8fafc;
    padding: 10px 14px;
    border-radius: 8px;
    box-shadow: 0 16px 36px -4px rgba(0, 0, 0, 0.4), 0 6px 12px -2px rgba(0, 0, 0, 0.25);
    border: 1px solid #334155;
    pointer-events: auto;
    transition: opacity 0.15s ease, transform 0.15s ease;
    opacity: 0;
    transform: translateY(4px);
    box-sizing: border-box;
  `;
  // 鼠标移入浮框自身时保持显示，移出时开启延迟关闭
  globalDescTooltip.addEventListener("mouseenter", cancelHideDescTooltip);
  globalDescTooltip.addEventListener("mouseleave", scheduleHideDescTooltip);
  document.body.appendChild(globalDescTooltip);
}

function cancelHideDescTooltip() {
  if (hideTooltipTimer) {
    clearTimeout(hideTooltipTimer);
    hideTooltipTimer = null;
  }
  if (globalDescTooltip && globalDescTooltip.style.display === "block") {
    globalDescTooltip.style.opacity = "1";
    globalDescTooltip.style.transform = "translateY(0)";
  }
}

function scheduleHideDescTooltip() {
  if (hideTooltipTimer) clearTimeout(hideTooltipTimer);
  hideTooltipTimer = setTimeout(() => {
    if (globalDescTooltip) {
      globalDescTooltip.style.opacity = "0";
      globalDescTooltip.style.transform = "translateY(4px)";
      setTimeout(() => {
        if (globalDescTooltip && globalDescTooltip.style.opacity === "0") {
          globalDescTooltip.style.display = "none";
        }
      }, 150);
    }
  }, 120);
}

function showDescTooltip(e, text) {
  if (!text || !text.trim()) return;
  cancelHideDescTooltip();
  initDescTooltip();

  const escaped = escapeHtml(text);
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  const formattedHtml = escaped.replace(urlRegex, (url) => {
    return `<a href="${url}" target="_blank" rel="noopener noreferrer" style="color:#60a5fa; text-decoration:underline; font-weight:500;">${url}</a>`;
  });

  globalDescTooltip.innerHTML = `
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; padding-bottom:5px; border-bottom:1px solid #1e293b; gap:12px;">
      <div style="display:flex; align-items:center; gap:5px; font-weight:700; color:#94a3b8; font-size:0.75rem;">
        <span>📝</span><span>说明详情</span>
      </div>
      <button type="button" class="btn-copy-desc" onclick="copyTooltipDesc(event)" style="background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.15); color:#cbd5e1; font-size:0.70rem; cursor:pointer; padding:2px 6px; border-radius:4px; transition:all 0.15s;" title="复制完整说明文本">
        📋 复制
      </button>
    </div>
    <div class="tooltip-body-text" style="color:#e2e8f0; font-size:0.83rem; line-height:1.6; word-break:break-word; white-space:pre-wrap;">${formattedHtml}</div>
  `;

  globalDescTooltip.style.visibility = "hidden";
  globalDescTooltip.style.display = "block";
  globalDescTooltip.style.opacity = "0";
  globalDescTooltip.style.transform = "translateY(4px)";

  // 动态测量内容实际渲染宽高，实现大小严格自适应内容
  const tooltipRect = globalDescTooltip.getBoundingClientRect();
  const tipWidth = tooltipRect.width;
  const tipHeight = tooltipRect.height;

  const targetRect = e.currentTarget.getBoundingClientRect();
  let top = targetRect.bottom + 6;
  let left = targetRect.left;

  // 视口右侧避让
  if (left + tipWidth > window.innerWidth - 16) {
    left = window.innerWidth - tipWidth - 16;
  }
  // 视口左侧避让
  if (left < 16) {
    left = 16;
  }

  // 视口底部避让：若下方空间不足则向上弹出
  if (top + tipHeight > window.innerHeight - 12 && targetRect.top - tipHeight - 6 > 0) {
    top = targetRect.top - tipHeight - 6;
  }

  globalDescTooltip.style.top = `${top}px`;
  globalDescTooltip.style.left = `${left}px`;
  globalDescTooltip.style.visibility = "visible";

  requestAnimationFrame(() => {
    if (globalDescTooltip) {
      globalDescTooltip.style.opacity = "1";
      globalDescTooltip.style.transform = "translateY(0)";
    }
  });
}

function copyTooltipDesc(e) {
  e.stopPropagation();
  const textEl = globalDescTooltip ? globalDescTooltip.querySelector(".tooltip-body-text") : null;
  const rawText = textEl ? textEl.innerText : "";
  if (!rawText) return;
  const onCopied = () => showToast("📋 说明内容已成功复制！");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(rawText).then(onCopied).catch(() => {
      fallbackCopy(rawText, onCopied);
    });
  } else {
    fallbackCopy(rawText, onCopied);
  }
}

function hideDescTooltip() {
  scheduleHideDescTooltip();
}

function formatDescription(text) {
  if (!text) return '<span style="color:#94a3b8;">—</span>';
  const clean = escapeHtml(text);
  const encodedParam = encodeURIComponent(text);
  return `
    <div class="desc-cell-content"
         data-desc="${encodedParam}"
         title="${clean}"
         onmouseenter="handleDescEnter(event)"
         onmouseleave="scheduleHideDescTooltip()">
      ${clean}
    </div>
  `;
}

function handleDescEnter(e) {
  const encoded = e.currentTarget.getAttribute("data-desc");
  if (!encoded) return;
  const rawText = decodeURIComponent(encoded);
  showDescTooltip(e, rawText);
}

function renderKnowledgeTable() {
  const tbody = document.getElementById("knowledgeTableBody");
  if (!tbody) return;

  const sites = knowledgeState.sites;
  const isAdmin = !!window.IS_ADMIN;
  const colSpan = 4;

  if (sites.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="${colSpan}" style="text-align:center; padding:40px; color:var(--text-muted);">
          📭 暂无知识库网址${isAdmin ? '，请点击上方「➕ 新增网站」开始添加' : ''}
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = sites.map((item) => {
    // 红色醒目样式渲染 {var}
    const rawUrl = item.full_url || "";
    let highlightedUrl = escapeHtml(rawUrl);
    if (item.has_var) {
      highlightedUrl = highlightedUrl.replaceAll("{var}", '<span class="var-pill-red">{var}</span>');
    }

    // 1. 网站名称列：仅展示网站名称，纯净清晰
    let siteTitleHtml = `
      <div class="site-title-cell">
        <div class="site-title-name" id="titleDisplay_${item.id}">${escapeHtml(item.title)}</div>
      </div>
    `;

    // 2. 网址列：左侧网址内容，中间var参数输入框（在网址右侧、在按钮左侧），右侧小图标直达按钮
    let urlCellHtml = `
      <div class="url-cell-content">
        ${item.has_var ? `
          <a class="url-text-code" id="urlDisplay_${item.id}" href="javascript:void(0);" onclick="handleUrlTextClick(${item.id})" title="请先在右侧输入参数后点击直达">
            ${highlightedUrl}
          </a>
          <div class="url-control-group">
            <input type="text"
                   class="form-input site-param-input js-param-input"
                   id="paramInput_${item.id}"
                   placeholder="输入参数"
                   data-site-id="${item.id}"
                   title="在此输入参数，左侧网址内容将实时随输入动态替换" />
            <button class="btn-url-icon" type="button" id="openBtn_${item.id}" onclick="openDynamicUrl(${item.id})" title="替换参数并在新标签页打开网址">
              🚀
            </button>
          </div>
        ` : (rawUrl ? `
          <a class="url-text-code" id="urlDisplay_${item.id}" href="${formatUrlForHref(rawUrl)}" target="_blank" rel="noopener noreferrer" title="在新标签页直接打开网站">
            ${highlightedUrl}
          </a>
          <div class="url-control-group">
            <a href="${formatUrlForHref(rawUrl)}" target="_blank" rel="noopener noreferrer" class="btn-url-icon" title="在新标签页直接打开网站">
              ↗️
            </a>
          </div>
        ` : '<span style="color:#94a3b8;">—</span>')}
      </div>
    `;

    // 3. 说明列：宽度调大，自然换行展示，识别并支持链接点击
    const descHtml = formatDescription(item.description || "");

    // 4. 操作列（所有人均可复制链接；管理员享有编辑与删除权限）
    let actionCellHtml = `
      <td class="site-action-cell">
        <div style="display:flex; gap:6px; justify-content:center; align-items:center;">
          <button class="btn btn-outline btn-sm" type="button" onclick="copySiteUrl(${item.id})" style="padding:2px 8px; font-size:0.75rem;" title="复制当前网址链接到剪贴板">
            📋 复制链接
          </button>
          ${isAdmin ? `
            <button class="btn btn-outline btn-sm" type="button" onclick="openEditSite(${item.id})" style="padding:2px 7px; font-size:0.75rem;">
              ✏️ 编辑
            </button>
            <button class="btn btn-danger btn-sm" type="button" onclick="deleteSite(${item.id}, '${escapeHtml(item.title)}')" style="padding:2px 7px; font-size:0.75rem;">
              🗑️ 删除
            </button>
          ` : ''}
        </div>
      </td>
    `;

    return `
      <tr id="siteRow_${item.id}">
        <td>${siteTitleHtml}</td>
        <td>${urlCellHtml}</td>
        <td title="${escapeHtml(item.description || '')}">${descHtml}</td>
        ${actionCellHtml}
      </tr>
    `;
  }).join("");

  // 绑定动态参数输入框的 input 事件 (随输入实时替换网址展示) 与回车直达
  document.querySelectorAll(".js-param-input").forEach(input => {
    const siteId = parseInt(input.getAttribute("data-site-id"), 10);
    input.addEventListener("input", () => onParamInputChange(siteId));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        openDynamicUrl(siteId);
      }
    });
  });
}

// ============================================================================
// 输入过程中，页面展示随输入的内容实时替换网址内容
// ============================================================================

function onParamInputChange(siteId) {
  const item = knowledgeState.sites.find(s => s.id === siteId);
  if (!item) return;

  const inp = document.getElementById(`paramInput_${siteId}`);
  const displayEl = document.getElementById(`urlDisplay_${siteId}`);
  const btnEl = document.getElementById(`openBtn_${siteId}`);
  if (!inp || !displayEl) return;

  const paramVal = inp.value;
  const rawUrl = item.full_url || "";

  if (!paramVal) {
    // 未输入内容或清空：恢复默认 {var} 红色醒目样式
    let def = escapeHtml(rawUrl);
    def = def.replaceAll("{var}", '<span class="var-pill-red">{var}</span>');
    displayEl.innerHTML = def;
    displayEl.setAttribute("href", "javascript:void(0);");
    displayEl.setAttribute("target", "_self");
    displayEl.title = "请先在右侧输入参数后点击直达";
    if (btnEl) btnEl.title = "替换参数并在新标签页打开网址";
  } else {
    // 随输入内容动态替换 {var}，并以红色醒目样式显示当前输入的动态值
    let replaced = escapeHtml(rawUrl);
    replaced = replaced.replaceAll(
      "{var}",
      `<span class="var-pill-red" title="已动态替换为: ${escapeHtml(paramVal)}">${escapeHtml(paramVal)}</span>`
    );
    displayEl.innerHTML = replaced;

    const fullTarget = rawUrl.replaceAll("{var}", encodeURIComponent(paramVal.trim()));
    const fullHref = formatUrlForHref(fullTarget);
    displayEl.setAttribute("href", fullHref);
    displayEl.setAttribute("target", "_blank");
    displayEl.title = `点击直达: ${fullTarget}`;

    if (btnEl) {
      btnEl.title = `点击直达: ${fullTarget}`;
    }
  }

  // 若网站名称也含有 {var}，同样随动实时替换
  const titleEl = document.getElementById(`titleDisplay_${siteId}`);
  if (titleEl && item.title && item.title.includes("{var}")) {
    if (!paramVal) {
      titleEl.innerHTML = escapeHtml(item.title).replaceAll("{var}", '<span class="var-pill-red">{var}</span>');
    } else {
      titleEl.innerHTML = escapeHtml(item.title).replaceAll(
        "{var}",
        `<span class="var-pill-red">${escapeHtml(paramVal)}</span>`
      );
    }
  }
}

function handleUrlTextClick(siteId) {
  const inp = document.getElementById(`paramInput_${siteId}`);
  const paramVal = inp ? inp.value.trim() : "";
  if (!paramVal) {
    showToast("请先在网址右侧输入参数（替换 {var}）后再打开！", "error");
    if (inp) inp.focus();
  }
}

// ============================================================================
// 客户动态参数直达跳转
// ============================================================================

function openDynamicUrl(siteId) {
  const item = knowledgeState.sites.find(s => s.id === siteId);
  if (!item) return;

  const inp = document.getElementById(`paramInput_${siteId}`);
  const paramVal = inp ? inp.value.trim() : "";

  if (!paramVal) {
    showToast("请先在网址右侧输入参数（替换 {var}）后再打开！", "error");
    if (inp) inp.focus();
    return;
  }

  // 替换 {var} 占位符并以新窗口打开
  const targetUrl = item.full_url.replaceAll("{var}", encodeURIComponent(paramVal));
  window.open(formatUrlForHref(targetUrl), "_blank", "noopener,noreferrer");
}

// ============================================================================
// 复制链接 (所有人可用：若填了参数则复制替换后的最终链接，未填则复制原网址)
// ============================================================================

function copySiteUrl(siteId) {
  const item = knowledgeState.sites.find(s => s.id === siteId);
  if (!item) return;

  const inp = document.getElementById(`paramInput_${siteId}`);
  const paramVal = inp ? inp.value.trim() : "";
  const rawUrl = item.full_url || "";

  let targetUrl = rawUrl;
  if (paramVal && item.has_var) {
    targetUrl = rawUrl.replaceAll("{var}", encodeURIComponent(paramVal));
  }
  targetUrl = formatUrlForHref(targetUrl);

  const onCopySuccess = () => {
    if (paramVal && item.has_var) {
      showToast("📋 已复制参数替换后的完整网址！");
    } else {
      showToast("📋 网址链接已成功复制到剪贴板！");
    }
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(targetUrl).then(onCopySuccess).catch(() => {
      fallbackCopy(targetUrl, onCopySuccess);
    });
  } else {
    fallbackCopy(targetUrl, onCopySuccess);
  }
}

function fallbackCopy(text, onSuccess) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand("copy");
    if (onSuccess) onSuccess();
  } catch (err) {
    showToast("复制失败，请手动选择网址复制！", "error");
  } finally {
    document.body.removeChild(textarea);
  }
}

// ============================================================================
// 管理员新增与编辑
// ============================================================================

function openAddSite() {
  knowledgeState.isAdding = true;
  knowledgeState.editingId = null;
  renderEditor({
    title: "",
    url_parts: ["", "", "", "", ""],
    description: "",
    sort_order: (knowledgeState.sites.length + 1) * 10
  });
}

function openEditSite(id) {
  const item = knowledgeState.sites.find(s => s.id === id);
  if (!item) return;
  knowledgeState.isAdding = false;
  knowledgeState.editingId = id;
  renderEditor(item);
}

function renderEditor(data) {
  const container = document.getElementById("editorContainer");
  if (!container) return;

  const isNew = knowledgeState.isAdding;
  const parts = data.url_parts || ["", "", "", "", ""];

  container.innerHTML = `
    <div class="edit-row-card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid #e2e8f0; padding-bottom:8px;">
        <div style="font-weight:700; color:#1e293b; font-size:0.95rem;">
          ${isNew ? '➕ 新增知识库网站' : '✏️ 编辑知识库网站'}
        </div>
        <button class="btn btn-outline btn-sm" type="button" onclick="cancelEdit()" style="padding:2px 8px; font-size:0.75rem;">
          ✕ 取消
        </button>
      </div>

      <div style="display:flex; flex-direction:column; gap:12px;">
        <!-- 1. 网站名称 -->
        <div>
          <label class="form-label" style="font-weight:700; margin-bottom:4px;">
            🌐 1. 网站名称 <span style="color:#ef4444;">*</span>
          </label>
          <input type="text" class="form-input" id="editorTitle" value="${escapeHtml(data.title || '')}" placeholder="如: 日本亚马逊商品搜索 / 1688以图搜款 / 店小秘商品" required style="width:100%;">
        </div>

        <!-- 2. 网址 (固定 5 个输入框，按序拼接，允许不全输入，如需动态参数填写 {var}) -->
        <div>
          <label class="form-label" style="font-weight:700; margin-bottom:4px; display:flex; justify-content:space-between; align-items:center;">
            <span>🔗 2. 网址 (固定 5 个分段输入框，按顺序首尾相连拼接；空框自动忽略；如需动态输入参数填 <code>{var}</code>)</span>
            <span style="font-weight:400; color:var(--text-muted); font-size:0.78rem;">允许不全填</span>
          </label>

          <div class="knowledge-url-inputs">
            <div class="url-segment-box">
              <input type="text" class="form-input js-url-part" id="urlPart1" value="${escapeHtml(parts[0] || '')}" placeholder="分段 1 (如 https://...)" />
              <span class="url-segment-badge">①</span>
            </div>
            <div class="url-segment-box">
              <input type="text" class="form-input js-url-part" id="urlPart2" value="${escapeHtml(parts[1] || '')}" placeholder="分段 2 (如需要参数填 {var})" />
              <span class="url-segment-badge">②</span>
            </div>
            <div class="url-segment-box">
              <input type="text" class="form-input js-url-part" id="urlPart3" value="${escapeHtml(parts[2] || '')}" placeholder="分段 3 (如 &ref=...)" />
              <span class="url-segment-badge">③</span>
            </div>
            <div class="url-segment-box">
              <input type="text" class="form-input js-url-part" id="urlPart4" value="${escapeHtml(parts[3] || '')}" placeholder="分段 4 (可选)" />
              <span class="url-segment-badge">④</span>
            </div>
            <div class="url-segment-box">
              <input type="text" class="form-input js-url-part" id="urlPart5" value="${escapeHtml(parts[4] || '')}" placeholder="分段 5 (可选)" />
              <span class="url-segment-badge">⑤</span>
            </div>
          </div>

          <!-- 实时拼接预览栏 -->
          <div class="url-preview-bar" id="urlPreviewBar">
            拼接完整网址预览: <span id="urlPreviewContent" style="color:#6366f1;">(暂无输入)</span>
          </div>
        </div>

        <!-- 3. 说明 -->
        <div>
          <label class="form-label" style="font-weight:700; margin-bottom:4px;">
            📝 3. 说明备注
          </label>
          <input type="text" class="form-input" id="editorDesc" value="${escapeHtml(data.description || '')}" placeholder="如: 亚马逊日亚前台商品搜词，输入 ASIN 或关键词后可直接跳转查品" style="width:100%;">
        </div>

        <!-- 操作按钮 -->
        <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:6px;">
          <button class="btn btn-outline" type="button" onclick="cancelEdit()" style="padding:6px 16px;">取消</button>
          <button class="btn btn-primary" type="button" onclick="saveSite()" style="padding:6px 20px; background:#6366f1; border-color:#6366f1; font-weight:600;">
            💾 确认保存
          </button>
        </div>
      </div>
    </div>
  `;

  container.style.display = "block";
  container.scrollIntoView({ behavior: "smooth", block: "nearest" });

  // 绑定 5 个分段输入框的实时预览更新
  document.querySelectorAll(".js-url-part").forEach(input => {
    input.addEventListener("input", updateUrlPreview);
  });
  updateUrlPreview();
}

function updateUrlPreview() {
  const p1 = (document.getElementById("urlPart1")?.value || "").trim();
  const p2 = (document.getElementById("urlPart2")?.value || "").trim();
  const p3 = (document.getElementById("urlPart3")?.value || "").trim();
  const p4 = (document.getElementById("urlPart4")?.value || "").trim();
  const p5 = (document.getElementById("urlPart5")?.value || "").trim();

  const joined = p1 + p2 + p3 + p4 + p5;
  const previewEl = document.getElementById("urlPreviewContent");
  if (!previewEl) return;

  if (!joined) {
    previewEl.innerHTML = '<span style="color:#94a3b8;">(请在上方 5 个框中输入网址片段)</span>';
  } else {
    let safe = escapeHtml(joined);
    safe = safe.replaceAll("{var}", '<span class="var-pill-red">{var}</span>');
    previewEl.innerHTML = safe;
  }
}

function cancelEdit() {
  const container = document.getElementById("editorContainer");
  if (container) {
    container.innerHTML = "";
    container.style.display = "none";
  }
  knowledgeState.isAdding = false;
  knowledgeState.editingId = null;
}

async function saveSite() {
  const title = (document.getElementById("editorTitle")?.value || "").trim();
  if (!title) {
    showToast("网站名称为必填项！", "error");
    document.getElementById("editorTitle")?.focus();
    return;
  }

  const parts = [
    (document.getElementById("urlPart1")?.value || "").trim(),
    (document.getElementById("urlPart2")?.value || "").trim(),
    (document.getElementById("urlPart3")?.value || "").trim(),
    (document.getElementById("urlPart4")?.value || "").trim(),
    (document.getElementById("urlPart5")?.value || "").trim()
  ];

  const fullUrl = parts.join("");
  if (!fullUrl) {
    showToast("网址内容不能为空，请在 5 个分段框中至少填写一段！", "error");
    document.getElementById("urlPart1")?.focus();
    return;
  }

  const description = (document.getElementById("editorDesc")?.value || "").trim();

  const payload = {
    title,
    url_parts: parts,
    description,
    sort_order: 0
  };

  try {
    const isNew = knowledgeState.isAdding;
    const url = isNew ? "/api/knowledge" : `/api/knowledge/${knowledgeState.editingId}`;
    const method = isNew ? "POST" : "PUT";

    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const result = await res.json();
    if (result.code === 0) {
      showToast(`🎉 网站「${title}」${isNew ? '添加' : '更新'}成功！`);
      cancelEdit();
      await loadKnowledgeSites();
    } else {
      showToast(`保存失败: ${result.detail || result.msg || "未知错误"}`, "error");
    }
  } catch (err) {
    showToast(`保存异常: ${err.message}`, "error");
  }
}

async function deleteSite(siteId, title) {
  if (!confirm(`确定要删除知识库网站「${title}」吗？删除后不可恢复。`)) return;

  try {
    const res = await fetch(`/api/knowledge/${siteId}`, { method: "DELETE" });
    const result = await res.json();
    if (result.code === 0) {
      showToast(`已成功删除网站「${title}」`);
      await loadKnowledgeSites();
    } else {
      showToast(`删除失败: ${result.detail || result.msg}`, "error");
    }
  } catch (err) {
    showToast(`删除异常: ${err.message}`, "error");
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ============================================================================
// 初始化
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  loadKnowledgeSites();

  const addBtn = document.getElementById("openAddSiteBtn");
  if (addBtn) {
    addBtn.addEventListener("click", openAddSite);
  }
});
