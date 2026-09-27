/**
 * 知识库文档库前端交互逻辑 (知识库子菜单: 文档库)
 * 管理员上传各类文档 (支持多选)、删除；所有用户可查阅与下载
 * 注意: 本页面同时加载 knowledge.js (已定义全局 showToast 与 escapeHtml), 此处直接复用
 */

const docsState = {
  documents: [],
  loaded: false
};

// ============================================================================
// 子菜单联动: 首次切到「文档库」tab 时懒加载
// ============================================================================
(function initDocsSubnav() {
  document.addEventListener("DOMContentLoaded", () => {
    const nav = document.getElementById("kbSubnav");
    if (!nav) return;
    nav.addEventListener("click", (e) => {
      const btn = e.target.closest(".kb-subnav-item");
      if (btn && btn.dataset.tab === "docs" && !docsState.loaded) {
        docsState.loaded = true;
        loadDocuments();
      }
    });
    const uploadBtn = document.getElementById("toggleDocUploadBtn");
    if (uploadBtn) {
      uploadBtn.addEventListener("click", toggleDocUpload);
    }
  });
})();

// ============================================================================
// 数据加载与表格渲染
// ============================================================================

async function loadDocuments() {
  const tbody = document.getElementById("docTableBody");
  try {
    const res = await fetch("/api/knowledge/documents");
    const result = await res.json();
    if (result.code === 0) {
      docsState.documents = result.data || [];
      const badge = document.getElementById("docCountBadge");
      if (badge) badge.innerText = `共 ${docsState.documents.length} 个文档`;
      renderDocTable();
    } else {
      showToast(`加载文档列表失败: ${result.msg || result.detail}`, "error");
    }
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:24px; color:#ef4444;">❌ 加载文档列表异常: ${err.message}</td></tr>`;
  }
}

function formatDocSize(size) {
  const n = Number(size) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

// 按扩展名返回文档类型图标
function docTypeIcon(ext) {
  const map = {
    ".pdf": "📕", ".doc": "📘", ".docx": "📘",
    ".xls": "📗", ".xlsx": "📗", ".csv": "📊",
    ".ppt": "📙", ".pptx": "📙",
    ".txt": "📄", ".md": "📝",
    ".zip": "🗜️", ".rar": "🗜️", ".7z": "🗜️",
    ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".gif": "🖼️", ".webp": "🖼️", ".svg": "🖼️"
  };
  return map[ext] || "📎";
}

function renderDocTable() {
  const tbody = document.getElementById("docTableBody");
  if (!tbody) return;

  const docs = docsState.documents;
  const isAdmin = !!window.IS_ADMIN;

  if (docs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align:center; padding:40px; color:var(--text-muted);">
          📭 暂无文档${isAdmin ? '，请点击上方「⬆️ 上传文档」开始上传' : ''}
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = docs.map((d, idx) => {
    const timePart = (d.created_at || "").replace("T", " ").slice(0, 16);
    const descHtml = d.description
      ? `<span style="color:#475569; font-size:0.82rem; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:190px;" title="${escapeHtml(d.description)}">${escapeHtml(d.description)}</span>`
      : '<span style="color:#94a3b8;">—</span>';

    return `
      <tr id="docRow_${d.id}">
        <td style="text-align:center; color:#94a3b8; font-size:0.8rem;">${idx + 1}</td>
        <td>
          <a href="${d.download_url}" class="doc-name-link" title="点击下载: ${escapeHtml(d.name)}">
            ${docTypeIcon(d.ext)} ${escapeHtml(d.name)}
          </a>
        </td>
        <td><span class="tag-badge" style="background:#f1f5f9; color:#475569; border-color:#e2e8f0;">${escapeHtml(d.ext_label || "文件")}</span></td>
        <td style="color:#64748b; font-size:0.82rem;">${formatDocSize(d.size)}</td>
        <td>${descHtml}</td>
        <td style="color:#64748b; font-size:0.8rem;">
          ${escapeHtml(d.uploaded_by || "—")}<br/>
          <span style="color:#94a3b8;">${escapeHtml(timePart)}</span>
        </td>
        <td class="site-action-cell">
          <div style="display:flex; gap:6px; justify-content:center; align-items:center;">
            <a href="${d.download_url}" class="btn btn-outline btn-sm" style="padding:2px 8px; font-size:0.75rem; text-decoration:none;" title="下载到本地">⬇️ 下载</a>
            ${isAdmin ? `
              <button class="btn btn-danger btn-sm" type="button" onclick="deleteDocument(${d.id}, '${escapeHtml(d.name)}')" style="padding:2px 7px; font-size:0.75rem;">
                🗑️ 删除
              </button>
            ` : ''}
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

// ============================================================================
// 管理员上传
// ============================================================================

function toggleDocUpload() {
  const container = document.getElementById("docUploadContainer");
  if (!container) return;
  if (container.style.display === "block") {
    container.style.display = "none";
    container.innerHTML = "";
  } else {
    container.innerHTML = `
      <div class="edit-row-card" style="border-color:#0ea5e9; margin-bottom:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid #e2e8f0; padding-bottom:8px;">
          <div style="font-weight:700; color:#1e293b; font-size:0.95rem;">⬆️ 上传文档 <span style="font-weight:400; color:var(--text-muted); font-size:0.78rem; margin-left:8px;">支持多选；PDF / Word / Excel / PPT / 文本 / 压缩包 / 图片，单个 ≤ 20MB</span></div>
          <button class="btn btn-outline btn-sm" type="button" onclick="toggleDocUpload()" style="padding:2px 8px; font-size:0.75rem;">✕ 收起</button>
        </div>

        <div style="display:flex; flex-direction:column; gap:10px;">
          <div>
            <label class="form-label" style="font-weight:700; margin-bottom:4px;">📄 选择文件 <span style="color:#ef4444;">*</span></label>
            <label id="docFileDrop" style="display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; cursor:pointer;
                        border:2px dashed #94a3b8; border-radius:10px; padding:22px; background:#f8fafc; transition:all 0.15s;">
              <span style="font-size:1.6rem;">📂</span>
              <span style="font-size:0.86rem; color:#334155; font-weight:600;">点击选择文件（可按住 Cmd 多选）</span>
              <span id="docFileSummary" style="font-size:0.78rem; color:#94a3b8;">尚未选择文件</span>
              <input type="file" id="docFileInput" multiple
                     accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv,.zip,.rar,.7z,.png,.jpg,.jpeg,.gif,.webp,.svg"
                     style="display:none;" />
            </label>
          </div>
          <div>
            <label class="form-label" style="font-weight:700; margin-bottom:4px;">📝 文档说明 (可选，应用于本批全部文件)</label>
            <input type="text" class="form-input" id="docDescInput" placeholder="如: 2026年Q4 选品调研资料" style="width:100%;">
          </div>
          <div style="display:flex; gap:10px; justify-content:flex-end;">
            <button class="btn btn-outline" type="button" onclick="toggleDocUpload()" style="padding:6px 16px;">取消</button>
            <button class="btn btn-primary" type="button" onclick="uploadDocuments()" style="padding:6px 20px; background:#0ea5e9; border-color:#0ea5e9; font-weight:600;">
              🚀 开始上传
            </button>
          </div>
        </div>
      </div>
    `;
    container.style.display = "block";

    const fileInput = document.getElementById("docFileInput");
    fileInput.addEventListener("change", () => {
      const files = Array.from(fileInput.files || []);
      const summary = document.getElementById("docFileSummary");
      if (files.length === 0) {
        summary.innerText = "尚未选择文件";
      } else if (files.length === 1) {
        summary.innerText = `已选择 1 个文件: ${files[0].name}`;
      } else {
        summary.innerText = `已选择 ${files.length} 个文件`;
      }
    });
  }
}

async function uploadDocuments() {
  const fileInput = document.getElementById("docFileInput");
  const descInput = document.getElementById("docDescInput");
  const files = Array.from(fileInput?.files || []);
  if (files.length === 0) {
    showToast("请先选择要上传的文档文件！", "error");
    return;
  }

  const formData = new FormData();
  files.forEach(f => formData.append("files", f));
  formData.append("description", (descInput?.value || "").trim());

  try {
    const res = await fetch("/api/knowledge/documents", { method: "POST", body: formData });
    const result = await res.json();
    if (result.code === 0) {
      showToast(`🎉 ${result.msg}`);
      toggleDocUpload();
      await loadDocuments();
    } else {
      showToast(`上传失败: ${result.detail || result.msg || "未知错误"}`, "error");
    }
  } catch (err) {
    showToast(`上传异常: ${err.message}`, "error");
  }
}

async function deleteDocument(docId, name) {
  if (!confirm(`确定要删除文档「${name}」吗？删除后不可恢复。`)) return;
  try {
    const res = await fetch(`/api/knowledge/documents/${docId}`, { method: "DELETE" });
    const result = await res.json();
    if (result.code === 0) {
      showToast(`已删除文档「${name}」`);
      await loadDocuments();
    } else {
      showToast(`删除失败: ${result.detail || result.msg}`, "error");
    }
  } catch (err) {
    showToast(`删除异常: ${err.message}`, "error");
  }
}
