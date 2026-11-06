/**
 * 履约工作台 · 履约专属能力 (表格/筛选/补录/复制/轨迹等复用 orders.js)
 * - 补录弹窗内嵌「全部素材上传 + 一键提交」
 * - 列表附件列图标点击 → 只读查看素材
 */
(function () {
  const esc = s => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const IMG_PDF = [".jpg", ".jpeg", ".png", ".webp", ".pdf"];
  const DOC_ALL = IMG_PDF.concat([".bmp", ".gif", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z"]);
  const SECTIONS = [
    { key: "purchase_order_shot", label: "采购单截图", icon: "🧾", exts: IMG_PDF, group: "po" },
    { key: "transfer_voucher", label: "转账凭证", icon: "💳", exts: IMG_PDF, group: "po" },
    { key: "invoice_purchase", label: "采购发票", icon: "📄", exts: IMG_PDF, group: "po" },
    { key: "delivery_note", label: "发货单", icon: "📦", exts: DOC_ALL, group: "pkg" },
    { key: "receipt", label: "签收单", icon: "✍️", exts: DOC_ALL, group: "pkg" },
    { key: "invoice_forwarder", label: "货代发票", icon: "🚚", exts: IMG_PDF, group: "pkg" },
    { key: "tax_cert", label: "清关报税", icon: "🛃", exts: DOC_ALL, group: "order" },
  ];
  const ORDER = ["purchase_order_shot", "transfer_voucher", "invoice_purchase",
    "delivery_note", "receipt", "invoice_forwarder", "tax_cert"];

  const SUP = {
    key: "", miaoshouId: 0, fmId: 0, data: null,
    files: [], seq: 0, busy: false,
    poId: 0, pkgId: 0,
  };

  // orders.js 的 orderApi 固定 JSON 头, 上传 FormData 需要单独封装
  async function fmApi(url, options = {}) {
    const opts = { ...options };
    opts.headers = (opts.body instanceof FormData) ? {} : { "Content-Type": "application/json" };
    const resp = await fetch(url, opts);
    if (resp.status === 401) { window.location.href = "/login"; throw new Error("未登录"); }
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok || body.code !== 0) throw new Error(body.detail || body.msg || "请求失败");
    return body;
  }

  function secMeta(key) {
    return SECTIONS.find(s => s.key === key) || { key, label: key, exts: DOC_ALL, group: "order" };
  }

  function sizeText(n) {
    n = Number(n || 0);
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(2) + " MB";
  }

  function extOf(name) {
    const i = String(name || "").lastIndexOf(".");
    return i < 0 ? "" : String(name).slice(i).toLowerCase();
  }

  /* 暂存素材的本地预览地址 (blob), 用完需 revoke */
  function supFileUrl(f) {
    if (!f.url) {
      try { f.url = URL.createObjectURL(f.file); } catch (e) { f.url = ""; }
    }
    return f.url;
  }

  function dropSupFile(id) {
    const n = Number(id);
    const item = SUP.files.find(f => f.id === n);
    if (item && item.url) {
      try { URL.revokeObjectURL(item.url); } catch (e) { /* 忽略 */ }
    }
    SUP.files = SUP.files.filter(f => f.id !== n);
  }

  function clearSupFiles() {
    SUP.files.forEach(f => {
      if (f.url) { try { URL.revokeObjectURL(f.url); } catch (e) { /* 忽略 */ } }
    });
    SUP.files = [];
    SUP.pending = false;
  }

  /* ───────── PDF 首帧快照: 上传前也能看到 PDF 长什么样 ───────── */
  let PDFJS_PROMISE = null;

  function loadPdfJs() {
    if (PDFJS_PROMISE) return PDFJS_PROMISE;
    PDFJS_PROMISE = new Promise((resolve, reject) => {
      if (window.pdfjsLib) { resolve(window.pdfjsLib); return; }
      const s = document.createElement("script");
      s.src = "/static/vendor/pdfjs/pdf.min.js";
      s.onload = () => {
        if (!window.pdfjsLib) { reject(new Error("pdf.js 加载异常")); return; }
        try {
          window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.js";
        } catch (e) { /* 忽略 */ }
        resolve(window.pdfjsLib);
      };
      s.onerror = () => reject(new Error("pdf.js 加载失败"));
      document.head.appendChild(s);
    });
    return PDFJS_PROMISE;
  }

  function isImgFile(f) {
    return String(f.file.type || "").startsWith("image/") ||
      [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"].includes(extOf(f.file.name));
  }

  function isPdfFile(f) {
    return String(f.file.type || "").toLowerCase() === "application/pdf" || extOf(f.file.name) === ".pdf";
  }

  async function buildPdfThumb(item) {
    if (item.pdfThumb !== undefined) return;
    item.pdfThumb = "";                 // 先占位, 失败时不再重试
    try {
      const lib = await loadPdfJs();
      const buf = await item.file.arrayBuffer();
      const doc = await lib.getDocument({ data: new Uint8Array(buf) }).promise;
      const page = await doc.getPage(1);
      const base = page.getViewport({ scale: 1 });
      const vp = page.getViewport({ scale: Math.max(0.12, 176 / Math.max(base.width, 1)) });
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(vp.width);
      canvas.height = Math.ceil(vp.height);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
      item.pdfThumb = canvas.toDataURL("image/jpeg", 0.82);
      try { doc.destroy(); } catch (e) { /* 忽略 */ }
    } catch (e) {
      item.pdfThumb = "";
    }
    drawMaterialPanel();
  }

  // 包裹归属只列未关闭的包裹
  function pkgs() {
    return ((SUP.data && SUP.data.packages) || [])
      .filter(p => (p.package_status || "") !== "cancelled");
  }
  function pos() { return (SUP.data && SUP.data.purchase_orders) || []; }

  /* ───────── 补录弹窗: 素材上传区 ───────── */

  async function renderFmSupplementMaterials(miaoshouId) {
    const box = document.getElementById("fmSupMaterials");
    if (!box) return;
    const key = String(miaoshouId || 0);
    if (SUP.key !== key) {
      SUP.key = key;
      SUP.miaoshouId = Number(miaoshouId) || 0;
      SUP.fmId = 0;
      SUP.data = null;
      clearSupFiles();
      SUP.poId = 0;
      SUP.pkgId = 0;
    }
    box.innerHTML = `<div style="font-size:0.72rem; color:#94a3b8;">⏳ 加载素材信息...</div>`;
    try {
      const sum = await orderApi("/api/fulfillment/materials-summary?order_ids=" +
        encodeURIComponent(String(miaoshouId)));
      let info = (sum.data || {})[String(miaoshouId)] || null;
      if (!info) {
        // 履约列表传入的已是 fm_orders.id, 直接按履约订单取
        info = { fm_order_id: Number(miaoshouId) || 0 };
      }
      SUP.fmId = info ? Number(info.fm_order_id || 0) : 0;
      if (SUP.fmId) {
        const ws = await orderApi("/api/fulfillment/orders/" + SUP.fmId);
        SUP.data = ws.data || null;
      }
    } catch (e) {
      /* 未进入履约体系时仍可展示提示 */
    }
    drawItemsBar();
    drawMaterialPanel();
  }

  /* 商品信息: SKU + 商品小图 (点击放大) */
  function drawItemsBar() {
    const box = document.getElementById("fmSupItems");
    if (!box) return;
    const order = (SUP.data && SUP.data.order) || {};
    const items = order.items || [];
    if (!SUP.fmId || !items.length) {
      box.style.display = "none";
      box.innerHTML = "";
      return;
    }
    box.style.display = "";
    box.innerHTML = `<div class="fm-sup-group-title">🏷️ 商品信息</div>` + items.map(it => {
      const pic = it.picUrl || it.originalPicUrl || "";
      const big = it.originalPicUrl || it.picUrl || "";
      const sku = it.platformOuterSkuId || it.platformItemId || it.platformSkuId || it.sku || "—";
      const title = it.title || it.name || order.product_label || "—";
      const thumb = pic
        ? `<img class="fm-item-thumb" src="${esc(pic)}" alt="" data-big="${esc(big)}"
            title="点击放大" onclick="openOrderImg(this.dataset.big, this.src)"
            onerror="this.style.visibility='hidden'">`
        : `<span class="fm-item-thumb"></span>`;
      return `<div class="fm-item-row">
        ${thumb}
        <div class="meta">
          <div class="nm" title="${esc(title)}">${esc(title)}</div>
          <div class="sku" title="${esc(sku)}">SKU：${esc(sku)}</div>
        </div>
        <div class="qty">× ${esc(it.quantity || 0)}</div>
      </div>`;
    }).join("");
  }

  function drawMaterialPanel() {
    const box = document.getElementById("fmSupMaterials");
    if (!box) return;
    if (!SUP.fmId) {
      box.innerHTML = `<div class="fm-sup-mat-head">📎 素材上传</div>
        <div style="font-size:0.74rem; color:#b91c1c; margin-top:6px; line-height:1.6;">
          该订单尚未进入履约体系（fm_orders 无对应记录），请先在履约侧同步后再上传素材。
        </div>`;
      return;
    }
    // 默认指向最新的采购单 / 包裹 (无则留空, 由后端自动建档)
    if (!SUP.poId && pos().length) {
      SUP.poId = Number(pos().slice().sort((a, b) => Number(b.id) - Number(a.id))[0].id) || 0;
    }
    if (!SUP.pkgId && pkgs().length) {
      SUP.pkgId = Number(pkgs().slice().sort((a, b) => Number(b.id) - Number(a.id))[0].id) || 0;
    }
    const pkgsHtml = pkgs().length
      ? pkgs().map(p => `<option value="${p.id}" ${Number(SUP.pkgId) === Number(p.id) ? "selected" : ""}>包裹 ${esc(p.app_package_no || p.tracking_no || p.id)}</option>`).join("")
      : `<option value="0">当前订单暂无包裹</option>`;
    const posHtml = pos().length
      ? pos().map(p => `<option value="${p.id}" ${Number(SUP.poId) === Number(p.id) ? "selected" : ""}>采购单 ${esc(p.purchase_no || p.supplier_name || ("#" + p.id))}</option>`).join("")
      : "";

    const counts = {};
    SUP.files.forEach(f => { counts[f.section] = (counts[f.section] || 0) + 1; });

    /* 某个素材槽下方直接展示已暂存快照 (点图放大, 右上角移除) */
    const thumbsOf = key => {
      const list = SUP.files.filter(f => f.section === key);
      if (!list.length) return "";
      return `<div class="fm-sup-thumbs">${list.map(f => {
        const url = supFileUrl(f);
        let inner;
        if (isImgFile(f)) {
          inner = `<img src="${esc(url)}" alt="">`;
        } else if (isPdfFile(f)) {
          // PDF 展示首帧快照; 尚未生成时先占位, 生成后自动重绘
          inner = f.pdfThumb
            ? `<img src="${esc(f.pdfThumb)}" alt="">`
            : `<span class="doc pdf">${f.pdfThumb === undefined ? "PDF…" : "PDF"}</span>`;
        } else {
          inner = `<span class="doc">${esc((extOf(f.file.name) || ".file").replace(".", "").toUpperCase().slice(0, 4))}</span>`;
        }
        return `<span class="fm-sup-thumb" title="${esc(f.file.name)} · ${sizeText(f.file.size)}">
            <span class="box" data-preview="${f.id}">${inner}</span>
            <button type="button" class="x" data-del="${f.id}" title="移除">✕</button>
          </span>`;
      }).join("")}</div>`;
    };

    const PKG_KEYS = ["delivery_note", "receipt", "invoice_forwarder"];
    const cardOf = s => {
      const n = counts[s.key] || 0;
      const disabled = PKG_KEYS.includes(s.key) && !pkgs().length;
      return `<div class="fm-sup-card">
        <button type="button" class="fm-sup-slot ${disabled ? "disabled" : ""}"
          data-slot="${s.key}" title="${esc(s.label)}（${s.exts.join(" ")}）">
          ${s.icon} ${esc(s.label)}${n ? `<span class="n">${n}</span>` : ""}
        </button>
        ${thumbsOf(s.key)}
        ${doneThumbsOf(s.key)}
      </div>`;
    };

    const ownerPo = `<select id="fmSupPo" class="fm-sup-owner-select" title="采购单归属">
        <option value="0">自动建档（默认）</option>${posHtml}
      </select>`;
    const ownerPkg = `<select id="fmSupPkg" class="fm-sup-owner-select" title="包裹归属"
        ${pkgs().length ? "" : "disabled"}>${pkgsHtml}</select>`;

    /* 已上传素材按分类索引: 直接展示在对应按钮下方, 一眼看清每类传了什么 */
    const uploadedMap = (() => {
      const map = {};
      const push = (cat, d) => {
        if (!cat) return;
        (map[cat] = map[cat] || []).push(d);
      };
      const data = SUP.data || {};
      // 只展示当前下拉选中的采购单 / 包裹下的素材, 切归属时同步切换
      const po = (data.purchase_orders || []).find(p => Number(p.id) === Number(SUP.poId));
      const pkg = (data.packages || []).find(p => Number(p.id) === Number(SUP.pkgId));
      (po ? po.documents || [] : []).forEach(d => push(d.category, d));
      (pkg ? pkg.documents || [] : []).forEach(d => push(d.category, d));
      (data.tax_certs || []).forEach(tc =>
        (tc.documents || []).forEach(d => push(d.category, d)));
      (data.invoices || []).forEach(inv => {
        const links = inv.links || [];
        const onPkg = links.some(l => l.owner_type === "package" && Number(l.owner_id) === Number(SUP.pkgId));
        const onPo = links.some(l => l.owner_type === "purchase_order" && Number(l.owner_id) === Number(SUP.poId));
        if (!onPkg && !onPo) return;
        // 归到哪一类由挂靠对象决定: 挂包裹=货代发票, 挂采购单=采购发票
        const cat = onPkg ? "invoice_forwarder" : "invoice_purchase";
        (inv.documents || []).forEach(d => push(cat, d));
      });
      return map;
    })();

    const doneThumbsOf = key => {
      const list = (uploadedMap[key] || []).slice(0, 6);
      if (!list.length) return "";
      return `<div class="fm-sup-thumbs done">${list.map(d => {
        const url = d.preview_url || d.thumb_url || "";
        const inner = url
          ? `<img src="${esc(encodeURI(url))}" alt="">`
          : `<span class="doc">${esc((extOf(d.file_name) || ".file").replace(".", "").toUpperCase().slice(0, 4))}</span>`;
        return `<span class="fm-sup-thumb done" title="已上传：${esc(d.file_name || "")}">
            <span class="box" onclick="openOrderImg('${esc(encodeURI(url))}')">${inner}</span>
            <b class="ok">✓</b>
            <button type="button" class="x" data-del-doc="${d.id}"
              data-doc-owner="${esc(d.owner_type || "")}" data-doc-owner-id="${d.owner_id || 0}"
              title="删除该素材">✕</button>
          </span>`;
      }).join("")}</div>`;
    };

    /* 采购类与包裹类各自成组: 标题行右侧归属下拉 + 素材槽 + 槽下方快照 + 已上传 */
    const GROUPS = [
      {
        title: "🧮 采购信息",
        owner: ownerPo,
        key: "po",
        keys: ["purchase_order_shot", "transfer_voucher", "invoice_purchase"],
      },
      {
        title: "📦 包裹信息",
        owner: ownerPkg,
        key: "pkg",
        keys: ["delivery_note", "receipt", "invoice_forwarder", "tax_cert"],
      },
    ];
    const groupsHtml = GROUPS.map(g => `<div class="fm-sup-group">
        <div class="fm-sup-group-head">
          <div class="fm-sup-group-title">${g.title}</div>
          ${g.owner}
        </div>
        <div class="fm-sup-mat-grid">${g.keys.map(k => cardOf(secMeta(k))).join("")}</div>
      </div>`).join("");

    box.innerHTML = `
      ${groupsHtml}
      <div class="fm-sup-actions">
        <span class="state">${SUP.files.length
        ? `已暂存 <b>${SUP.files.length}</b> 个文件，尚未上传`
        : "尚未选择素材"}</span>
      </div>
      <div id="fmSupFailList" class="fm-sup-fails" style="display:none;"></div>
      <div id="fmSupProgress" style="display:none; margin-top:8px; font-size:0.8rem; color:#1d4ed8;"></div>`;
  }

  function pickMaterial(section, cb) {
    const meta = secMeta(section);
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = meta.exts.join(",");
    input.onchange = () => cb(Array.from(input.files || []));
    input.click();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const box = document.getElementById("fmSupMaterials");
    if (box) {
      box.addEventListener("click", e => {
        const delDoc = e.target.closest("[data-del-doc]");
        if (delDoc) {
          deleteUploadedDoc(delDoc.dataset.delDoc, delDoc.dataset.docOwner, delDoc.dataset.docOwnerId);
          return;
        }
        const pv = e.target.closest("[data-preview]");
        if (pv) {
          openSupPreview(pv.dataset.preview);
          return;
        }
        const slot = e.target.closest("[data-slot]");
        if (slot) {
          if (slot.classList.contains("disabled")) {
            showToast("当前订单没有包裹，无法上传该类素材", "error");
            return;
          }
          const section = slot.dataset.slot;
          pickMaterial(section, files => {
            let added = 0;
            files.forEach(file => {
              const meta = secMeta(section);
              if (!meta.exts.includes(extOf(file.name))) {
                showToast(`「${file.name}」格式不支持`, "error");
                return;
              }
              if (file.size > 20 * 1048576) {
                showToast(`「${file.name}」超过 20MB`, "error");
                return;
              }
              const item = { id: ++SUP.seq, section, file };
              SUP.files.push(item);
              added += 1;
              if (isPdfFile(item)) buildPdfThumb(item);   // 异步生成 PDF 首帧快照
            });
            if (!added) return;
            // 仅暂存, 等弹窗底部统一提交时再上传
            drawMaterialPanel();
          });
          return;
        }
        const del = e.target.closest("[data-del]");
        if (del) {
          dropSupFile(del.dataset.del);
          drawMaterialPanel();
        }
      });
      // 归属选择记住, 重绘后仍指向同一张采购单 / 同一个包裹
      box.addEventListener("change", e => {
        const id = e.target && e.target.id;
        if (id !== "fmSupPo" && id !== "fmSupPkg") return;
        if (id === "fmSupPo") SUP.poId = Number(e.target.value) || 0;
        if (id === "fmSupPkg") SUP.pkgId = Number(e.target.value) || 0;
        drawMaterialPanel();      // 归属切换后同步刷新该类素材
      });
    }
  });

  function entryFor(file) {
    const meta = secMeta(file.section);
    const entry = { file_index: 0, category: "", target_type: "", target_id: 0 };
    const poSel = Number((document.getElementById("fmSupPo") || {}).value || 0);
    const pkgSel = Number((document.getElementById("fmSupPkg") || {}).value || 0) || SUP.pkgId || 0;
    if (file.section === "purchase_order_shot") {
      entry.category = "purchase_order_shot";
      // 首次提交(无归属)由后端建档; 选了采购单则追加为它的截图
      entry.target_type = "purchase_order";
      entry.target_id = poSel || SUP.poId || 0;
    } else if (file.section === "transfer_voucher") {
      entry.category = "transfer_voucher";
      entry.target_type = "purchase_order";
      entry.target_id = poSel || SUP.poId || 0;
    } else if (file.section === "invoice_purchase") {
      entry.category = "invoice";
      entry.target_type = "purchase_order";
      entry.target_id = poSel || SUP.poId || 0;
      entry.invoice_kind = "采购发票";
    } else if (file.section === "invoice_forwarder") {
      entry.category = "invoice";
      entry.target_type = "package";
      entry.target_id = pkgSel;
      entry.invoice_kind = "物流发票";
    } else if (file.section === "delivery_note" || file.section === "receipt") {
      entry.category = file.section;
      entry.target_type = "package";
      entry.target_id = pkgSel;
    } else {
      entry.category = "tax_cert";
    }
    return entry;
  }

  /* 一次请求提交全部暂存素材, 返回 { ok, failed: [{ name, reason }] }
     必须整批提交: 后端在同一批里才会把多张截图/凭证/发票合并到同一张采购单 */
  async function uploadSupMaterials() {
    const result = { ok: 0, failed: [] };
    if (!SUP.files.length) return result;
    if (!SUP.fmId) {
      result.failed.push({ name: "全部素材", reason: "该订单尚未进入履约体系" });
      return result;
    }
    if (!pkgs().length && SUP.files.some(f => ["delivery_note", "receipt", "invoice_forwarder"].includes(f.section))) {
      result.failed.push({ name: "包裹类素材", reason: "当前订单没有包裹" });
    }

    // 组装清单: file_index 与提交的文件顺序一一对应
    const queue = ORDER.reduce((acc, k) => acc.concat(SUP.files.filter(f => f.section === k)), []);
    const picked = [];
    const manifest = [];
    queue.forEach(item => {
      const entry = entryFor(item);
      // 采购单类缺归属时交给后端自动建档, 只有包裹类必须选包裹
      if (entry.target_type === "package" && !entry.target_id) {
        result.failed.push({ name: item.file.name, reason: "缺少归属包裹" });
        return;
      }
      entry.file_index = picked.length;
      picked.push(item);
      manifest.push(entry);
    });
    if (!picked.length) return result;

    const prog = document.getElementById("fmSupProgress");
    SUP.busy = true;
    if (prog) {
      prog.style.display = "";
      prog.textContent = `正在上传 ${picked.length} 个素材…`;
    }

    try {
      const fd = new FormData();
      picked.forEach(item => fd.append("files", item.file, item.file.name));
      fd.append("manifest", JSON.stringify(manifest));
      const res = await fmApi(`/api/fulfillment/orders/${SUP.fmId}/materials`, {
        method: "POST", body: fd,
      });
      const items = (res.data && res.data.items) || [];
      items.forEach(one => {
        const item = picked[Number(one.index)];
        if (!item) return;
        if (one.status === "success") {
          result.ok += 1;
          if (item.section === "purchase_order_shot" && !SUP.poId && one.target_id) {
            SUP.poId = Number(one.target_id) || 0;
          }
          dropSupFile(item.id);
        } else {
          result.failed.push({
            name: item.file.name,
            reason: one.message || one.msg || "服务端返回失败",
          });
        }
      });
      // 服务端未返回结果的按失败处理, 保留在暂存区
      picked.forEach((item, i) => {
        if (items.some(one => Number(one.index) === i)) return;
        if (result.failed.some(f => f.name === item.file.name)) return;
        result.failed.push({ name: item.file.name, reason: "未返回上传结果" });
      });
    } catch (e) {
      picked.forEach(item => result.failed.push({
        name: item.file.name, reason: e.message || "上传失败",
      }));
    }

    SUP.busy = false;
    if (prog) {
      prog.textContent = result.failed.length
        ? `已上传 ${result.ok} 个，失败 ${result.failed.length} 个`
        : `已上传 ${result.ok} 个素材`;
      prog.style.display = result.ok || result.failed.length ? "" : "none";
    }
    return result;
  }

  function showSupFails(failed, okCount) {
    const box = document.getElementById("fmSupFailList");
    if (!box) return;
    box.style.display = "";
    box.innerHTML =
      `<div class="t">⚠️ ${failed.length} 个素材提交失败${okCount ? `（已有 ${okCount} 个上传成功）` : ""}</div>` +
      failed.map(f => `<div class="item">· ${esc(f.name)}：${esc(f.reason || "未知原因")}</div>`).join("") +
      `<div class="tip">失败项仍保留在上方暂存区，可删除后重新提交。</div>`;
  }

  function hideSupFails() {
    const box = document.getElementById("fmSupFailList");
    if (box) { box.style.display = "none"; box.innerHTML = ""; }
  }

  /* 统一提交: 补录字段 + 暂存素材, 全成功才关闭弹窗 */
  async function saveOrderSupplementUnified() {
    const btn = document.getElementById("suppSaveBtn");
    if (btn && btn.disabled) return;
    if (typeof collectOrderSupplement !== "function") {
      showToast("页面脚本未就绪，请刷新后重试", "error");
      return;
    }
    const payload = collectOrderSupplement();
    if (!payload) return;

    hideSupFails();
    const oldText = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "提交中..."; }

    let saved = false;
    try {
      await postOrderSupplement(payload);
      saved = true;
    } catch (e) {
      if (e.message !== "未登录") showToast("补录信息保存失败：" + e.message, "error");
    }

    let result = { ok: 0, failed: [] };
    if (saved && SUP.files.length) result = await uploadSupMaterials();

    if (btn) { btn.disabled = false; btn.textContent = oldText || "提交补录与素材"; }

    if (!saved) {
      drawMaterialPanel();
      return;
    }

    if (result.failed.length) {
      drawMaterialPanel();          // 重绘会重建失败清单容器, 之后再渲染
      showSupFails(result.failed, result.ok);
      showToast(`素材成功 ${result.ok} 个，失败 ${result.failed.length} 个`, "error");
      return;
    }

    closeOrderSupplement();
    await loadOrders();
    showToast(result.ok ? `提交完成，已上传 ${result.ok} 个素材` : "补录信息已保存", "success");
  }

  /* 删除已上传素材: 发票走发票接口, 其它走文档接口; 采购单空则由后端连带删除 */
  async function deleteUploadedDoc(docId, ownerType, ownerId) {
    if (!docId) return;
    if (!window.confirm("确认删除这个已上传的素材？删除后不可恢复")) return;
    try {
      if (ownerType === "invoice") {
        await fmApi(`/api/fulfillment/invoices/${Number(ownerId) || 0}`, { method: "DELETE" });
      } else {
        await fmApi(`/api/fulfillment/documents/${Number(docId)}`, { method: "DELETE" });
      }
      showToast("素材已删除", "success");
      await renderFmSupplementMaterials(SUP.key);
      await loadOrders();
    } catch (e) {
      if (e.message !== "未登录") showToast("删除失败：" + e.message, "error");
    }
  }

  /* ───────── 暂存素材预览 ───────── */

  /* 把 PDF 第一页渲染成高清图片 (用于弹框内放大, 不新开页签) */
  async function renderPdfImage(item, targetWidth = 900) {
    const lib = await loadPdfJs();
    const buf = await item.file.arrayBuffer();
    const doc = await lib.getDocument({ data: new Uint8Array(buf) }).promise;
    const page = await doc.getPage(1);
    const base = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: Math.max(0.3, targetWidth / Math.max(base.width, 1)) });
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(vp.width);
    canvas.height = Math.ceil(vp.height);
    await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise;
    const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
    try { doc.destroy(); } catch (e) { /* 忽略 */ }
    return dataUrl;
  }

  async function openSupPreview(id) {
    const item = SUP.files.find(f => f.id === Number(id));
    if (!item) return;
    const modal = document.getElementById("fmSupPreviewModal");
    const img = document.getElementById("fmSupPreviewImg");
    const cap = document.getElementById("fmSupPreviewCap");
    if (!modal || !img) return;
    if (cap) cap.textContent = `${secMeta(item.section).label} · ${item.file.name}`;

    if (isImgFile(item)) {
      img.src = supFileUrl(item);
      img.style.display = "block";
      modal.style.display = "flex";
      return;
    }
    if (!isPdfFile(item)) {
      // 非图片非 PDF: 仍交回原文件 (浏览器自行处理)
      const url = supFileUrl(item);
      if (url) window.open(url, "_blank", "noopener");
      return;
    }

    // PDF: 弹框内展示首帧, 先给缩略图占位再换成高清
    img.style.display = item.pdfThumb ? "block" : "none";
    if (item.pdfThumb) img.src = item.pdfThumb;
    modal.style.display = "flex";
    if (item.pdfBig) {
      img.src = item.pdfBig;
      img.style.display = "block";
      return;
    }
    try {
      if (cap) cap.textContent = `${secMeta(item.section).label} · ${item.file.name}（渲染中…）`;
      item.pdfBig = await renderPdfImage(item);
      img.src = item.pdfBig;
      img.style.display = "block";
      if (cap) cap.textContent = `${secMeta(item.section).label} · ${item.file.name}`;
    } catch (e) {
      if (cap) cap.textContent = `${secMeta(item.section).label} · ${item.file.name}（预览失败）`;
    }
  }

  function closeSupPreview() {
    const modal = document.getElementById("fmSupPreviewModal");
    if (modal) modal.style.display = "none";
    const img = document.getElementById("fmSupPreviewImg");
    if (img) img.removeAttribute("src");
  }

  /* ───────── 列表图标 → 素材查看 (只读) ───────── */

  let FM_VIEW = { fmId: 0, miaoshouId: 0, orderSn: "" };

  async function openFmMaterials(fmId, miaoshouId, orderSn) {
    const modal = document.getElementById("fmMatModal");
    if (!modal) return;
    FM_VIEW = { fmId: Number(fmId || 0), miaoshouId: Number(miaoshouId || 0), orderSn: orderSn || "" };
    document.getElementById("fmMatSub").textContent = orderSn || "—";
    document.getElementById("fmMatBody").innerHTML =
      `<div style="text-align:center; padding:30px; color:#94a3b8;">⏳ 加载中...</div>`;
    modal.style.display = "flex";

    if (!FM_VIEW.fmId) {
      // 未进入履约体系时尝试按妙手订单号反查
      try {
        const sum = await orderApi("/api/fulfillment/materials-summary?order_ids=" +
          encodeURIComponent(String(FM_VIEW.miaoshouId)) +
          "&order_sns=" + encodeURIComponent(FM_VIEW.orderSn));
        const info = (sum.data || {})[String(FM_VIEW.miaoshouId)] ||
          (sum.data || {})["sn:" + FM_VIEW.orderSn] || null;
        FM_VIEW.fmId = info ? Number(info.fm_order_id || 0) : 0;
      } catch (e) { /* ignore */ }
    }
    if (!FM_VIEW.fmId) {
      document.getElementById("fmMatBody").innerHTML =
        `<div style="text-align:center; padding:30px; color:#94a3b8;">
          该订单尚未进入履约体系，暂无素材<br>
          <span style="font-size:0.74rem;">同步履约数据后可在此查看</span>
        </div>`;
      return;
    }
    try {
      const ws = await orderApi("/api/fulfillment/orders/" + FM_VIEW.fmId);
      renderFmMaterialList(ws.data || {});
    } catch (e) {
      document.getElementById("fmMatBody").innerHTML =
        `<div style="text-align:center; padding:30px; color:#dc2626;">❌ ${esc(e.message)}</div>`;
    }
  }

  function docRow(d) {
    const url = d.relative_url || d.url || "";
    const name = d.file_name || d.name || "文件";
    return `<div style="display:flex; gap:6px; align-items:center; font-size:0.74rem;
      padding:3px 0; border-bottom:1px dashed #f1f5f9;">
      <span>📎</span>
      ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener"
        style="color:#1d4ed8; text-decoration:none; flex:1; min-width:0; overflow:hidden;
        text-overflow:ellipsis; white-space:nowrap;">${esc(name)}</a>`
        : `<span style="flex:1;">${esc(name)}</span>`}
      <span style="color:#94a3b8;">${sizeText(d.size_bytes)}</span>
    </div>`;
  }

  function renderFmMaterialList(data) {
    const groups = {};
    const push = (key, docs) => {
      (docs || []).forEach(d => {
        (groups[key] || (groups[key] = [])).push(d);
      });
    };
    (data.packages || []).forEach(p => {
      push("delivery_note", (p.documents || []).filter(d => d.category === "delivery_note"));
      push("receipt", (p.documents || []).filter(d => d.category === "receipt"));
    });
    (data.purchase_orders || []).forEach(po => {
      push("purchase_order_shot", (po.documents || []).filter(d => d.category === "purchase_order_shot"));
      push("transfer_voucher", (po.documents || []).filter(d => d.category === "transfer_voucher"));
    });
    (data.invoices || []).forEach(inv => {
      const key = (inv.invoice_kind || "") === "物流发票" ? "invoice_forwarder" : "invoice_purchase";
      push(key, inv.documents || []);
    });
    (data.tax_certs || []).forEach(tc => push("tax_cert", tc.documents || []));

    const html = SECTIONS.map(s => {
      const list = groups[s.key] || [];
      if (!list.length) return "";
      return `<div style="margin-bottom:10px;">
        <div style="font-size:0.76rem; font-weight:700; color:#334155; margin-bottom:2px;">
          ${s.icon} ${esc(s.label)} <span style="color:#94a3b8; font-weight:400;">(${list.length})</span>
        </div>
        ${list.map(docRow).join("")}
      </div>`;
    }).join("");

    document.getElementById("fmMatBody").innerHTML = html ||
      `<div style="text-align:center; padding:30px; color:#94a3b8;">
        暂无履约素材，可在「补录 → 素材上传」中一次性提交</div>`;
  }

  function closeFmMaterials() {
    const modal = document.getElementById("fmMatModal");
    if (modal) modal.style.display = "none";
  }

  function openFmSupplementForCurrent() {
    closeFmMaterials();
    if (FM_VIEW.miaoshouId) openOrderSupplement(FM_VIEW.miaoshouId);
  }

  /* ───────── 详情 / 轨迹: 数据全部来自履约模块 ───────── */

  function kv(label, value) {
    return `<div style="padding:5px 0; border-bottom:1px dashed #e2e8f0; display:flex; gap:12px;">
      <span style="color:#64748b; font-size:0.78rem; min-width:82px; flex-shrink:0;">${label}</span>
      <span style="font-size:0.8rem; color:#0f172a; flex:1; text-align:right; word-break:break-all;">${value || "—"}</span>
    </div>`;
  }

  async function openFmDetailModal(id) {
    const modal = document.getElementById("orderDetailModal");
    const bodyEl = document.getElementById("orderDetailBody");
    if (!modal || !bodyEl) return;
    document.getElementById("orderDetailTitle").innerText = "订单详情";
    document.getElementById("orderDetailSub").innerText = "加载中...";
    bodyEl.innerHTML = `<div style="text-align:center; padding:36px; color:#94a3b8;">⏳ 正在加载...</div>`;
    modal.style.display = "flex";
    try {
      const res = await orderApi("/api/fulfillment/orders/" + id);
      const d = res.data || {};
      const o = d.order || {};
      const ps = d.summary || {};
      const items = o.items || [];
      const pkgs = d.packages || [];
      const first = pkgs[0] || {};
      document.getElementById("orderDetailTitle").innerText = o.order_sn || "订单详情";
      document.getElementById("orderDetailSub").innerHTML =
        `${esc(o.shop_name || "—")} · ${esc(o.order_status_text || o.order_status || "—")}
         · 包裹 ${ps.package_count || 0} / 采购单 ${ps.purchase_order_count || 0}
         / 发票 ${ps.invoice_count || 0} / 清关报税 ${ps.tax_cert_count || 0}`;

      const itemCards = items.map(it => `
        <div style="display:flex; gap:10px; padding:8px 10px; border:1px solid #e2e8f0;
          border-radius:8px; margin-bottom:6px; background:#fff;">
          <img src="${esc(it.picUrl || it.originalPicUrl || "")}" alt=""
            style="width:56px; height:56px; object-fit:cover; border-radius:6px; background:#f1f5f9; flex-shrink:0;"
            onerror="this.style.visibility='hidden'">
          <div style="flex:1; min-width:0;">
            <div style="font-size:0.8rem; color:#0f172a; line-height:1.45;">${esc(o.product_label || it.title || it.name || "—")}</div>
            ${o.product_label && (it.title || it.name) && o.product_label !== (it.title || it.name)
        ? `<div style="font-size:0.7rem; color:#94a3b8; margin-top:2px; line-height:1.4;">${esc(it.title || it.name)}</div>` : ""}
            <div style="font-size:0.72rem; color:#94a3b8; margin-top:4px;">
              SKU: ${esc(it.platformOuterSkuId || it.platformItemId || it.sku || "—")}
            </div>
          </div>
          <div style="text-align:right; flex-shrink:0;">
            <div style="font-size:0.8rem; font-weight:700; color:#0f172a;">${esc(fmtMoney(it.originalPrice || it.unitPrice || 0, o.currency))}</div>
            <div style="font-size:0.72rem; color:#64748b;">× ${esc(it.quantity || 0)}</div>
          </div>
        </div>`).join("");

      bodyEl.innerHTML = `
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:0 24px;">
          <div>
            <div style="font-weight:700; font-size:0.85rem; color:#334155; margin-bottom:6px;">📋 订单信息</div>
            ${kv("平台订单号", esc(o.order_sn))}
            ${kv("妙手包裹号", esc(o.app_package_no || first.app_package_no || ""))}
            ${kv("店铺", esc(o.shop_name))}
            ${kv("下单时间", esc(o.gmt_order))}
            ${kv("支付时间", esc(o.gmt_pay))}
            ${kv("平台状态", esc(o.order_status_text || o.order_status))}
            ${kv("目的国家", esc(o.dest_country_name || o.dest_country))}
            ${kv("商品件数", esc(o.items_count || items.length))}
          </div>
          <div>
            <div style="font-weight:700; font-size:0.85rem; color:#334155; margin-bottom:6px;">💰 金额 / 物流 / 补录</div>
            ${kv("订单金额", esc(fmtMoney(o.order_amount, o.currency)))}
            ${kv("支付金额", esc(fmtMoney(o.pay_amount, o.currency)))}
            ${kv("运单号", esc(first.tracking_no))}
            ${kv("物流公司", esc(first.tracking_company))}
            ${kv("包裹状态", esc(first.package_status_text || first.package_status))}
            ${kv("采购日期", esc(o.purchase_date))}
            ${kv("国内包裹数", esc(o.domestic_package_count || ""))}
            ${kv("国内单号", esc(o.domestic_tracking_no))}
          </div>
        </div>
        <div style="margin-top:16px;">
          <div style="font-weight:700; font-size:0.85rem; color:#334155; margin-bottom:8px;">📦 商品明细（${items.length}）</div>
          ${itemCards || `<div style="color:#94a3b8; font-size:0.8rem;">无商品明细</div>`}
        </div>`;
    } catch (e) {
      document.getElementById("orderDetailSub").innerText = "加载失败";
      bodyEl.innerHTML = `<div style="text-align:center; padding:36px; color:#dc2626;">❌ ${esc(e.message)}</div>`;
    }
  }

  async function openFmTrackModal(id) {
    const modal = document.getElementById("orderTrackModal");
    const sub = document.getElementById("orderTrackSub");
    const bodyEl = document.getElementById("orderTrackBody");
    if (!modal || !bodyEl) return;
    sub.innerText = "加载中...";
    bodyEl.innerHTML = `<div style="text-align:center; padding:34px; color:#94a3b8;">⏳ 加载中...</div>`;
    modal.style.display = "flex";
    try {
      const res = await orderApi("/api/fulfillment/orders/" + id);
      const d = res.data || {};
      const pkgs = d.packages || [];
      const o = d.order || {};
      sub.innerHTML = `${esc(o.order_sn || "")} · ${pkgs.length} 个包裹`;
      if (!pkgs.length) {
        bodyEl.innerHTML = `<div style="text-align:center; padding:30px; color:#94a3b8;">该订单暂无匹配包裹，暂无轨迹</div>`;
        return;
      }
      const jumpBtn = document.getElementById("orderTrackJumpBtn");
      const no = String(pkgs[0].tracking_no || "").trim();
      if (jumpBtn) jumpBtn.disabled = !no;
      // 供 orders.js 的 17TRACK 跳转使用
      if (typeof trackState !== "undefined") {
        trackState.data = { tracking_no: no, channel_hawbcode: "" };
      }
      bodyEl.innerHTML = pkgs.map(p => `
        <div style="border:1px solid #e2e8f0; border-radius:8px; padding:10px 12px; margin-bottom:8px; background:#fff;">
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:0.8rem;">
            <b>📦 ${esc(p.app_package_no || p.source_package_id || "包裹")}</b>
            <span style="color:#1d4ed8; font-family:ui-monospace, Menlo, monospace;">${esc(p.tracking_no || "无运单号")}</span>
            <span class="tag-badge" style="background:#f1f5f9; color:#475569; border:none;">${esc(p.track_status_name || "—")}</span>
          </div>
          <div style="font-size:0.74rem; color:#475569; margin-top:6px; line-height:1.5;">
            ${esc(p.track_desc || "暂无轨迹")}
          </div>
          <div style="font-size:0.7rem; color:#94a3b8; margin-top:4px;">
            更新时间：${esc(p.track_time || "—")} · 承运商：${esc(p.tracking_company || "—")}
          </div>
        </div>`).join("");
    } catch (e) {
      bodyEl.innerHTML = `<div style="text-align:center; padding:30px; color:#dc2626;">❌ ${esc(e.message)}</div>`;
    }
  }

  /* 关闭补录弹窗时释放暂存的预览 blob, 避免内存泄漏 */
  const baseCloseOrderSupplement = window.closeOrderSupplement;
  window.closeOrderSupplement = function () {
    clearSupFiles();
    // 下次打开重新指向最新的采购单 / 包裹
    SUP.poId = 0;
    SUP.pkgId = 0;
    if (typeof baseCloseOrderSupplement === "function") baseCloseOrderSupplement();
  };

  /* 暴露给 orders.js / 模板 */
  window.renderFmSupplementMaterials = renderFmSupplementMaterials;
  window.saveOrderSupplementUnified = saveOrderSupplementUnified;
  window.openSupPreview = openSupPreview;
  window.closeSupPreview = closeSupPreview;
  window.openFmMaterials = openFmMaterials;
  window.closeFmMaterials = closeFmMaterials;
  window.openFmSupplementForCurrent = openFmSupplementForCurrent;
  window.openFmDetailModal = openFmDetailModal;
  window.openFmTrackModal = openFmTrackModal;
})();
