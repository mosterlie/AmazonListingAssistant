/**
 * 任务管理与成果登记前端交互逻辑 (tasks.js)
 */

const taskState = {
  tasks: [],
  users: [],
  products: [],
  currentStatusFilter: "all",
  searchKeyword: ""
};

document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([
    loadUserOptions(),
    loadProductOptions(),
    loadTasksList()
  ]);
});

/**
 * 加载系统用户列表（供管理员派发指派）
 */
async function loadUserOptions() {
  if (window.currentUserRole !== "admin") return;
  try {
    const res = await fetch("/api/users");
    const json = await res.json();
    if (json.code === 0 && Array.isArray(json.data)) {
      taskState.users = json.data;

      // 填充派发下拉框
      const dispatchSelect = document.getElementById("dispatchAssigneeSelect");
      const editSelect = document.getElementById("editAssigneeSelect");
      const filterSelect = document.getElementById("taskAssigneeFilter");

      const userOptions = json.data.map(u => `
        <option value="${u.username}">
          ${u.display_name ? u.display_name : u.username} (${u.username} - ${u.role === "admin" ? "管理员" : "成员"})
        </option>
      `).join("");

      if (dispatchSelect) {
        dispatchSelect.innerHTML = `<option value="">-- 请选择执行人 --</option>` + userOptions;
      }
      if (editSelect) {
        editSelect.innerHTML = `<option value="">-- 请选择执行人 --</option>` + userOptions;
      }
      if (filterSelect) {
        filterSelect.innerHTML = `<option value="">👤 全部执行人</option>` + json.data.map(u => `
          <option value="${u.username}">${u.display_name ? u.display_name : u.username}</option>
        `).join("");
      }
    }
  } catch (err) {
    console.error("加载用户列表失败:", err);
  }
}

/**
 * 加载系统中已录入的商品列表（供成果关联选择，仅含未被其它任务关联的商品）
 * @param {number|null} taskId 当前任务 ID（放行该任务已关联的商品，便于重新登记）
 */
async function loadProductOptions(taskId = null) {
  try {
    let url = "/api/tasks/products/options";
    if (taskId) url += `?task_id=${taskId}`;
    const res = await fetch(url);
    const json = await res.json();
    if (json.code === 0 && Array.isArray(json.data)) {
      taskState.products = json.data;
      renderProductOptions(json.data);
    }
  } catch (err) {
    console.error("加载商品选项列表失败:", err);
  }
}

/**
 * 渲染商品下拉选项
 */
function renderProductOptions(products) {
  const prodSelect = document.getElementById("deliverableProductSelect");
  if (!prodSelect) return;
  const prevVal = prodSelect.value;

  let opts = `<option value="">-- 请选择关联的已录入商品 (必选) --</option>`;
  opts += products.map(p => {
    const skuTxt = p.parent_sku ? `[${p.parent_sku}]` : "";
    const storeTxt = p.store_account ? `(${p.store_account})` : "";
    const titleTxt = p.title ? p.title.slice(0, 45) : "未命名商品";
    return `<option value="${p.id}" data-sku="${p.parent_sku || ''}" data-title="${p.title || ''}" data-image="${p.main_image || ''}" data-store="${p.store_account || ''}">
      #${p.id} ${skuTxt} ${titleTxt} ${storeTxt}
    </option>`;
  }).join("");
  prodSelect.innerHTML = opts;

  // 恢复之前选中的项（若仍存在于筛选结果中）
  if (prevVal && products.some(p => String(p.id) === prevVal)) {
    prodSelect.value = prevVal;
  }
}

/**
 * 按 SKU / 标题关键词筛选商品下拉选项（服务端检索 + 本地兜底过滤）
 */
function filterProductOptionsBySku(keyword) {
  const all = taskState.products || [];
  const kw = (keyword || "").trim().toLowerCase();
  if (!kw) {
    renderProductOptions(all);
    return;
  }
  const filtered = all.filter(p =>
    String(p.id).includes(kw) ||
    (p.parent_sku || "").toLowerCase().includes(kw) ||
    (p.title || "").toLowerCase().includes(kw)
  );
  renderProductOptions(filtered);
}

/**
 * 刷新与渲染任务列表
 */
async function loadTasksList() {
  const tbody = document.getElementById("taskTableBody");
  if (!tbody) return;

  const searchInp = document.getElementById("taskSearchInput");
  const keyword = searchInp ? searchInp.value.trim() : "";
  const assigneeSelect = document.getElementById("taskAssigneeFilter");
  const assignee = assigneeSelect ? assigneeSelect.value.trim() : "";

  let url = `/api/tasks?status=${encodeURIComponent(taskState.currentStatusFilter)}`;
  if (keyword) url += `&search=${encodeURIComponent(keyword)}`;
  if (assignee) url += `&assigned_to=${encodeURIComponent(assignee)}`;

  try {
    const res = await fetch(url);
    const json = await res.json();
    if (json.code === 0 && Array.isArray(json.data)) {
      taskState.tasks = json.data;
      updateStatPills(json.data);
      renderTaskTable(json.data);
    } else {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:30px; color:#ef4444;">加载失败: ${json.detail || json.msg}</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:30px; color:#ef4444;">网络请求异常: ${err.message}</td></tr>`;
  }
}

/**
 * 统计徽章更新
 */
function updateStatPills(tasks) {
  let pendingCount = 0;
  let completedCount = 0;

  tasks.forEach(t => {
    if (t.status === "completed") completedCount++;
    else pendingCount++;
  });

  const totalEl = document.getElementById("statCountAll");
  const pendingEl = document.getElementById("statCountPending");
  const completedEl = document.getElementById("statCountCompleted");

  if (totalEl) totalEl.innerText = tasks.length;
  if (pendingEl) pendingEl.innerText = pendingCount;
  if (completedEl) completedEl.innerText = completedCount;

  // 更新当前高亮样式
  ["all", "pending", "completed"].forEach(st => {
    const el = document.getElementById(`statPill${st.charAt(0).toUpperCase() + st.slice(1)}`);
    if (el) {
      if (taskState.currentStatusFilter === st) {
        el.style.borderColor = "var(--primary)";
        el.style.background = "#eef2ff";
      } else {
        el.style.borderColor = "#cbd5e1";
        el.style.background = "#fff";
      }
    }
  });
}

function filterByStatus(status) {
  taskState.currentStatusFilter = status;
  loadTasksList();
}

function handleSearchKeyup(event) {
  if (event.key === "Enter") {
    loadTasksList();
  }
}

/**
 * 渲染任务表格
 */
function renderTaskTable(tasks) {
  const tbody = document.getElementById("taskTableBody");
  if (!tbody) return;

  if (tasks.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align:center; padding:48px; color:var(--text-muted);">
          <div style="font-size:2rem; margin-bottom:8px;">📭</div>
          <div>暂无符合条件的任务记录</div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = tasks.map(t => {
    const isCompleted = (t.status === "completed");
    const statusBadge = isCompleted
      ? `<span class="tag-badge" style="background:#dcfce7; color:#15803d; border-color:#bbf7d0; font-weight:700; padding:3px 8px; font-size:0.8rem;">✅ 已完成</span>`
      : `<span class="tag-badge" style="background:#fef3c7; color:#b45309; border-color:#fde68a; font-weight:700; padding:3px 8px; font-size:0.8rem;">⏳ 待处理</span>`;

    // 关联商品卡片展示 (支持点击直接调起商品详情弹窗)
    let productCardHtml = `<span style="color:var(--text-muted); font-size:0.82rem;">未关联品</span>`;
    if (t.product_id && t.product_id > 0) {
      const imgUrl = t.product_main_image ? `/api/images/preview?path=${encodeURIComponent(t.product_main_image)}` : "";
      productCardHtml = `
        <div onclick="viewProductDetail(${t.product_id})" 
             title="点击查看此商品详情" 
             style="display:flex; align-items:center; gap:8px; background:#f0fdf4; border:1px solid #86efac; border-radius:6px; padding:6px 8px; max-width:260px; cursor:pointer; transition:all 0.2s;" 
             onmouseenter="this.style.background='#dcfce7'; this.style.borderColor='#22c55e'; this.style.transform='translateY(-1px)';" 
             onmouseleave="this.style.background='#f0fdf4'; this.style.borderColor='#86efac'; this.style.transform='none';">
          ${imgUrl ? `<img src="${imgUrl}" style="width:36px; height:36px; border-radius:4px; object-fit:cover; border:1px solid #86efac; flex-shrink:0;">` : `<span style="font-size:1.2rem;">📦</span>`}
          <div style="min-width:0; flex:1;">
            <div style="font-size:0.78rem; font-weight:700; color:#166534; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${t.product_title || ''}">
              ${t.product_title || '已关联商品'}
            </div>
            <div style="font-size:0.72rem; color:#15803d; font-family:monospace; margin-top:1px; display:flex; align-items:center; justify-content:space-between;">
              <span>SKU: ${t.product_parent_sku || `#${t.product_id}`}</span>
              <span style="font-size:0.68rem; color:#2563eb; background:#eff6ff; padding:1px 4px; border-radius:3px; font-weight:600;">详情 ↗</span>
            </div>
          </div>
        </div>
      `;
    }

    // 成果信息
    let deliverableHtml = `<span style="color:var(--text-muted); font-size:0.82rem;">尚未登记</span>`;
    if (t.result_url) {
      deliverableHtml = `
        <div style="font-size:0.82rem;">
          <div style="margin-bottom:3px;">
            <a href="${t.result_url}" target="_blank" style="color:#2563eb; text-decoration:none; font-weight:600; display:inline-flex; align-items:center; gap:3px;">
              <span>🔗 成品链接</span>
              <span style="font-size:0.7rem;">↗</span>
            </a>
          </div>
          ${t.submitted_at ? `<div style="font-size:0.72rem; color:var(--text-muted);">登记: ${t.submitted_at}</div>` : ''}
        </div>
      `;
    }

    // 派发信息 (标题 + 参考链接)
    const refUrlHtml = t.reference_url
      ? `<div style="margin-top:4px;"><a href="${t.reference_url}" target="_blank" style="color:#2563eb; text-decoration:none; font-weight:600; display:inline-flex; align-items:center; gap:3px; word-break:break-all;"><span>🔗 参考链接</span><span style="font-size:0.7rem;">↗</span></a></div>`
      : `<span style="color:var(--text-muted); font-size:0.75rem;">无参考链接</span>`;

    // 任务说明 (单独一列展示)
    const instructionsHtml = t.instructions
      ? `<div style="font-size:0.8rem; color:#334155; line-height:1.45; white-space:pre-wrap; word-break:break-word; max-width:280px;">${t.instructions}</div>`
      : `<span style="color:var(--text-muted); font-size:0.78rem;">(无特殊说明)</span>`;

    // 操作按钮 (登记/关联仅任务执行人或管理员可见)
    const isAdmin = (window.currentUserRole === "admin");
    const canSubmit = isAdmin || (window.currentUsername && window.currentUsername === t.assigned_to);
    const actionsHtml = `
      <div style="display:flex; flex-direction:column; gap:4px; align-items:center;">
        ${canSubmit ? `
        <button class="btn btn-outline btn-sm" onclick="openSubmitDeliverableModal(${t.id})" style="padding:3px 8px; font-size:0.75rem; width:100%; border-color:#3b82f6; color:#2563eb; background:#eff6ff;">
          📝 登记/关联
        </button>` : '<span style="font-size:0.7rem; color:#94a3b8;">仅执行人可登记</span>'}
        ${isAdmin ? `
          <div style="display:flex; gap:4px; width:100%;">
            <button class="btn btn-outline btn-sm" onclick="openEditTaskModal(${t.id})" style="padding:3px 8px; font-size:0.75rem; flex:1;">✏️ 编辑</button>
            <button class="btn btn-outline btn-sm" onclick="handleDeleteTask(${t.id})" style="padding:3px 8px; font-size:0.75rem; flex:1; color:#ef4444; border-color:#fca5a5;">🗑️ 删除</button>
          </div>
        ` : ''}
      </div>
    `;

    return `
      <tr id="task_row_${t.id}">
        <td style="font-weight:700; color:var(--primary); text-align:center;">#${t.id}</td>
        <td>
          <div style="font-weight:600; color:#1e293b; margin-bottom:2px;">${t.title || '无标题任务'}</div>
          ${refUrlHtml}
        </td>
        <td>
          ${instructionsHtml}
        </td>
        <td style="text-align:center;">
          <span class="tag-badge" style="font-size:0.8rem; background:#f1f5f9; color:#334155; border-color:#cbd5e1; padding:3px 6px;">
            👤 ${t.assigned_to_name || t.assigned_to}
          </span>
        </td>
        <td>
          <div style="font-size:0.8rem; font-weight:600; color:#334155;">${t.assigned_by}</div>
          <div style="font-size:0.72rem; color:var(--text-muted); margin-top:2px;">${t.assigned_at || t.created_at}</div>
        </td>
        <td style="text-align:center;">${statusBadge}</td>
        <td>${deliverableHtml}</td>
        <td>${productCardHtml}</td>
        <td>${actionsHtml}</td>
      </tr>
    `;
  }).join("");
}

// ============================================================================
// 模态弹窗 1: 管理员派发新任务
// ============================================================================
function openDispatchModal() {
  closeEditTaskModal();
  closeSubmitDeliverableModal();
  const modal = document.getElementById("dispatchTaskModal");
  if (modal) {
    document.getElementById("dispatchTaskForm").reset();
    modal.style.display = "flex";
  }
}

function closeDispatchModal() {
  const modal = document.getElementById("dispatchTaskModal");
  if (modal) modal.style.display = "none";
}

async function handleDispatchSubmit(e) {
  e.preventDefault();
  const assignee = document.getElementById("dispatchAssigneeSelect").value;
  const title = document.getElementById("dispatchTitleInput").value.trim();
  const refUrl = document.getElementById("dispatchRefUrlInput").value.trim();
  const instructions = document.getElementById("dispatchInstructionsInput").value.trim();

  if (!assignee) {
    alert("请选择执行人！");
    return;
  }
  if (!refUrl) {
    alert("请输入参考链接！");
    return;
  }

  const btn = document.getElementById("dispatchSubmitBtn");
  btn.disabled = true;
  btn.innerText = "正在派发...";

  try {
    const res = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        assigned_to: assignee,
        title: title,
        reference_url: refUrl,
        instructions: instructions
      })
    });
    const json = await res.json();
    if (json.code === 0) {
      closeDispatchModal();
      showToast("🎉 任务派发成功！");
      await loadTasksList();
    } else {
      alert(`派发失败: ${json.detail || json.msg}`);
    }
  } catch (err) {
    alert(`请求异常: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerText = "🚀 确认派发任务";
  }
}

// ============================================================================
// 模态弹窗 2: 登记成果与关联商品
// ============================================================================
function openSubmitDeliverableModal(taskId) {
  closeDispatchModal();
  closeEditTaskModal();
  closeProductDetailModal();
  const task = taskState.tasks.find(t => t.id === taskId);
  if (!task) return;

  document.getElementById("submitTargetTaskId").value = task.id;
  document.getElementById("submitTaskIdSpan").innerText = task.id;
  document.getElementById("submitRefUrlLink").href = task.reference_url || "#";
  document.getElementById("submitRefUrlLink").innerText = task.reference_url || "(无参考链接)";
  document.getElementById("submitInstructionsText").innerText = task.instructions || "(无特殊要求)";

  document.getElementById("deliverableResultUrlInput").value = task.result_url || "";

  // 重新加载商品选项 (仅未被其它任务关联的商品；本任务已关联的商品仍可选)，并清空 SKU 筛选
  const skuFilter = document.getElementById("deliverableProductSkuFilter");
  if (skuFilter) skuFilter.value = "";
  const prodSelect = document.getElementById("deliverableProductSelect");
  if (prodSelect) prodSelect.value = "";

  loadProductOptions(task.id).then(() => {
    if (prodSelect && task.product_id && task.product_id > 0) {
      prodSelect.value = String(task.product_id);
      handleProductSelectChange(prodSelect);
    }
  });

  const modal = document.getElementById("submitDeliverableModal");
  if (modal) modal.style.display = "flex";
}

function closeSubmitDeliverableModal() {
  const modal = document.getElementById("submitDeliverableModal");
  if (modal) modal.style.display = "none";
}

function handleProductSelectChange(selectEl) {
  const previewCard = document.getElementById("selectedProductPreviewCard");
  const val = selectEl.value;
  if (!val || val === "0") {
    if (previewCard) previewCard.style.display = "none";
    return;
  }

  const opt = selectEl.options[selectEl.selectedIndex];
  if (opt && previewCard) {
    const title = opt.dataset.title || "已选商品";
    const sku = opt.dataset.sku || "-";
    const store = opt.dataset.store || "-";
    const img = opt.dataset.image;

    document.getElementById("previewProductTitle").innerText = title;
    document.getElementById("previewProductSku").innerText = sku;
    document.getElementById("previewProductStore").innerText = store;

    const imgEl = document.getElementById("previewProductImg");
    if (img) {
      imgEl.src = `/api/images/preview?path=${encodeURIComponent(img)}`;
      imgEl.style.display = "block";
    } else {
      imgEl.style.display = "none";
    }

    previewCard.style.display = "flex";
  }
}

async function handleSubmitDeliverable(e) {
  e.preventDefault();
  const taskId = document.getElementById("submitTargetTaskId").value;
  const resultUrl = document.getElementById("deliverableResultUrlInput").value.trim();
  const productId = parseInt(document.getElementById("deliverableProductSelect").value) || 0;

  // 校验成品链接与关联商品均为必填项
  if (!resultUrl) {
    alert("【成品链接】为必填项，请输入成品链接！");
    document.getElementById("deliverableResultUrlInput").focus();
    return;
  }
  if (!productId || productId <= 0) {
    alert("【关联的品】为必选项，请选择已录入的商品！");
    document.getElementById("deliverableProductSelect").focus();
    return;
  }

  const btn = document.getElementById("submitDeliverableBtn");
  btn.disabled = true;
  btn.innerText = "正在保存...";

  try {
    const res = await fetch(`/api/tasks/${taskId}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        result_url: resultUrl,
        product_id: productId
      })
    });
    const json = await res.json();
    if (json.code === 0) {
      closeSubmitDeliverableModal();
      showToast("🎉 已成功登记成果并关联商品，任务状态更新为【已完成】！");
      await loadTasksList();
    } else {
      alert(`登记失败: ${json.detail || json.msg}`);
    }
  } catch (err) {
    alert(`请求异常: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerText = "保存";
  }
}

// ============================================================================
// 模态弹窗 3: 管理员修改任务派发信息
// ============================================================================
function openEditTaskModal(taskId) {
  closeDispatchModal();
  closeSubmitDeliverableModal();
  closeProductDetailModal();
  const task = taskState.tasks.find(t => t.id === taskId);
  if (!task) return;

  document.getElementById("editTaskId").value = task.id;
  document.getElementById("editTitleInput").value = task.title || "";
  document.getElementById("editRefUrlInput").value = task.reference_url || "";
  document.getElementById("editInstructionsInput").value = task.instructions || "";

  const editSelect = document.getElementById("editAssigneeSelect");
  if (editSelect) {
    editSelect.value = task.assigned_to || "";
  }

  const modal = document.getElementById("editTaskModal");
  if (modal) modal.style.display = "flex";
}

function closeEditTaskModal() {
  const modal = document.getElementById("editTaskModal");
  if (modal) modal.style.display = "none";
}

async function handleEditTaskSubmit(e) {
  e.preventDefault();
  const taskId = document.getElementById("editTaskId").value;
  const assignee = document.getElementById("editAssigneeSelect").value;
  const title = document.getElementById("editTitleInput").value.trim();
  const refUrl = document.getElementById("editRefUrlInput").value.trim();
  const instructions = document.getElementById("editInstructionsInput").value.trim();

  if (!assignee) {
    alert("请选择执行人！");
    return;
  }
  if (!refUrl) {
    alert("请输入参考链接！");
    return;
  }

  const btn = document.getElementById("editSubmitBtn");
  btn.disabled = true;
  btn.innerText = "正在保存...";

  try {
    const res = await fetch(`/api/tasks/${taskId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        assigned_to: assignee,
        title: title,
        reference_url: refUrl,
        instructions: instructions
      })
    });
    const json = await res.json();
    if (json.code === 0) {
      closeEditTaskModal();
      showToast("💾 任务信息修改成功！");
      await loadTasksList();
    } else {
      alert(`修改失败: ${json.detail || json.msg}`);
    }
  } catch (err) {
    alert(`请求异常: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerText = "保存";
  }
}

// ============================================================================
// 模态弹窗 4: 点击关联商品查看完整商品详情
// ============================================================================
function closeProductDetailModal() {
  const modal = document.getElementById("productDetailModal");
  if (modal) modal.style.display = "none";
}

async function viewProductDetail(productId) {
  closeDispatchModal();
  closeSubmitDeliverableModal();
  closeEditTaskModal();

  const modal = document.getElementById("productDetailModal");
  if (!modal) return;
  const body = document.getElementById("modalContentBody");
  body.innerHTML = "<div style='text-align:center; padding:40px; color:#64748b;'>⏳ 正在加载商品完整结构化数据...</div>";
  modal.style.display = "flex";

  try {
    const res = await fetch(`/api/products/${productId}`);
    const result = await res.json();
    if (result.code !== 0 || !result.data) {
      body.innerHTML = `<div style="color:#dc2626; padding:20px;">加载详情失败: ${result.msg || '商品不存在'}</div>`;
      return;
    }

    const p = result.data;
    document.getElementById("modalProductTitle").textContent = p.title || "商品详情";
    document.getElementById("modalParentSku").textContent = p.parent_sku || p.sku || "-";
    document.getElementById("modalStoreAccount").textContent = p.store_account || "-";
    document.getElementById("modalCreatedBy").textContent = p.created_by || "admin";

    // 渲染详情 HTML
    let html = `
      <!-- 1. 基础信息与尺寸 Card 1~3, 9~10 -->
      <div class="detail-section">
        <div class="detail-section-title">📌 1. 基础信息、型号与尺寸规格</div>

        <!-- 1.1 增加标题单独醒目展示 (白色底色，突出醒目) -->
        <div style="margin-bottom:14px; background:#ffffff; border:1px solid #e2e8f0; border-left:4px solid #2563eb; border-radius:6px; padding:12px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.03);">
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">
            <div class="detail-field-label" style="font-weight:700; color:#1e40af; font-size:0.84rem; display:inline-flex; align-items:center; gap:4px;">
              <span>📝 商品标题 (Product Title)</span>
            </div>
            <span class="tag-badge" style="background:#eff6ff; color:#2563eb; font-size:0.75rem; font-weight:600; border-color:#bfdbfe;">Amazon 日本站标题</span>
          </div>
          <div style="font-size:1.05rem; font-weight:700; color:#0f172a; line-height:1.55; word-break:break-word;">
            ${p.title || '<span style="color:#94a3b8;">未命名商品</span>'}
          </div>
        </div>

        <div class="detail-grid">
          <div><div class="detail-field-label">店铺账号</div><div class="detail-field-value">${p.store_account || '-'}</div></div>
          <div><div class="detail-field-label">品牌 (Brand)</div><div class="detail-field-value"><span class="tag-badge" style="background:#fef3c7; color:#92400e; font-weight:700; border-color:#fde68a;">🏷️ ${p.brand || '-'}</span></div></div>
          <div><div class="detail-field-label">Parent SKU</div><div class="detail-field-value" style="font-family:monospace; color:#2563eb;">${p.parent_sku || p.sku || '-'}</div></div>
          <div><div class="detail-field-label">售卖形式</div><div class="detail-field-value">${p.sale_type === 'single' ? '单品 (single)' : '多变体 (variation)'}</div></div>
          <div><div class="detail-field-label">变种主题</div><div class="detail-field-value">${p.variation_theme || '-'}</div></div>
          <div><div class="detail-field-label">品番・型番(型号)</div><div class="detail-field-value">${p.model_number || '-'}</div></div>
          <div><div class="detail-field-label">モデル名(型号名称)</div><div class="detail-field-value">${p.model_name || '-'}</div></div>
          <div><div class="detail-field-label">品目寸法 (长×宽×高)</div><div class="detail-field-value">${p.item_length || 0} × ${p.item_width || 0} × ${p.item_height || 0} ${p.item_dim_unit || p.item_dimension_unit || 'cm'}</div></div>
          <div><div class="detail-field-label">包装寸法 (长×宽×高)</div><div class="detail-field-value">${p.package_length || 0} × ${p.package_width || 0} × ${p.package_height || 0} ${p.package_dim_unit || p.package_dimension_unit || 'cm'}</div></div>
          <div><div class="detail-field-label">包装重量</div><div class="detail-field-value">${p.package_weight || 0} ${p.package_weight_unit || 'kg'}</div></div>
          <div><div class="detail-field-label">配送渠道</div><div class="detail-field-value"><span class="tag-badge" style="background:#eff6ff; color:#2563eb;">${p.fulfillment_channel || 'FBM'}</span></div></div>
          <div><div class="detail-field-label">维护人</div><div class="detail-field-value"><span class="tag-badge" style="background:#f3e8ff; color:#7e22ce;">${p.created_by || 'admin'}</span></div></div>
          <div><div class="detail-field-label">维护时间</div><div class="detail-field-value" style="font-size:0.8rem; color:#64748b;">${p.updated_at || p.created_at || '-'}</div></div>
        </div>
        <div style="margin-top:12px;">
          <div class="detail-field-label" style="font-weight:700; margin-bottom:4px;">Search Terms (搜索关键词)</div>
          <div style="font-size:0.88rem; color:#1e293b; background:#ffffff; padding:10px 14px; border-radius:6px; border:1px solid #e2e8f0; word-break:break-word;">
            ${p.search_terms || p.title || '-'}
          </div>
        </div>
      </div>

      <!-- 2. 图片展示与变体属性维度配置 (不直接显示文本路径，悬停浮框显示路径，点击放大) -->
      <div class="detail-section">
        <div class="detail-section-title">🖼️ 2. 商品主图、附图与变体选项图文配置</div>
        
        <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:16px;">
          <!-- 2.1 主图 -->
          <div style="flex:0 0 auto;">
            <div class="detail-field-label" style="margin-bottom:6px; font-weight:700;">★ 商品主图</div>
            ${p.main_image ? `
              <div style="width:100px; height:100px; border-radius:8px; border:1px solid #cbd5e1; overflow:hidden; background:#f8fafc; cursor:pointer; box-shadow:0 1px 4px rgba(0,0,0,0.06); transition:all 0.2s;" 
                   title="图片路径: ${p.main_image} (点击放大)"
                   onmouseenter="this.style.transform='scale(1.03)'; this.style.borderColor='#3b82f6';"
                   onmouseleave="this.style.transform='none'; this.style.borderColor='#cbd5e1';"
                   onclick="previewImageLightbox('/api/images/preview?path=${encodeURIComponent(p.main_image)}', '主图 (main_image): ${p.main_image}')">
                <img src="/api/images/preview?path=${encodeURIComponent(p.main_image)}" 
                     alt="主图" 
                     style="width:100%; height:100%; object-fit:cover;"
                     onerror="this.style.display='none';">
              </div>
            ` : '<div style="width:100px; height:100px; border-radius:8px; border:1px dashed #cbd5e1; background:#f8fafc; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:0.8rem;">无主图</div>'}
          </div>

          <!-- 2.2 附图相册 -->
          <div style="flex:1; min-width:260px;">
            <div class="detail-field-label" style="margin-bottom:6px; font-weight:700;">📷 附图相册 (${(p.extra_images && p.extra_images.length) || 0} 张)</div>
            ${(p.extra_images && p.extra_images.length) ? `
              <div style="display:flex; gap:10px; flex-wrap:wrap;">
                ${p.extra_images.map((img, idx) => `
                  <div style="width:80px; height:80px; border-radius:8px; border:1px solid #cbd5e1; overflow:hidden; background:#f8fafc; cursor:pointer; box-shadow:0 1px 3px rgba(0,0,0,0.06); transition:all 0.2s;"
                       title="附图 #${idx + 1} 路径: ${img} (点击放大)"
                       onmouseenter="this.style.transform='scale(1.03)'; this.style.borderColor='#3b82f6';"
                       onmouseleave="this.style.transform='none'; this.style.borderColor='#cbd5e1';"
                       onclick="previewImageLightbox('/api/images/preview?path=${encodeURIComponent(img)}', '附图 #${idx + 1}: ${img}')">
                    <img src="/api/images/preview?path=${encodeURIComponent(img)}" 
                         alt="附图"
                         style="width:100%; height:100%; object-fit:cover;"
                         onerror="this.style.display='none';">
                  </div>
                `).join('')}
              </div>
            ` : '<div style="color:#94a3b8; font-size:0.85rem; padding:10px 0;">无附图</div>'}
          </div>
        </div>

        <!-- 2.3 变体图片录入维度与选项对应图片 (优化展示方式) -->
        <div style="margin-top:14px; border-top:1px dashed #e2e8f0; padding-top:14px;">
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; flex-wrap:wrap; gap:8px;">
            <div style="font-weight:700; color:#1e293b; font-size:0.88rem; display:flex; align-items:center; gap:6px;">
              <span>🎨 变体选项与对应图片配置</span>
            </div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:0.8rem; color:#64748b;">录入维度:</span>
              <span class="tag-badge" style="background:#ecfdf5; color:#059669; font-weight:700;">
                按${p.variant_image_dimension === 'size' ? '尺寸 (size)' : '颜色 (color)'}录入
              </span>
            </div>
          </div>
          
          <!-- 变体选项与对应图片卡片网格 -->
          <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(130px, 1fr)); gap:12px;">
            ${renderVariantDimensionCards(p)}
          </div>
        </div>
      </div>

      <!-- 3. 五点描述与中文翻译对照 (Card 8) -->
      <div class="detail-section">
        <div class="detail-section-title">📝 3. 五点描述 (日文) & 逐条中文翻译参考 (Card 8)</div>
        <div>
          ${renderBulletPointsCompare(p.bullet_points || [], p.chinese_translations || [])}
        </div>
        ${p.description ? `
          <div style="margin-top:14px;">
            <div class="detail-field-label">商品长描述 (Description)</div>
            <pre style="background:#f8fafc; padding:10px 14px; border-radius:6px; border:1px solid #e2e8f0; font-size:0.84rem; white-space:pre-wrap; color:#334155; margin-top:4px; font-family:inherit;">${p.description}</pre>
          </div>
        ` : ''}
      </div>

      <!-- 4. 变体明细矩阵表 (is_parent = 0) -->
      <div class="detail-section">
        <div class="detail-section-title">📊 4. 变体明细数据 (${(p.variations || []).length} 个子变体)</div>
        <div class="table-wrapper" style="overflow-x:auto;">
          <table class="matrix-table" style="width:100%; font-size:0.83rem;">
            <thead>
              <tr style="background:#f8fafc;">
                <th style="width:60px; text-align:center;">图片</th>
                <th>子 SKU 编码</th>
                <th style="width:75px;">颜色</th>
                <th style="width:65px;">尺寸</th>
                <th style="width:105px;">尺寸(cm)</th>
                <th style="width:75px;">重量(kg)</th>
                <th style="width:75px;">采购价(¥)</th>
                <th style="width:60px;">系数</th>
                <th style="width:145px;">快递选择及运费</th>
                <th style="width:85px;">售价(JPY)</th>
                <th style="width:60px;">库存</th>
                <th style="width:125px;">EAN 条码</th>
              </tr>
            </thead>
            <tbody>
              ${renderVariationsRows(p.variations || [])}
            </tbody>
          </table>
        </div>
      </div>
    `;

    body.innerHTML = html;
  } catch (err) {
    body.innerHTML = `<div style="color:#dc2626; padding:20px;">系统异常: ${err.message}</div>`;
  }
}

function renderVariantDimensionCards(p) {
  const dim = p.variant_image_dimension || 'color';
  const options = (dim === 'size' ? (p.size_options || []) : (p.color_options || []));
  const mapping = p.variant_dimension_images || {};

  const allKeys = Array.from(new Set([...options, ...Object.keys(mapping)]));
  if (!allKeys.length) {
    return '<div style="grid-column:1/-1; color:#94a3b8; font-size:0.82rem; padding:10px 0;">暂无变体选项配置</div>';
  }

  return allKeys.map(opt => {
    const img = mapping[opt];
    return `
      <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px 8px; text-align:center; transition:all 0.2s;"
           onmouseenter="this.style.borderColor='#3b82f6'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.06)';"
           onmouseleave="this.style.borderColor='#e2e8f0'; this.style.boxShadow='none';">
        <div style="font-size:0.82rem; font-weight:700; color:#0f172a; margin-bottom:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${opt}">
          ${opt}
        </div>
        ${img ? `
          <div style="width:68px; height:68px; margin:0 auto; border-radius:6px; border:1px solid #cbd5e1; overflow:hidden; background:#fff; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
               title="图片路径: ${img} (点击放大)"
               onmouseenter="this.style.transform='scale(1.05)'; this.style.borderColor='#3b82f6';"
               onmouseleave="this.style.transform='none'; this.style.borderColor='#cbd5e1';"
               onclick="previewImageLightbox('/api/images/preview?path=${encodeURIComponent(img)}', '变体选项 [${opt}]: ${img}')">
            <img src="/api/images/preview?path=${encodeURIComponent(img)}" 
                 alt="${opt}" 
                 style="width:100%; height:100%; object-fit:cover;"
                 onerror="this.style.display='none';">
          </div>
        ` : `
          <div style="width:68px; height:68px; margin:0 auto; border-radius:6px; border:1px dashed #cbd5e1; background:#f1f5f9; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#94a3b8; font-size:0.75rem;" title="该选项未配置图片">
            <span style="font-size:1.1rem; margin-bottom:2px;">🖼️</span>
            未配置
          </div>
        `}
      </div>
    `;
  }).join('');
}

function renderBulletPointsCompare(bullets, trans) {
  if (!bullets.length) return '<div style="color:#94a3b8; font-size:0.85rem;">暂无五点描述</div>';
  return bullets.map((b, idx) => {
    let cn = (trans && trans[idx]) ? trans[idx] : '';
    cn = cn.replace(/^🇨🇳\s*中文翻译参考[:：]?\s*/, '').trim();
    return `
      <div class="bullet-compare-box">
        <div class="bullet-jp"><strong>#${idx + 1}.</strong> ${b}</div>
        ${cn ? `<div class="bullet-cn">🇨🇳 <strong>中文翻译参考:</strong> ${cn}</div>` : ''}
      </div>
    `;
  }).join('');
}

function calculateSkuFreights(length_cm, width_cm, height_cm, weight_kg) {
  const L = parseFloat(length_cm) || 0;
  const W = parseFloat(width_cm) || 0;
  const H = parseFloat(height_cm) || 0;
  let actWt = parseFloat(weight_kg) || 0.1;
  if (actWt <= 0) actWt = 0.1;

  const sumSides = L + W + H;
  const maxSide = sumSides > 0 ? Math.max(L, W, H) : 0;
  const minSide = sumSides > 0 ? Math.min(L, W, H) : 0;
  const midSide = sumSides - maxSide - minSide;

  const vol6000 = sumSides > 0 ? Math.ceil((L * W * H / 6000) * 1000) / 1000 : 0;
  const vol8000 = sumSides > 0 ? Math.ceil((L * W * H / 8000) * 1000) / 1000 : 0;

  let cwRiChuan = null;
  if (sumSides <= 960) {
    let rawCw = sumSides < 100 ? actWt : (actWt > vol6000 ? actWt : (actWt + vol6000) / 2);
    cwRiChuan = Math.ceil(rawCw / 0.5) * 0.5;
  }

  let cwChuDao = null;
  if (sumSides <= 140) cwChuDao = actWt;
  else if (sumSides <= 160) cwChuDao = (actWt + vol6000) / 2;
  else cwChuDao = Math.max(actWt, vol6000);

  let cwChuDao160 = sumSides <= 160 ? actWt : (actWt + vol6000) / 2;

  let cwSfLarge = null;
  if (!(maxSide > 200 || (midSide > 80 && minSide > 80) || (midSide > 70 && minSide > 70))) {
    cwSfLarge = Math.ceil(Math.max(actWt, vol6000) * 1000) / 1000;
  }

  let cwHeimao = null;
  if (sumSides <= 159) {
    cwHeimao = (cwSfLarge !== null && cwSfLarge <= 120) ? actWt : (actWt + vol6000) / 2;
  }

  const freights = [];

  // 1. 顺丰小包
  if (!(actWt > 30 || maxSide > 120 || sumSides > 160)) {
    const cw = Math.max(actWt, vol8000);
    const steps = Math.ceil(cw / 0.5);
    let base = 42 + (steps - 1) * 12;
    if (cw <= 2) base = 38 + (steps - 1) * 8;
    else if (cw <= 5) base = 40 + (steps - 1) * 9;
    else if (cw <= 10) base = 41 + (steps - 1) * 11;
    freights.push({ channel: "顺丰小包", cost: Math.round(base * 0.8 * 100) / 100 });
  }

  // 2. 顺丰国际大件
  if (cwSfLarge !== null) {
    if (cwSfLarge < 100) freights.push({ channel: "顺丰国际大件", cost: Math.max(cwSfLarge, 20) * 15 });
    else if (cwSfLarge <= 500) freights.push({ channel: "顺丰国际大件", cost: cwSfLarge * 14 });
    else if (cwSfLarge <= 1000) freights.push({ channel: "顺丰国际大件", cost: cwSfLarge * 13 });
  }

  // 3. 日川普货
  if (cwRiChuan !== null && actWt <= 20) {
    const steps = Math.ceil(cwRiChuan / 0.5);
    let base = 35 + (steps - 1) * 8;
    if (cwRiChuan <= 2) base = 32 + (steps - 1) * 6.5;
    else if (cwRiChuan <= 5) base = 33 + (steps - 1) * 7;
    else if (cwRiChuan <= 10) base = 34 + (steps - 1) * 7.5;
    let extraSize = sumSides > 239 ? 260 : (sumSides > 220 ? 200 : (sumSides > 200 ? 150 : (sumSides > 179 ? 100 : (sumSides > 159 ? 80 : 0))));
    let extraWt = actWt > 9.9 ? 50 : 0;
    freights.push({ channel: "日川普货", cost: base + extraSize + extraWt });
  }

  // 4. 日川带电
  if (cwRiChuan !== null && actWt <= 20) {
    const steps = Math.ceil(cwRiChuan / 0.5);
    let base = 37 + (steps - 1) * 8.5;
    if (cwRiChuan <= 2) base = 35 + (steps - 1) * 7;
    else if (cwRiChuan <= 5) base = 36 + (steps - 1) * 7.5;
    else if (cwRiChuan <= 10) base = 36 + (steps - 1) * 8;
    let extraSize = sumSides > 239 ? 260 : (sumSides > 220 ? 200 : (sumSides > 200 ? 150 : (sumSides > 179 ? 100 : (sumSides > 159 ? 80 : 0))));
    let extraWt = actWt > 9.9 ? 50 : 0;
    freights.push({ channel: "日川带电", cost: base + extraSize + extraWt });
  }

  // 5. 川日大包
  if (cwRiChuan !== null && cwRiChuan <= 900 && L <= 305 && W <= 175 && H <= 155) {
    let base = cwRiChuan * 16.5;
    if (cwRiChuan < 21) base = 60 + (Math.ceil(cwRiChuan / 0.5) - 1) * 18;
    else if (cwRiChuan < 51) base = cwRiChuan * 19;
    else if (cwRiChuan < 101) base = cwRiChuan * 18.5;
    else if (cwRiChuan < 301) base = cwRiChuan * 17.5;
    else if (cwRiChuan < 501) base = cwRiChuan * 17;
    let extra = (maxSide > 159 && cwRiChuan < 300) ? 200 : 0;
    freights.push({ channel: "川日大包", cost: Math.round((base + extra) * 100) / 100 });
  }

  // 6. 佐川大件
  if (cwRiChuan !== null && cwRiChuan <= 30 && sumSides <= 250 && maxSide <= 150) {
    const steps = Math.ceil(cwRiChuan / 0.5);
    freights.push({ channel: "佐川大件", cost: 40 + (steps - 1) * 10 });
  }

  // 7. 义乌小包
  if (cwChuDao !== null && actWt <= 20 && maxSide <= 9100 && sumSides <= 9160) {
    const steps = Math.ceil(cwChuDao / 0.5);
    let base = 36 + (steps - 1) * 8;
    if (cwChuDao <= 2) base = 34 + (steps - 1) * 6;
    else if (cwChuDao <= 5) base = 35 + (steps - 1) * 7;
    let extra1 = maxSide > 99 ? 35 : 0;
    let extra2 = sumSides > 200 ? 120 : (sumSides > 160 ? 80 : 0);
    freights.push({ channel: "义乌小包", cost: Math.ceil(base + Math.max(extra1, extra2)) });
  }

  // 8. 初岛160免泡
  if (cwChuDao160 !== null && actWt <= 20 && maxSide <= 9100 && sumSides <= 260) {
    const steps = Math.ceil(cwChuDao160 / 0.5);
    let base = 36 + (steps - 1) * 8;
    if (cwChuDao160 <= 2) base = 34 + (steps - 1) * 6;
    else if (cwChuDao160 <= 5) base = 35 + (steps - 1) * 7;
    let extraMax = sumSides > 200 ? 100 : (sumSides > 160 ? 50 : 0);
    let extraSum = sumSides > 200 ? 20 : (sumSides > 160 ? 30 : 0);
    freights.push({ channel: "初岛160免泡", cost: Math.ceil(base + extraMax + extraSum + 20) });
  }

  // 9. 初岛黑猫
  if (cwHeimao !== null && actWt <= 20 && maxSide <= 160 && sumSides <= 160) {
    const steps = Math.ceil(cwHeimao / 0.5);
    let base = 39 + (steps - 1) * 10;
    if (cwHeimao <= 2) base = 36 + (steps - 1) * 6;
    else if (cwHeimao <= 5) base = 37 + (steps - 1) * 7;
    else if (cwHeimao <= 10) base = 38 + (steps - 1) * 8;
    freights.push({ channel: "初岛黑猫", cost: Math.ceil(base) });
  }

  // 10. 航空邮政大包
  if (actWt <= 30 && maxSide <= 150 && ((sumSides - maxSide) * 2 + maxSide <= 330)) {
    const wtCeil = Math.ceil(actWt);
    freights.push({ channel: "航空邮政大包", cost: Math.round((124.2 + (wtCeil - 1) * 29.6 + 8.0) * 100) / 100 });
  }

  freights.sort((a, b) => a.cost - b.cost);
  return freights;
}

function renderVariationsRows(vars) {
  if (!vars.length) return '<tr><td colspan="12" style="text-align:center; padding:20px; color:#94a3b8;">暂无变体数据</td></tr>';
  return vars.map(v => {
    const imgPath = v.variant_image || v.main_image;
    const chosenChannel = v.shipping_channel || v.selected_channel || v.optimal_channel || '';
    const freights = calculateSkuFreights(v.length_cm, v.width_cm, v.height_cm, v.weight_kg || v.weight);

    let matchedFreight = freights.find(f => f.channel === chosenChannel);
    if (!matchedFreight && freights.length > 0) {
      matchedFreight = freights[0];
    }
    const currentChannelName = matchedFreight ? matchedFreight.channel : chosenChannel;
    const optimalChannelName = freights.length > 0 ? freights[0].channel : '';

    let channelHtml = '';
    if (freights.length > 0) {
      channelHtml = `
        <select class="readonly-channel-select" 
                style="width:100%; min-width:135px; padding:4px 6px; font-size:0.78rem; font-weight:600; color:#1e293b; background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; cursor:pointer; outline:none;"
                title="点击展开可查看全部快递公司报价（仅供比价查看，不可修改）"
                onfocus="this.dataset.origVal = this.value;"
                onchange="this.value = this.dataset.origVal || '${currentChannelName}';">
          ${freights.map(f => {
            const isSelected = (f.channel === currentChannelName);
            const isOptimal = (f.channel === optimalChannelName);
            return `<option value="${f.channel}" ${isSelected ? 'selected' : ''}>¥${f.cost} ${f.channel}${isOptimal ? ' ⭐' : ''}</option>`;
          }).join('')}
        </select>
      `;
    } else if (chosenChannel) {
      channelHtml = `<span class="tag-badge" style="font-size:0.75rem;">${chosenChannel}</span>`;
    } else {
      channelHtml = `<span style="color:#94a3b8; font-size:0.75rem;">未核算</span>`;
    }

    return `
      <tr>
        <td style="text-align:center;">
          ${imgPath ? `
            <div style="width:38px; height:38px; margin:0 auto; border-radius:4px; border:1px solid #cbd5e1; overflow:hidden; display:inline-flex; align-items:center; justify-content:center; background:#f8fafc; cursor:pointer;" 
                 title="图片路径: ${imgPath} (点击放大)"
                 onclick="previewImageLightbox('/api/images/preview?path=${encodeURIComponent(imgPath)}', 'SKU ${v.sku || ''}: ${imgPath}')">
              <img src="/api/images/preview?path=${encodeURIComponent(imgPath)}" 
                   style="width:100%; height:100%; object-fit:cover;"
                   onerror="this.style.display='none';">
              <span style="display:none; font-size:0.85rem;">🖼️</span>
            </div>
          ` : '<span style="color:#cbd5e1;">-</span>'}
        </td>
        <td style="font-family:monospace; font-weight:600; color:#0f172a;">${v.sku || '-'}</td>
        <td>${v.color || '-'}</td>
        <td>${v.size || '-'}</td>
        <td style="font-size:0.78rem;">${v.length_cm || 0}×${v.width_cm || 0}×${v.height_cm || 0}</td>
        <td>${v.weight_kg || v.weight || 0}</td>
        <td>¥${v.purchase_price || 0}</td>
        <td>${v.profit_coefficient || 1.0}</td>
        <td>${channelHtml}</td>
        <td style="font-weight:700; color:#dc2626;">¥${v.price_jpy || 0}</td>
        <td>${v.quantity || 0}</td>
        <td style="font-family:monospace; color:#2563eb;">${v.ean || '-'}</td>
      </tr>
    `;
  }).join('');
}

// ============================================================================
// 管理员删除任务
// ============================================================================
async function handleDeleteTask(taskId) {
  if (!confirm(`确定要彻底删除任务 #${taskId} 吗？此操作不可逆！`)) return;

  try {
    const res = await fetch(`/api/tasks/${taskId}`, { method: "DELETE" });
    const json = await res.json();
    if (json.code === 0) {
      showToast("🗑️ 任务已成功删除！");
      await loadTasksList();
    } else {
      alert(`删除失败: ${json.detail || json.msg}`);
    }
  } catch (err) {
    alert(`请求异常: ${err.message}`);
  }
}
