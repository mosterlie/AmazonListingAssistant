/**
 * 履约中心公共前端工具: API 调用 / 弹窗表单 / 文件上传 / 附件卡片 / 分页
 * 依赖 base.html 中的 showToast (app.js), 未加载时回退 alert
 */
(function () {
  const FM = {};

  FM.esc = function (value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  };

  FM.toast = function (msg, type) {
    if (typeof window.showToast === "function") {
      window.showToast(msg, type || "success");
    } else {
      alert(msg);
    }
  };

  FM.api = async function (url, options) {
    const opts = Object.assign({ credentials: "same-origin" }, options || {});
    if (opts.body && !(opts.body instanceof FormData)) {
      opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
      if (typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, opts);
    let data = {};
    try {
      data = await resp.json();
    } catch (e) {
      data = {};
    }
    if (!resp.ok) {
      throw new Error(data.detail || data.msg || ("请求失败 HTTP " + resp.status));
    }
    if (data.code !== undefined && data.code !== 0) {
      throw new Error(data.msg || data.detail || "操作失败");
    }
    return data;
  };

  FM.money = function (amount, currency) {
    const num = Number(amount || 0);
    return (currency || "") + num.toLocaleString("zh-CN", {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
  };

  FM.fmtTime = function (text) {
    return String(text || "").replace("T", " ").slice(0, 16) || "—";
  };

  FM.pickFile = function (accept) {
    return new Promise(resolve => {
      const input = document.createElement("input");
      input.type = "file";
      if (accept) input.accept = accept;
      input.style.display = "none";
      document.body.appendChild(input);
      input.addEventListener("change", () => {
        const file = input.files && input.files[0] ? input.files[0] : null;
        document.body.removeChild(input);
        resolve(file);
      });
      input.click();
    });
  };

  FM.modal = function (config) {
    const overlay = document.createElement("div");
    overlay.className = "fm-overlay";
    const fieldHtml = (config.fields || []).map(function (f) {
      const value = f.value == null ? "" : f.value;
      const id = "fmf_" + Math.random().toString(36).slice(2, 8);
      let control = "";
      if (f.type === "select") {
        control = `<select id="${id}" data-key="${FM.esc(f.key)}">` + (f.options || []).map(o =>
          `<option value="${FM.esc(o.value)}" ${String(o.value) === String(value) ? "selected" : ""}>${FM.esc(o.label)}</option>`
        ).join("") + "</select>";
      } else if (f.type === "textarea") {
        control = `<textarea id="${id}" data-key="${FM.esc(f.key)}" placeholder="${FM.esc(f.placeholder || "")}">${FM.esc(value)}</textarea>`;
      } else if (f.type === "file") {
        control = `<input id="${id}" data-key="${FM.esc(f.key)}" type="file" ${f.accept ? `accept="${FM.esc(f.accept)}"` : ""}>`;
      } else {
        control = `<input id="${id}" data-key="${FM.esc(f.key)}" type="${f.type || "text"}"
          value="${FM.esc(value)}" placeholder="${FM.esc(f.placeholder || "")}" ${f.step ? `step="${f.step}"` : ""}>`;
      }
      return `<div class="fm-field"><label for="${id}">${FM.esc(f.label)}${f.required ? ' <span style="color:#ef4444;">*</span>' : ""}</label>${control}</div>`;
    }).join("");

    overlay.innerHTML = `
      <div class="fm-modal" style="${config.width ? `width:min(${config.width},100%)` : ""}">
        <div class="fm-modal-head">
          <div class="fm-modal-title">${FM.esc(config.title || "")}</div>
          <button type="button" class="fm-btn ghost" data-close style="margin-left:auto;">✕</button>
        </div>
        <div class="fm-modal-body">
          ${config.hint ? `<div class="fm-muted">${config.hint}</div>` : ""}
          ${fieldHtml}
        </div>
        <div class="fm-modal-foot">
          <button type="button" class="fm-btn" data-close>取消</button>
          <button type="button" class="fm-btn primary" data-submit>${FM.esc(config.submitText || "保存")}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.addEventListener("click", e => {
      if (e.target === overlay || e.target.closest("[data-close]")) close();
    });
    overlay.querySelector("[data-submit]").addEventListener("click", async function () {
      const btn = this;
      const values = {};
      overlay.querySelectorAll("[data-key]").forEach(el => {
        values[el.dataset.key] = el.type === "file" ? (el.files && el.files[0]) || null : el.value;
      });
      btn.disabled = true;
      btn.textContent = "处理中…";
      try {
        const keepOpen = await config.onSubmit(values);
        if (keepOpen !== false) close();
      } catch (err) {
        FM.toast(err.message || "操作失败", "error");
        btn.disabled = false;
        btn.textContent = config.submitText || "保存";
      }
    });
    return overlay;
  };

  FM.infoModal = function (title, html, width) {
    const overlay = document.createElement("div");
    overlay.className = "fm-overlay";
    overlay.innerHTML = `
      <div class="fm-modal" style="${width ? `width:min(${width},100%)` : ""}">
        <div class="fm-modal-head">
          <div class="fm-modal-title">${FM.esc(title || "")}</div>
          <button type="button" class="fm-btn ghost" data-close style="margin-left:auto;">✕</button>
        </div>
        <div class="fm-modal-body">${html || '<div class="fm-doc-empty">暂无内容</div>'}</div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", e => {
      if (e.target === overlay || e.target.closest("[data-close]")) overlay.remove();
    });
    FM.bindDocs(overlay, () => {});
    return overlay;
  };

  FM.uploadFiles = async function (url, fields, files) {
    const fd = new FormData();
    Object.keys(fields || {}).forEach(k => {
      if (fields[k] !== undefined && fields[k] !== null) fd.append(k, fields[k]);
    });
    (files || []).forEach(f => fd.append("files", f));
    return FM.api(url, { method: "POST", body: fd });
  };

  FM.docCard = function (doc, canDelete) {
    const thumb = doc.preview_url
      ? `<img src="${FM.esc(doc.preview_url)}" alt="">`
      : `<span style="font-size:1.1rem;">${FM.esc(doc.category_icon || "📎")}</span>`;
    return `<div class="fm-doc" data-doc-id="${doc.id}">
      <div class="fm-doc-thumb" data-preview="${FM.esc(doc.preview_url || "")}" title="点击预览">${thumb}</div>
      <div class="fm-doc-info">
        <div class="fm-doc-name" title="${FM.esc(doc.file_name)}">${FM.esc(doc.file_name)}</div>
        <div class="fm-doc-meta">${FM.esc(doc.category_label || "")} · ${FM.esc(doc.size_text || "")} · ${FM.esc(FM.fmtTime(doc.created_at))}</div>
      </div>
      <div class="fm-doc-acts">
        <a href="${FM.esc(doc.download_url)}" title="下载">⬇</a>
        ${canDelete ? `<button type="button" data-doc-del="${doc.id}" title="删除">🗑</button>` : ""}
      </div>
    </div>`;
  };

  FM.bindDocs = function (root, onChange) {
    if (!root) return;
    root.querySelectorAll("[data-preview]").forEach(el => {
      el.addEventListener("click", () => {
        const url = el.dataset.preview;
        if (!url) return;
        const overlay = document.createElement("div");
        overlay.className = "fm-overlay";
        overlay.innerHTML = `<div style="max-width:min(1100px,100%); background:#fff; padding:8px; border-radius:10px;">
          <div style="display:flex; justify-content:flex-end;"><button class="fm-btn" data-x>✕ 关闭</button></div>
          <img src="${FM.esc(url)}" style="max-width:100%; max-height:80vh; display:block; margin:6px auto;">
        </div>`;
        document.body.appendChild(overlay);
        overlay.addEventListener("click", e => {
          if (e.target === overlay || e.target.closest("[data-x]")) overlay.remove();
        });
      });
    });
    root.querySelectorAll("[data-doc-del]").forEach(el => {
      el.addEventListener("click", async () => {
        if (!confirm("确定删除该附件？删除后不可恢复。")) return;
        try {
          await FM.api("/api/fulfillment/documents/" + el.dataset.docDel, { method: "DELETE" });
          FM.toast("附件已删除");
          if (onChange) onChange();
        } catch (err) {
          FM.toast(err.message, "error");
        }
      });
    });
  };

  FM.pager = function (data, onChange) {
    const total = Number(data.total || 0);
    const page = Number(data.page || 1);
    const size = Number(data.page_size || 20);
    const pages = Math.max(1, Math.ceil(total / size));
    const el = document.createElement("div");
    el.className = "fm-pager";
    el.innerHTML = `<span>共 ${total} 条 · 第 ${page}/${pages} 页</span>
      <button class="fm-btn" data-prev ${page <= 1 ? "disabled" : ""}>上一页</button>
      <button class="fm-btn" data-next ${page >= pages ? "disabled" : ""}>下一页</button>`;
    el.querySelector("[data-prev]").addEventListener("click", () => { if (page > 1) onChange(page - 1); });
    el.querySelector("[data-next]").addEventListener("click", () => { if (page < pages) onChange(page + 1); });
    return el;
  };

  FM.statusChip = function (status, text) {
    const label = text || status || "未知";
    const raw = String(status || "");
    let cls = "info";
    if (/deliver|sign|complete|finish|success/i.test(raw)) cls = "ok";
    if (/exception|fail|lost|error|cancel/i.test(raw)) cls = "err";
    if (/transit|shipped|wait|pending|shipping/i.test(raw)) cls = "warn";
    return `<span class="fm-chip ${cls}">${FM.esc(label)}</span>`;
  };

  FM.parseChip = function (status) {
    if (status === "success") return `<span class="fm-chip ok">已解析</span>`;
    if (status === "failed") return `<span class="fm-chip err">解析失败</span>`;
    if (status === "pending") return `<span class="fm-chip warn">待解析</span>`;
    return `<span class="fm-chip">未解析</span>`;
  };

  FM.ownerTypeLabel = function (type) {
    return ({ order: "订单", package: "包裹", purchase_order: "采购单" })[type] || type;
  };

  window.FM = FM;
})();
