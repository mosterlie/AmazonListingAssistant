/**
 * 履约中心管理页: 采购单 / 包裹 / 发票 / 清关报税
 */
(function () {
  const FM = window.FM;
  const mode = window.FM_MODE;
  const canEdit = !!window.FM_CAN_EDIT;
  const canDelete = !!window.FM_CAN_DELETE;
  const M = { page: 1, keyword: "", data: null };
  const $ = sel => document.querySelector(sel);
  const fileAccept = ".jpg,.jpeg,.png,.webp,.pdf,.doc,.docx,.xls,.xlsx,.zip";

  function orderChips(orders) {
    if (!orders || !orders.length) return '<span class="fm-muted">未关联</span>';
    return orders.map(o => `<span class="fm-chip info">${FM.esc(o.order_sn)}</span>`).join(" ");
  }

  function docCountText(po, keys) {
    const counts = po.doc_counts || {};
    return keys.map(k => {
      const label = { purchase_order_shot: "采购单截图", transfer_voucher: "转账凭证", delivery_note: "发货单", receipt: "签收单", tax_cert: "证明" }[k] || k;
      return `${label} ${counts[k] || 0}`;
    }).join(" · ");
  }

  function actionsHtml(items) {
    return `<div class="fm-actions" style="margin-left:0;">${items.join("")}</div>`;
  }

  function renderPurchase(data) {
    if (!data.items.length) return '<div class="fm-doc-empty" style="padding:30px; text-align:center;">暂无采购单</div>';
    return `<div class="fm-table-scroll"><table class="fm-table"><thead><tr>
      <th>采购单 / 供应商</th><th>采购日期</th><th>金额</th><th>付款</th>
      <th>关联订单</th><th>资料</th><th>操作</th></tr></thead><tbody>
      ${data.items.map(po => `<tr>
        <td><b>${FM.esc(po.purchase_no || "未识别单号")}</b><br><span class="fm-muted">${FM.esc(po.supplier_name || "—")}</span></td>
        <td>${FM.esc(po.purchase_date || "—")}</td>
        <td class="fm-money">${FM.money(po.total_amount, po.currency)}<br><span class="fm-muted">已付 ${FM.money(po.paid_amount, po.currency)}</span></td>
        <td>${FM.esc(po.payment_status || "—")}<br>${FM.parseChip(po.parse_status)}</td>
        <td>${orderChips(po.orders)}</td>
        <td class="fm-muted">${docCountText(po, ["purchase_order_shot", "transfer_voucher"])}</td>
        <td>${actionsHtml([
          `<button class="fm-btn" data-act="po-docs" data-id="${po.id}">📎 资料</button>`,
          canEdit ? `<button class="fm-btn" data-act="po-edit" data-id="${po.id}">✏️</button>` : "",
          canEdit ? `<button class="fm-btn blue" data-act="po-shot" data-id="${po.id}">📷 采购单</button>` : "",
          canEdit ? `<button class="fm-btn blue" data-act="po-voucher" data-id="${po.id}">💳 转账</button>` : "",
          canEdit ? `<button class="fm-btn" data-act="po-link" data-id="${po.id}">🔗 关联订单</button>` : "",
          canDelete ? `<button class="fm-btn danger" data-act="po-delete" data-id="${po.id}">🗑</button>` : "",
        ])}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  function renderPackages(data) {
    if (!data.items.length) return '<div class="fm-doc-empty" style="padding:30px; text-align:center;">暂无包裹，请先到履约工作台同步妙手订单</div>';
    return `<table class="fm-table"><thead><tr>
      <th>包裹</th><th>运单号</th><th>状态</th><th>关联订单</th><th>资料</th><th>发票</th><th>操作</th></tr></thead><tbody>
      ${data.items.map(p => `<tr>
        <td><b>${FM.esc(p.app_package_no || p.source_package_id)}</b><br><span class="fm-muted">${FM.esc(p.gmt_delivery || "—")}</span></td>
        <td class="fm-monospace">${FM.esc(p.tracking_no || "—")}<br><span class="fm-muted">${FM.esc(p.tracking_company || "")}</span></td>
        <td>${FM.statusChip(p.package_status, p.package_status_text)}<br><span class="fm-muted">${FM.esc(p.track_status_name || "")}</span></td>
        <td>${orderChips(p.orders)}</td>
        <td class="fm-muted">${docCountText(p, ["delivery_note", "receipt"])}</td>
        <td><span class="fm-chip">${p.invoice_count || 0}</span></td>
        <td>${actionsHtml([
          `<button class="fm-btn" data-act="pkg-docs" data-id="${p.id}">📎 资料</button>`,
          canEdit ? `<button class="fm-btn blue" data-act="pkg-doc" data-id="${p.id}" data-cat="delivery_note">📄 发货单</button>` : "",
          canEdit ? `<button class="fm-btn blue" data-act="pkg-doc" data-id="${p.id}" data-cat="receipt">✍️ 签收单</button>` : "",
          canEdit ? `<button class="fm-btn" data-act="pkg-invoice" data-id="${p.id}">🧾 发票</button>` : "",
          canEdit ? `<button class="fm-btn" data-act="pkg-link" data-id="${p.id}">🔗 关联订单</button>` : "",
        ])}</td>
      </tr>`).join("")}</tbody></table>`;
  }

  function renderInvoices(data) {
    if (!data.items.length) return '<div class="fm-doc-empty" style="padding:30px; text-align:center;">暂无发票</div>';
    return `<div class="fm-table-scroll"><table class="fm-table"><thead><tr>
      <th>类型</th><th>发票号</th><th>开票日期</th><th>开票公司</th><th>购买方公司</th><th>金额</th>
      <th>解析</th><th>关联对象</th><th>文件</th><th>操作</th></tr></thead><tbody>
      ${data.items.map(inv => `<tr>
        <td><b>${FM.esc(inv.invoice_kind || "发票")}</b></td>
        <td class="fm-monospace">${FM.esc(inv.invoice_number || "—")}</td>
        <td>${FM.esc(inv.invoice_date || "—")}</td>
        <td>${FM.esc(inv.seller_name || "—")}</td>
        <td>${FM.esc(inv.buyer_name || "—")}</td>
        <td class="fm-money">${FM.money(inv.total_amount, inv.currency)}</td>
        <td>${FM.parseChip(inv.parse_status)}<br>${inv.verified ? '<span class="fm-chip ok">已确认</span>' : '<span class="fm-chip warn">待确认</span>'}</td>
        <td>${(inv.links || []).map(l => `<span class="fm-chip info">${FM.esc(l.owner_label || l.owner_type)}</span>`).join(" ") || '<span class="fm-muted">未关联</span>'}</td>
        <td><span class="fm-chip">${(inv.documents || []).length}</span></td>
        <td>${actionsHtml([
          `<button class="fm-btn" data-act="inv-view" data-id="${inv.id}">🔍 核对</button>`,
          canEdit ? `<button class="fm-btn" data-act="inv-edit" data-id="${inv.id}">✏️</button>` : "",
          canEdit && window.FM_CAN_PARSE ? `<button class="fm-btn" data-act="inv-reparse" data-id="${inv.id}">🔄</button>` : "",
          canEdit ? `<button class="fm-btn" data-act="inv-link" data-id="${inv.id}">🔗 关联</button>` : "",
          canEdit ? `<button class="fm-btn" data-act="inv-unlink" data-id="${inv.id}">✖ 解除</button>` : "",
          canDelete ? `<button class="fm-btn danger" data-act="inv-delete" data-id="${inv.id}">🗑</button>` : "",
        ])}</td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  function renderTax(data) {
    if (!data.items.length) return '<div class="fm-doc-empty" style="padding:30px; text-align:center;">暂无清关报税</div>';
    return `<table class="fm-table"><thead><tr>
      <th>证明</th><th>类型 / 期间</th><th>金额</th><th>关联订单 / 运单</th><th>文件</th><th>操作</th></tr></thead><tbody>
      ${data.items.map(tc => `<tr>
        <td><b>${FM.esc(tc.title || "清关报税")}</b><br><span class="fm-muted">${FM.esc(tc.cert_no || "")}</span></td>
        <td>${FM.esc(tc.cert_type || "—")}<br><span class="fm-muted">${FM.esc(tc.tax_period || "")}</span></td>
        <td class="fm-money">${FM.money(tc.amount, tc.currency)}</td>
        <td>${tc.order_sn ? `<span class="fm-chip info">${FM.esc(tc.order_sn)}</span>` : '<span class="fm-muted">独立</span>'}
          ${tc.tracking_nos ? `<br><span class="fm-muted" style="font-size:0.7rem;">${FM.esc(tc.tracking_nos)}</span>` : ""}</td>
        <td><span class="fm-chip">${(tc.documents || []).length}</span></td>
        <td>${actionsHtml([
          `<button class="fm-btn" data-act="tax-docs" data-id="${tc.id}">📎 文件</button>`,
          canEdit ? `<button class="fm-btn blue" data-act="tax-upload" data-id="${tc.id}">⬆️ 上传</button>` : "",
          canEdit ? `<button class="fm-btn" data-act="tax-edit" data-id="${tc.id}">✏️</button>` : "",
          canDelete ? `<button class="fm-btn danger" data-act="tax-delete" data-id="${tc.id}">🗑</button>` : "",
        ])}</td>
      </tr>`).join("")}</tbody></table>`;
  }

  async function load() {
    try {
      const q = encodeURIComponent(M.keyword);
      let url = "";
      if (mode === "purchase") url = `/api/fulfillment/purchase-orders?keyword=${q}&page=${M.page}&page_size=20`;
      if (mode === "packages") url = `/api/fulfillment/packages?keyword=${q}&page=${M.page}&page_size=20`;
      if (mode === "invoices") url = `/api/fulfillment/invoices?keyword=${q}&page=${M.page}&page_size=20`;
      if (mode === "tax") url = `/api/fulfillment/tax-certs?keyword=${q}&page=${M.page}&page_size=20`;
      const res = await FM.api(url);
      M.data = res.data;
      const body = $("#fmManageBody");
      if (mode === "purchase") body.innerHTML = renderPurchase(res.data);
      if (mode === "packages") body.innerHTML = renderPackages(res.data);
      if (mode === "invoices") body.innerHTML = renderInvoices(res.data);
      if (mode === "tax") body.innerHTML = renderTax(res.data);
      $("#fmManagePager").innerHTML = "";
      $("#fmManagePager").appendChild(FM.pager(res.data, p => { M.page = p; load(); }));
      FM.bindDocs(body, load);
    } catch (err) {
      $("#fmManageBody").innerHTML = `<div class="fm-empty" style="border:none; color:#b91c1c;">${FM.esc(err.message)}</div>`;
    }
  }

  // ── 采购单 ──
  function purchaseFields(po) {
    po = po || {};
    return [
      { key: "purchase_no", label: "采购单号", value: po.purchase_no || "" },
      { key: "supplier_name", label: "供应商", value: po.supplier_name || "" },
      { key: "purchase_date", label: "采购日期", type: "date", value: po.purchase_date || "" },
      { key: "currency", label: "币种", value: po.currency || "CNY" },
      { key: "total_amount", label: "采购金额", type: "number", step: "0.01", value: po.total_amount || 0 },
      { key: "status", label: "采购状态", value: po.status || "待付款" },
      { key: "payment_status", label: "付款状态", type: "select", value: po.payment_status || "未付款",
        options: ["未付款", "部分付款", "已付款"].map(v => ({ value: v, label: v })) },
      { key: "note", label: "说明", type: "textarea", value: po.note || "" },
    ];
  }

  function createPurchase() {
    FM.modal({
      title: "新建采购单", fields: purchaseFields(), submitText: "创建",
      onSubmit: async values => {
        await FM.api("/api/fulfillment/purchase-orders", { method: "POST", body: values });
        FM.toast("采购单已创建");
        await load();
      },
    });
  }

  function editPurchase(id) {
    const po = (M.data.items || []).find(x => x.id === id);
    if (!po) return;
    FM.modal({
      title: "编辑采购单", fields: purchaseFields(po), submitText: "保存",
      onSubmit: async values => {
        await FM.api("/api/fulfillment/purchase-orders/" + id, { method: "PUT", body: values });
        FM.toast("采购单已更新");
        await load();
      },
    });
  }

  async function uploadPurchaseDoc(id, category) {
    const file = await FM.pickFile(fileAccept);
    if (!file) return;
    const fd = new FormData();
    fd.append("category", category);
    fd.append("file", file);
    fd.append("auto_parse", "true");
    try {
      const res = await FM.api(`/api/fulfillment/purchase-orders/${id}/documents`, { method: "POST", body: fd });
      FM.toast(res.msg || "已上传");
      await load();
    } catch (err) { FM.toast(err.message, "error"); }
  }

  function linkOrders(id, endpoint) {
    const url = endpoint || `/api/fulfillment/purchase-orders/${id}/link-orders`;
    FM.modal({
      title: "关联亚马逊订单",
      hint: "每行一个亚马逊订单号；系统会精确匹配已同步到履约中心的订单。",
      fields: [{ key: "order_sns", label: "订单号（可多行）", type: "textarea", required: true }],
      submitText: "关联",
      onSubmit: async values => {
        const sns = String(values.order_sns || "").split(/[\s,，]+/).filter(Boolean);
        const ids = [];
        const missing = [];
        for (const sn of sns) {
          const res = await FM.api("/api/fulfillment/orders?page_size=20&keyword=" + encodeURIComponent(sn));
          const hit = (res.data.items || []).find(o => o.order_sn === sn);
          if (hit) ids.push(hit.id); else missing.push(sn);
        }
        if (!ids.length) throw new Error("未找到对应订单，请先在工作台同步妙手订单");
        await FM.api(url, { method: "POST", body: { order_ids: ids } });
        FM.toast(missing.length ? `已关联 ${ids.length} 个订单，未找到: ${missing.join("、")}` : "关联已更新");
        await load();
      },
    });
  }

  async function showDocs(ownerType, ownerId, title) {
    try {
      const res = await FM.api(`/api/fulfillment/documents?owner_type=${ownerType}&owner_id=${ownerId}`);
      let html = (res.data || []).length
        ? `<div class="fm-doc-grid">${res.data.map(d => FM.docCard(d, canDelete)).join("")}</div>`
        : '<div class="fm-doc-empty">暂无资料</div>';
      // 采购单: 把该采购单对应的发票连原件一起展示在素材里
      if (ownerType === "purchase_order") {
        try {
          const po = await FM.api(`/api/fulfillment/purchase-orders/${ownerId}`);
          const invs = (po.data && po.data.invoices) || [];
          if (invs.length) {
            html += `<div style="margin-top:14px;">
              <div style="font-size:0.82rem; font-weight:700; color:#475569; margin-bottom:6px;">
                对应发票 ${invs.length} 张</div>
              ${invs.map(inv => `
                <div style="border:1px solid #eef2f7; border-radius:8px; padding:8px 10px; margin-bottom:8px;">
                  <div style="font-size:0.8rem; font-weight:700; color:#334155;">
                    ${FM.esc(inv.invoice_kind || "发票")} · ${FM.esc(inv.invoice_number || "无号码")}
                    <span class="fm-money" style="margin-left:8px;">${FM.money(inv.total_amount, inv.currency)}</span>
                  </div>
                  <div class="fm-muted" style="margin-top:2px;">
                    ${FM.esc(inv.seller_name || "—")} · ${FM.esc(inv.invoice_date || "无日期")}
                  </div>
                  <div class="fm-doc-grid" style="margin-top:6px;">
                    ${(inv.documents || []).map(d => FM.docCard(d, false)).join("") || '<span class="fm-muted">无原件</span>'}
                  </div>
                </div>`).join("")}
            </div>`;
          }
        } catch (e) { /* 发票信息获取失败不影响资料展示 */ }
      }
      FM.infoModal(title, html);
    } catch (err) { FM.toast(err.message, "error"); }
  }

  // ── 包裹 ──
  async function uploadPackageDoc(id, category) {
    const file = await FM.pickFile(fileAccept);
    if (!file) return;
    const fd = new FormData();
    fd.append("owner_type", "package");
    fd.append("owner_id", id);
    fd.append("category", category);
    fd.append("files", file);
    try {
      await FM.api("/api/fulfillment/documents", { method: "POST", body: fd });
      FM.toast("已上传");
      await load();
    } catch (err) { FM.toast(err.message, "error"); }
  }

  function invoiceFields(inv) {
    inv = inv || {};
    return [
      { key: "invoice_kind", label: "发票类型", value: inv.invoice_kind || "其他发票" },
      { key: "invoice_code", label: "发票代码", value: inv.invoice_code || "" },
      { key: "invoice_number", label: "发票号码", value: inv.invoice_number || "" },
      { key: "invoice_date", label: "开票日期", value: inv.invoice_date || "" },
      { key: "seller_name", label: "销售方", value: inv.seller_name || "" },
      { key: "seller_tax_id", label: "销售方税号", value: inv.seller_tax_id || "" },
      { key: "buyer_name", label: "购买方", value: inv.buyer_name || "" },
      { key: "buyer_tax_id", label: "购买方税号", value: inv.buyer_tax_id || "" },
      { key: "currency", label: "币种", value: inv.currency || "CNY" },
      { key: "amount_excl_tax", label: "不含税金额", type: "number", step: "0.01", value: inv.amount_excl_tax || 0 },
      { key: "tax_amount", label: "税额", type: "number", step: "0.01", value: inv.tax_amount || 0 },
      { key: "total_amount", label: "价税合计", type: "number", step: "0.01", value: inv.total_amount || 0 },
      { key: "remark", label: "备注", type: "textarea", value: inv.remark || "" },
      { key: "verified", label: "确认状态", type: "select", value: inv.verified ? "1" : "0",
        options: [{ value: "0", label: "待确认" }, { value: "1", label: "已确认" }] },
    ];
  }

  function uploadInvoiceStandalone(ownerType, ownerId) {
    const fields = [
      { key: "invoice_kind", label: "发票类型", type: "select", value: "其他发票",
        options: ["采购发票", "物流发票", "其他发票"].map(v => ({ value: v, label: v })) },
      { key: "file", label: "发票文件", type: "file", required: true, accept: ".jpg,.jpeg,.png,.webp,.pdf" },
    ];
    FM.modal({
      title: ownerType ? "上传包裹发票" : "上传发票（不关联）",
      hint: "保存后自动解析；解析失败文件与记录仍保留。",
      fields, submitText: "上传并解析",
      onSubmit: async values => {
        if (!values.file) throw new Error("请选择发票文件");
        const fd = new FormData();
        fd.append("file", values.file);
        fd.append("invoice_kind", values.invoice_kind);
        fd.append("auto_parse", "true");
        if (ownerType) {
          fd.append("owner_type", ownerType);
          fd.append("owner_id", ownerId);
        }
        const res = await FM.api("/api/fulfillment/invoices", { method: "POST", body: fd });
        FM.toast(res.msg || "发票已上传");
        await load();
      },
    });
  }

  function editInvoice(id) {
    const inv = (M.data.items || []).find(x => x.id === id);
    if (!inv) return;
    FM.modal({
      title: "修正发票信息", fields: invoiceFields(inv), submitText: "保存",
      onSubmit: async values => {
        values.verified = values.verified === "1";
        await FM.api("/api/fulfillment/invoices/" + id, { method: "PUT", body: values });
        FM.toast("发票已更新");
        await load();
      },
    });
  }

  /* 发票核对: 左侧信息对照, 右侧发票大图 */
  function viewInvoice(id) {
    const inv = (M.data.items || []).find(x => x.id === id);
    if (!inv) return;
    const items = (inv.items || []).length ? `<table class="fm-invoice-items"><thead><tr>
      <th>名称</th><th>规格</th><th style="text-align:right;">数量</th>
      <th style="text-align:right;">单价</th><th style="text-align:right;">金额</th><th>税率</th></tr></thead>
      <tbody>${inv.items.map(it => `<tr><td>${FM.esc(it.name)}</td><td>${FM.esc(it.spec)}</td>
      <td class="num">${Number(it.quantity || 0).toLocaleString("zh-CN")}</td>
      <td class="num">${Number(it.unit_price || 0).toFixed(2)}</td>
      <td class="num">${FM.money(it.amount)}</td><td>${FM.esc(it.tax_rate)}</td></tr>`).join("")}
      </tbody></table>` : '<div class="fm-doc-empty">无发票明细</div>';

    const kv = `
      <div class="fm-kv">
        <div><span>发票类型</span><span>${FM.esc(inv.invoice_kind || "—")}</span></div>
        <div><span>发票号码</span><span>${FM.esc(inv.invoice_number || "—")}</span></div>
        <div><span>发票日期</span><span>${FM.esc(inv.invoice_date || "—")}</span></div>
        <div><span>销售方</span><span>${FM.esc(inv.seller_name || "—")}</span></div>
        <div><span>购买方</span><span>${FM.esc(inv.buyer_name || "—")}</span></div>
        <div><span>价税合计</span><span class="fm-money">${FM.money(inv.total_amount, inv.currency)}</span></div>
        <div><span>税额</span><span>${FM.money(inv.tax_amount, inv.currency)}</span></div>
        <div><span>解析状态</span><span>${FM.esc(inv.parse_status || "—")}</span></div>
      </div>`;

    const doc = (inv.documents || [])[0] || null;
    const rawUrl = doc ? (doc.relative_url || doc.preview_url || doc.thumb_url || "") : "";
    const src = rawUrl ? encodeURI(rawUrl) : "";
    const isPdf = /\.pdf$/i.test(doc ? (doc.stored_name || doc.file_name || "") : "");
    const right = !src
      ? '<div class="fm-doc-empty">无发票文件</div>'
      : isPdf
        ? `<iframe class="inv-big-pdf" src="${FM.esc(src)}#toolbar=1&view=FitH"></iframe>`
        : `<img class="inv-big" src="${FM.esc(src)}" alt="发票大图"
             title="点击查看原图" onclick="window.open('${FM.esc(src)}','_blank','noopener')">`;

    FM.infoModal("发票核对", `
      <div class="inv-check">
        <div class="inv-check-left">
          ${kv}
          <div style="margin-top:8px;">${items}</div>
          ${(inv.documents || []).length > 1
        ? `<div style="margin-top:8px;" class="fm-doc-grid">${inv.documents.slice(1).map(d => FM.docCard(d, false)).join("")}</div>` : ""}
        </div>
        <div class="inv-check-right">${right}</div>
      </div>`, "1180px");
  }

  function linkInvoice(id) {
    FM.modal({
      title: "发票追加关联",
      fields: [
        { key: "owner_type", label: "关联类型", type: "select", value: "order",
          options: [{ value: "order", label: "订单" }, { value: "package", label: "包裹" }, { value: "purchase_order", label: "采购单" }] },
        { key: "owner_id", label: "对象 ID", type: "number", required: true, placeholder: "如 12（可在工作台链接中查看）" },
        { key: "allocated_amount", label: "分摊金额（可选）", type: "number", step: "0.01", value: 0 },
      ],
      submitText: "添加关联",
      onSubmit: async values => {
        await FM.api(`/api/fulfillment/invoices/${id}/links`, { method: "POST", body: values });
        FM.toast("关联已添加");
        await load();
      },
    });
  }

  function unlinkInvoice(id) {
    const inv = (M.data.items || []).find(x => x.id === id);
    if (!inv || !(inv.links || []).length) {
      FM.toast("该发票没有关联对象", "error");
      return;
    }
    FM.modal({
      title: "解除发票关联",
      fields: [{ key: "link", label: "选择关联", type: "select", value: inv.links[0].owner_type + ":" + inv.links[0].owner_id,
        options: inv.links.map(l => ({
          value: l.owner_type + ":" + l.owner_id,
          label: l.owner_label || (l.owner_type + " #" + l.owner_id),
        })) }],
      submitText: "解除",
      onSubmit: async values => {
        const [ownerType, ownerId] = String(values.link).split(":");
        await FM.api(`/api/fulfillment/invoices/${id}/links?owner_type=${ownerType}&owner_id=${ownerId}`,
          { method: "DELETE" });
        FM.toast("关联已解除");
        await load();
      },
    });
  }

  // ── 清关报税 ──
  function taxFields(tc) {
    tc = tc || {};
    return [
      { key: "title", label: "证明名称", value: tc.title || "清关报税", required: true },
      { key: "cert_type", label: "证明类型", value: tc.cert_type || "" },
      { key: "cert_no", label: "证明编号", value: tc.cert_no || "" },
      { key: "tax_period", label: "税务期间", value: tc.tax_period || "" },
      { key: "country", label: "国家/地区", value: tc.country || "" },
      { key: "amount", label: "金额", type: "number", step: "0.01", value: tc.amount || 0 },
      { key: "currency", label: "币种", value: tc.currency || "CNY" },
      { key: "issued_date", label: "开具日期", type: "date", value: tc.issued_date || "" },
      { key: "note", label: "说明", type: "textarea", value: tc.note || "" },
    ];
  }

  function createTax() {
    const fields = taxFields();
    fields.push({ key: "file", label: "证明文件（可选）", type: "file", accept: fileAccept });
    FM.modal({
      title: "新增清关报税", fields, submitText: "创建",
      onSubmit: async values => {
        const file = values.file;
        delete values.file;
        const res = await FM.api("/api/fulfillment/tax-certs", { method: "POST", body: values });
        if (file) {
          const fd = new FormData();
          fd.append("file", file);
          await FM.api(`/api/fulfillment/tax-certs/${res.data.id}/documents`, { method: "POST", body: fd });
        }
        FM.toast("清关报税已创建");
        await load();
      },
    });
  }

  function editTax(id) {
    const tc = (M.data.items || []).find(x => x.id === id);
    if (!tc) return;
    FM.modal({
      title: "编辑清关报税", fields: taxFields(tc), submitText: "保存",
      onSubmit: async values => {
        values.order_id = tc.order_id || 0;
        await FM.api("/api/fulfillment/tax-certs/" + id, { method: "PUT", body: values });
        FM.toast("清关报税已更新");
        await load();
      },
    });
  }

  async function uploadTaxFile(id) {
    const file = await FM.pickFile(fileAccept);
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      await FM.api(`/api/fulfillment/tax-certs/${id}/documents`, { method: "POST", body: fd });
      FM.toast("文件已上传");
      await load();
    } catch (err) { FM.toast(err.message, "error"); }
  }

  async function handleAction(act, el) {
    const id = Number(el.dataset.id || 0);
    if (act === "po-edit") return editPurchase(id);
    if (act === "po-shot") return uploadPurchaseDoc(id, "purchase_order_shot");
    if (act === "po-voucher") return uploadPurchaseDoc(id, "transfer_voucher");
    if (act === "po-link") return linkOrders(id);
    if (act === "po-docs") return showDocs("purchase_order", id, "采购单资料");
    if (act === "po-delete") {
      if (!confirm("确定删除该采购单？仅当没有关联发票时可删除。")) return;
      try {
        await FM.api("/api/fulfillment/purchase-orders/" + id, { method: "DELETE" });
        FM.toast("采购单已删除");
        await load();
      } catch (err) { FM.toast(err.message, "error"); }
      return;
    }
    if (act === "pkg-docs") return showDocs("package", id, "包裹资料");
    if (act === "pkg-doc") return uploadPackageDoc(id, el.dataset.cat);
    if (act === "pkg-invoice") return uploadInvoiceStandalone("package", id);
    if (act === "pkg-link") return linkOrders(id, `/api/fulfillment/packages/${id}/link-orders`);
    if (act === "inv-view") return viewInvoice(id);
    if (act === "inv-edit") return editInvoice(id);
    if (act === "inv-reparse") {
      try {
        await FM.api(`/api/fulfillment/invoices/${id}/reparse`, { method: "POST" });
        FM.toast("已重新解析");
        await load();
      } catch (err) { FM.toast(err.message, "error"); }
      return;
    }
    if (act === "inv-link") return linkInvoice(id);
    if (act === "inv-unlink") return unlinkInvoice(id);
    if (act === "inv-delete") {
      if (!confirm("确定删除该发票及其文件？")) return;
      try {
        await FM.api("/api/fulfillment/invoices/" + id, { method: "DELETE" });
        FM.toast("发票已删除");
        await load();
      } catch (err) { FM.toast(err.message, "error"); }
      return;
    }
    if (act === "tax-edit") return editTax(id);
    if (act === "tax-upload") return uploadTaxFile(id);
    if (act === "tax-docs") return showDocs("tax_cert", id, "清关报税文件");
    if (act === "tax-delete") {
      if (!confirm("确定删除该清关报税及其文件？")) return;
      try {
        await FM.api("/api/fulfillment/tax-certs/" + id, { method: "DELETE" });
        FM.toast("清关报税已删除");
        await load();
      } catch (err) { FM.toast(err.message, "error"); }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const createBtn = $("#fmManageCreate");
    if (canEdit) {
      if (mode === "purchase") {
        createBtn.style.display = "";
        createBtn.textContent = "➕ 新建采购单";
        createBtn.addEventListener("click", createPurchase);
      } else if (mode === "invoices") {
        createBtn.style.display = "";
        createBtn.textContent = "⬆️ 上传发票";
        createBtn.addEventListener("click", () => uploadInvoiceStandalone("", 0));
      } else if (mode === "tax") {
        createBtn.style.display = "";
        createBtn.textContent = "➕ 新增清关报税";
        createBtn.addEventListener("click", createTax);
      } else if (mode === "packages") {
        createBtn.style.display = "";
        createBtn.textContent = "🗂️ 去工作台同步";
        createBtn.addEventListener("click", () => { location.href = "/fulfillment"; });
      }
    }
    $("#fmManageRefresh").addEventListener("click", load);
    let timer = null;
    $("#fmManageSearch").addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(() => { M.keyword = this.value.trim(); M.page = 1; load(); }, 300);
    });
    $("#fmManageBody").addEventListener("click", e => {
      const btn = e.target.closest("[data-act]");
      if (!btn) return;
      e.preventDefault();
      handleAction(btn.dataset.act, btn);
    });
    load();
  });
})();
