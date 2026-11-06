/**
 * 订单素材统一上传页
 * 文件仅在浏览器内暂存 (File 对象), 提交时按分类顺序逐个发送;
 * 提交前不产生任何接口写入, 页面上实时显示每个文件的处理进度与结果。
 *
 * 分组: 采购信息 = 采购单截图 / 转账凭证 / 采购发票
 *       包裹信息 = 发货单 / 签收单 / 货代发票 / 清关报税
 */
(function () {
  const FM = window.FM;
  const $ = sel => document.querySelector(sel);
  const orderId = Number(new URLSearchParams(location.search).get("order_id") || 0);
  const UP = { data: null, staged: [], seq: 0, submitting: false };

  const IMG_PDF = [".jpg", ".jpeg", ".png", ".webp", ".pdf"];
  const DOC_ALL = IMG_PDF.concat([".bmp", ".gif", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z"]);
  // category 为后端素材分类; 采购发票与货代发票后端同为 invoice, 由 target + invoice_kind 区分
  const SECTION_META = {
    purchase_order_shot: { label: "采购单截图", icon: "🧾", exts: IMG_PDF, category: "purchase_order_shot" },
    transfer_voucher: { label: "转账凭证", icon: "💳", exts: IMG_PDF, category: "transfer_voucher" },
    invoice_purchase: { label: "采购发票", icon: "📄", exts: IMG_PDF, category: "invoice" },
    delivery_note: { label: "发货单", icon: "📦", exts: DOC_ALL, category: "delivery_note" },
    receipt: { label: "签收单", icon: "✍️", exts: DOC_ALL, category: "receipt" },
    invoice_forwarder: { label: "货代发票", icon: "🚚", exts: IMG_PDF, category: "invoice" },
    tax_cert: { label: "清关报税", icon: "🛃", exts: DOC_ALL, category: "tax_cert" },
  };
  // 提交顺序: 采购单截图先生成采购单, 转账凭证/采购发票才能挂到该采购单
  const SECTION_ORDER = [
    "purchase_order_shot", "transfer_voucher", "invoice_purchase",
    "delivery_note", "receipt", "invoice_forwarder", "tax_cert",
  ];
  const PKG_SECTIONS = ["delivery_note", "receipt", "invoice_forwarder"];

  function sizeText(bytes) {
    const n = Number(bytes || 0);
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(2) + " MB";
  }

  function extOf(name) {
    const i = String(name || "").lastIndexOf(".");
    return i < 0 ? "" : String(name).slice(i).toLowerCase();
  }

  function pkgList() {
    return (UP.data && UP.data.packages) || [];
  }

  function hasPoShot() {
    return UP.staged.some(i => i.section === "purchase_order_shot");
  }

  function selId(selector) {
    const sel = $(selector);
    return Number(sel ? sel.value : 0) || 0;
  }

  // 未指定采购单, 且本次没有采购单截图 → 没有可挂靠的采购单
  function needsPoFromShot(selectedId) {
    return !selectedId && !hasPoShot();
  }

  function categoryOf(section) {
    return (SECTION_META[section] || {}).category || "";
  }

  function setDropEnabled(section, enabled, subText) {
    const drop = document.querySelector(`[data-drop="${section}"]`);
    if (!drop) return;
    drop.classList.toggle("disabled", !enabled);
    const input = drop.querySelector("[data-input]");
    if (input) input.disabled = !enabled;
    const sub = drop.querySelector(".fm-drop-sub");
    if (sub && subText) sub.textContent = subText;
  }

  function refreshDependencies() {
    const hasPkg = pkgList().length > 0;
    ["delivery_note", "receipt"].forEach(section => {
      setDropEnabled(section, hasPkg,
        hasPkg ? "图片 / PDF / 压缩包" : "暂无包裹，不可上传");
    });
    setDropEnabled("invoice_forwarder", hasPkg,
      hasPkg ? "jpg / png / webp / pdf" : "暂无包裹，不可上传");

    // 转账凭证 / 采购发票允许先暂存, 提交时再校验采购单
    const voucherOk = !needsPoFromShot(selId("#fmVoucherPo"));
    setDropEnabled("transfer_voucher", true,
      voucherOk ? "jpg / png / webp / pdf" : "需先添加采购单截图");
    const invPoOk = !needsPoFromShot(selId("#fmInvPo"));
    setDropEnabled("invoice_purchase", true,
      invPoOk ? "jpg / png / webp / pdf" : "需先添加采购单截图");

    const hint = $("#fmPkgHint");
    if (hint) {
      hint.textContent = hasPkg ? "按包裹归档 / 清关报税" : "暂无包裹，不可上传";
      hint.style.color = hasPkg ? "" : "#dc2626";
    }
  }

  function packageOptions(select, placeholder) {
    if (!select) return;
    const pkgs = pkgList();
    select.innerHTML = pkgs.length
      ? pkgs.map(p => `<option value="${p.id}">${FM.esc(p.app_package_no || p.tracking_no || p.source_package_id)}${p.tracking_no ? " · " + FM.esc(p.tracking_no) : ""}</option>`).join("")
      : `<option value="0">${FM.esc(placeholder || "当前订单暂无包裹")}</option>`;
    select.disabled = !pkgs.length;
  }

  function poOptions() {
    const pos = (UP.data && UP.data.purchase_orders) || [];
    const html = `<option value="0">自动关联本次生成的采购单</option>` + pos.map(po =>
      `<option value="${po.id}">关联已有：${FM.esc(po.purchase_no || po.supplier_name || ("#" + po.id))}</option>`
    ).join("");
    ["#fmVoucherPo", "#fmInvPo"].forEach(sel => {
      const el = $(sel);
      if (el) el.innerHTML = html;
    });
  }

  function targetLabel(item) {
    if (item.section === "purchase_order_shot") return "新建采购单";
    if (item.section === "transfer_voucher") {
      const sel = $("#fmVoucherPo");
      return sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "本次生成的采购单";
    }
    if (item.section === "invoice_purchase") {
      const sel = $("#fmInvPo");
      return "采购单 · " + (sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "本次生成");
    }
    if (item.section === "invoice_forwarder") {
      const sel = $("#fmInvPkg");
      return "包裹 · " + (sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "未选择");
    }
    if (item.section === "delivery_note" || item.section === "receipt") {
      const sel = item.section === "delivery_note" ? $("#fmDeliveryPkg") : $("#fmReceiptPkg");
      return "包裹 · " + (sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "未选择");
    }
    return "归档到当前订单";
  }

  function renderStage() {
    document.querySelectorAll("[data-stage]").forEach(box => { box.innerHTML = ""; });
    const groups = {};
    UP.staged.forEach(item => {
      const meta = SECTION_META[item.section];
      const list = groups[item.section] || (groups[item.section] = []);
      list.push(`
        <div class="fm-stage-item" data-stage-id="${item.id}">
          <div class="fm-stage-thumb">${item.previewUrl ? `<img src="${item.previewUrl}" alt="">` : (meta ? meta.icon : "📎")}</div>
          <div class="fm-stage-info">
            <div class="fm-stage-name" title="${FM.esc(item.file.name)}">${FM.esc(item.file.name)}</div>
            <div class="fm-stage-meta">${sizeText(item.file.size)} · ${FM.esc(targetLabel(item))}</div>
          </div>
          <button class="fm-stage-remove" type="button" data-remove="${item.id}" title="移除">✕</button>
        </div>`);
    });
    Object.keys(groups).forEach(key => {
      const box = document.querySelector(`[data-stage="${key}"]`);
      if (box) box.innerHTML = groups[key].join("");
    });
    document.querySelectorAll("[data-stage]").forEach(box => {
      if (!box.innerHTML.trim()) box.innerHTML = '<div class="fm-stage-empty">尚未添加文件</div>';
    });

    const total = UP.staged.reduce((s, i) => s + Number(i.file.size || 0), 0);
    const kinds = [...new Set(UP.staged.map(i => SECTION_META[i.section].label))];
    $("#fmStageCount").textContent = UP.staged.length;
    $("#fmStageSize").textContent = sizeText(total);
    $("#fmStageKinds").textContent = kinds.length ? kinds.join("、") : "—";
    $("#fmSubmitAll").disabled = !UP.staged.length || UP.submitting || !orderId || !window.FM_CAN_EDIT;
    $("#fmClearAll").disabled = !UP.staged.length || UP.submitting;
    refreshDependencies();
  }

  function addFiles(section, fileList) {
    const meta = SECTION_META[section];
    if (!meta) return;
    if (PKG_SECTIONS.includes(section) && !pkgList().length) {
      FM.toast("当前订单没有包裹，无法上传" + meta.label, "error");
      return;
    }
    const files = Array.from(fileList || []);
    if (!files.length) return;
    if (UP.staged.length + files.length > 60) {
      FM.toast("单次最多暂存 60 个文件，请分批提交", "error");
      return;
    }
    let added = 0;
    files.forEach(file => {
      if (!meta.exts.includes(extOf(file.name))) {
        FM.toast(`「${file.name}」格式不支持`, "error");
        return;
      }
      if (file.size > 20 * 1024 * 1024) {
        FM.toast(`「${file.name}」超过 20MB`, "error");
        return;
      }
      UP.staged.push({
        id: ++UP.seq,
        section,
        file,
        previewUrl: /^image\//.test(file.type) ? URL.createObjectURL(file) : "",
      });
      added += 1;
    });
    if (added) renderStage();
  }

  function removeItem(id) {
    const idx = UP.staged.findIndex(i => i.id === id);
    if (idx < 0) return;
    if (UP.staged[idx].previewUrl) URL.revokeObjectURL(UP.staged[idx].previewUrl);
    UP.staged.splice(idx, 1);
    renderStage();
  }

  function clearAll() {
    if (!UP.staged.length) return;
    if (!confirm("确定清空暂存清单？已选择的文件不会上传。")) return;
    UP.staged.forEach(i => { if (i.previewUrl) URL.revokeObjectURL(i.previewUrl); });
    UP.staged = [];
    renderStage();
  }

  // 单条 manifest 条目; ctx.poId 为本次采购单截图新建出的采购单 id
  function entryFor(item, ctx) {
    const entry = { file_index: 0, category: categoryOf(item.section), target_type: "", target_id: 0 };
    if (item.section === "invoice_purchase") {
      entry.target_type = "purchase_order";
      entry.target_id = selId("#fmInvPo") || Number((ctx && ctx.poId) || 0);
      entry.invoice_kind = "采购发票";
    } else if (item.section === "invoice_forwarder") {
      entry.target_type = "package";
      entry.target_id = selId("#fmInvPkg");
      entry.invoice_kind = "物流发票";
    } else if (item.section === "transfer_voucher") {
      entry.target_type = "purchase_order";
      entry.target_id = selId("#fmVoucherPo") || Number((ctx && ctx.poId) || 0);
    } else if (item.section === "delivery_note" || item.section === "receipt") {
      const sel = item.section === "delivery_note" ? $("#fmDeliveryPkg") : $("#fmReceiptPkg");
      entry.target_type = "package";
      entry.target_id = Number(sel.value || 0);
    }
    return entry;
  }

  function zeroTargetMessage(section) {
    if (section === "invoice_purchase") return "采购发票需要采购单：本次采购单截图未生成成功，请重试或选择已有采购单";
    if (section === "transfer_voucher") return "转账凭证需要采购单：本次采购单截图未生成成功，请重试或选择已有采购单";
    if (section === "invoice_forwarder") return "货代发票需要选择包裹";
    if (section === "delivery_note" || section === "receipt") return "请选择要归档的包裹";
    return "缺少归属对象";
  }

  function orderedQueue() {
    return SECTION_ORDER.reduce((acc, key) =>
      acc.concat(UP.staged.filter(i => i.section === key)), []);
  }

  function validateBeforeSubmit() {
    const hasPkg = pkgList().length > 0;
    if (!hasPkg && UP.staged.some(i => PKG_SECTIONS.includes(i.section))) {
      return "当前订单没有包裹，请先移除发货单/签收单/货代发票";
    }
    if (UP.staged.some(i => i.section === "delivery_note") && !selId("#fmDeliveryPkg")) {
      return "发货单需要先选择包裹";
    }
    if (UP.staged.some(i => i.section === "receipt") && !selId("#fmReceiptPkg")) {
      return "签收单需要先选择包裹";
    }
    if (UP.staged.some(i => i.section === "invoice_forwarder") && !selId("#fmInvPkg")) {
      return "货代发票需要先选择包裹";
    }
    if (UP.staged.some(i => i.section === "transfer_voucher") && needsPoFromShot(selId("#fmVoucherPo"))) {
      return "没有采购单素材：转账凭证需挂到采购单，请上传采购单截图或选择已有采购单";
    }
    if (UP.staged.some(i => i.section === "invoice_purchase") && needsPoFromShot(selId("#fmInvPo"))) {
      return "没有采购单素材：采购发票需挂到采购单，请上传采购单截图或选择已有采购单";
    }
    return "";
  }

  function resetProgress(total) {
    $("#fmResultBox").style.display = "";
    $("#fmResultSummary").textContent = "";
    $("#fmResultList").innerHTML = "";
    $("#fmProgressChip").textContent = `0/${total}`;
    $("#fmProgressFill").style.width = "0%";
    $("#fmProgressText").textContent = `准备处理 ${total} 个文件…`;
    $("#fmBackAfter").onclick = () => { location.href = "/fulfillment?order_id=" + orderId; };
  }

  function setProgress(done, total, text) {
    $("#fmProgressFill").style.width = (total ? Math.round(done / total * 100) : 0) + "%";
    $("#fmProgressChip").textContent = `${done}/${total}`;
    if (text) $("#fmProgressText").textContent = text;
  }

  function appendRunning(name) {
    const row = document.createElement("div");
    row.className = "fm-result-item run";
    row.innerHTML = `⏳ ${FM.esc(name)} · 处理中…`;
    const list = $("#fmResultList");
    list.appendChild(row);
    list.scrollTop = list.scrollHeight;
    return row;
  }

  async function submitAll() {
    if (UP.submitting || !UP.staged.length) return;
    if (!window.FM_CAN_EDIT) {
      FM.toast("无素材上传权限", "error");
      return;
    }
    const err = validateBeforeSubmit();
    if (err) {
      FM.toast(err, "error");
      return;
    }

    const queue = orderedQueue();
    const total = queue.length;
    const btn = $("#fmSubmitAll");
    UP.submitting = true;
    btn.textContent = "⏳ 处理中…";
    btn.disabled = true;
    $("#fmClearAll").disabled = true;
    resetProgress(total);

    const ctx = { poId: 0 };
    const okIds = new Set();
    let ok = 0;
    let failed = 0;

    for (let i = 0; i < total; i++) {
      const item = queue[i];
      const row = appendRunning(item.file.name);
      setProgress(i, total, `正在处理 ${i + 1}/${total}：${item.file.name}`);

      const entry = entryFor(item, ctx);
      if (entry.target_type && !entry.target_id) {
        failed += 1;
        row.className = "fm-result-item err";
        row.innerHTML = `❌ ${FM.esc(item.file.name)}<br>${FM.esc(zeroTargetMessage(item.section))}`;
        setProgress(i + 1, total, `已完成 ${i + 1}/${total}`);
        continue;
      }

      const fd = new FormData();
      fd.append("files", item.file, item.file.name);
      fd.append("manifest", JSON.stringify([entry]));

      let detail = null;
      try {
        const res = await FM.api(`/api/fulfillment/orders/${orderId}/materials`, {
          method: "POST", body: fd,
        });
        detail = (res.data && res.data.items && res.data.items[0]) || null;
        if (!detail) detail = { status: "success", file_name: item.file.name, message: res.msg || "已处理" };
      } catch (e) {
        detail = { status: "failed", file_name: item.file.name, message: e.message || "上传失败" };
      }

      const good = detail.status === "success";
      if (good) {
        ok += 1;
        okIds.add(item.id);
        if (item.section === "purchase_order_shot" && !ctx.poId) {
          ctx.poId = Number(detail.target_id || 0);
        }
        row.className = "fm-result-item ok";
      } else {
        failed += 1;
        row.className = "fm-result-item err";
      }
      row.innerHTML = `${good ? "✅" : "❌"} ${FM.esc(detail.file_name || item.file.name)}<br>${FM.esc(detail.message || "")}`;
      setProgress(i + 1, total, `已完成 ${i + 1}/${total}`);
    }

    UP.staged = UP.staged.filter(item => {
      if (!okIds.has(item.id)) return true;
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      return false;
    });
    UP.submitting = false;
    btn.textContent = "🚀 统一提交并处理";
    $("#fmProgressText").textContent = failed ? "处理结束，存在失败项" : "全部处理完成";
    $("#fmResultSummary").textContent =
      `成功 ${ok} 个，失败 ${failed} 个` + (failed ? "；失败项已保留在暂存清单，可修正后重试" : "");
    renderStage();
    if (ok) {
      FM.toast(`已成功处理 ${ok} 个素材`);
      try {
        await loadOrderData();
      } catch (e) {
        FM.toast("订单数据刷新失败：" + e.message, "error");
      }
    } else {
      FM.toast("没有素材处理成功", "error");
    }
  }

  async function loadOrderData() {
    if (!orderId) return;
    const res = await FM.api("/api/fulfillment/orders/" + orderId);
    UP.data = res.data;
    const o = res.data.order;
    $("#fmUploadOrder").textContent = `订单 ${o.order_sn}`;
    $("#fmUploadOrderMeta").innerHTML = [
      o.shop_name || "—",
      o.order_status_text || o.order_status || "—",
      `${res.data.packages.length} 个包裹`,
      `${res.data.purchase_orders.length} 张采购单`,
      o.gmt_order || "",
    ].map(t => `<span>${FM.esc(t)}</span>`).join("");
    $("#fmBackToOrder").href = "/fulfillment?order_id=" + orderId;
    $("#fmBackAfter").onclick = () => { location.href = "/fulfillment?order_id=" + orderId; };
    poOptions();
    packageOptions($("#fmDeliveryPkg"));
    packageOptions($("#fmReceiptPkg"));
    packageOptions($("#fmInvPkg"));
    renderStage();
  }

  function bindDropZones() {
    document.querySelectorAll("[data-drop]").forEach(drop => {
      const section = drop.dataset.drop;
      const input = drop.querySelector("[data-input]");
      drop.addEventListener("click", () => {
        if (drop.classList.contains("disabled") || input.disabled) {
          FM.toast("当前不可上传" + (SECTION_META[section] ? SECTION_META[section].label : "该素材"), "error");
          return;
        }
        input.click();
      });
      input.addEventListener("change", () => {
        addFiles(section, input.files);
        input.value = "";
      });
      ["dragenter", "dragover"].forEach(evt => drop.addEventListener(evt, e => {
        e.preventDefault();
        if (!drop.classList.contains("disabled")) drop.classList.add("dragging");
      }));
      ["dragleave", "drop"].forEach(evt => drop.addEventListener(evt, e => {
        e.preventDefault();
        drop.classList.remove("dragging");
      }));
      drop.addEventListener("drop", e => {
        e.preventDefault();
        if (drop.classList.contains("disabled")) return;
        if (e.dataTransfer && e.dataTransfer.files) addFiles(section, e.dataTransfer.files);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    if (!orderId) {
      $("#fmUploadOrder").textContent = "缺少订单参数";
      $("#fmUploadOrderMeta").innerHTML = '<span style="color:#b91c1c;">请从履约工作台选择订单后进入</span>';
      $("#fmSubmitAll").disabled = true;
      document.querySelectorAll("[data-input]").forEach(i => { i.disabled = true; });
      return;
    }
    if (!window.FM_CAN_EDIT) {
      $("#fmSubmitAll").disabled = true;
      $("#fmSubmitAll").textContent = "无素材上传权限";
      document.querySelectorAll("[data-input]").forEach(i => { i.disabled = true; });
    }
    bindDropZones();
    $("#fmSubmitAll").addEventListener("click", submitAll);
    $("#fmClearAll").addEventListener("click", clearAll);
    document.querySelectorAll("#fmVoucherPo, #fmInvPo, #fmDeliveryPkg, #fmReceiptPkg, #fmInvPkg")
      .forEach(sel => sel.addEventListener("change", renderStage));
    document.querySelectorAll("[data-stage]").forEach(box => {
      box.addEventListener("click", e => {
        const btn = e.target.closest("[data-remove]");
        if (btn) removeItem(Number(btn.dataset.remove));
      });
    });
    try {
      await loadOrderData();
    } catch (err) {
      $("#fmUploadOrder").textContent = "加载订单失败";
      $("#fmUploadOrderMeta").innerHTML = `<span style="color:#b91c1c;">${FM.esc(err.message)}</span>`;
      document.querySelectorAll("[data-input]").forEach(i => { i.disabled = true; });
      refreshDependencies();
    }
  });
})();
