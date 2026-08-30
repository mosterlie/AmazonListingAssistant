/**
 * System Settings Management Frontend Logic
 * 店铺账号增删维护与 Calcfee 物流核心计价参数动态保存
 */

const settingsState = {
  storeAccounts: [],
  pricingConfig: {
    tax_rate: 0.17,
    exchange_rate: 23.0,
    price_coefficient: 26.0,
    default_profit_coeff: 1.0
  },
  storagePaths: {
    mac: "/Users/gx/Desktop/products",
    win: "D:\\products",
    rel_main: "main",
    rel_sku: "sku"
  }
};

function showToast(msg, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast-msg toast-${type}`;
  toast.innerText = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ============================================================================
// Load & Render Settings
// ============================================================================
async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const result = await res.json();
    if (result.code === 0 && result.data) {
      settingsState.storeAccounts = result.data.store_accounts || ["金梧汇辰", "店小秘通用测试"];
      if (result.data.pricing_config) {
        settingsState.pricingConfig = { ...result.data.pricing_config };
      }
      if (result.data.storage_paths) {
        settingsState.storagePaths = { ...result.data.storage_paths };
      }
      populateForm();
    }
  } catch (err) {
    showToast(`加载系统配置失败: ${err.message}`, "error");
  }
}

function populateForm() {
  renderStoreTable();

  const taxInp = document.getElementById("taxRateInput");
  const exInp = document.getElementById("exchangeRateInput");
  const coeffInp = document.getElementById("priceCoeffInput");
  const profitInp = document.getElementById("defaultProfitCoeffInput");
  const formulaPreview = document.getElementById("formulaCoeffPreview");
  const pathMacInp = document.getElementById("storagePathMacInput");
  const pathWinInp = document.getElementById("storagePathWinInput");
  const relMainInp = document.getElementById("storageRelMainInput");
  const relSkuInp = document.getElementById("storageRelSkuInput");
  const previewRelMain = document.getElementById("previewRelMain");
  const previewRelSku = document.getElementById("previewRelSku");

  if (taxInp) taxInp.value = settingsState.pricingConfig.tax_rate;
  if (exInp) exInp.value = settingsState.pricingConfig.exchange_rate;
  if (coeffInp) {
    coeffInp.value = settingsState.pricingConfig.price_coefficient;
    if (formulaPreview) formulaPreview.innerText = settingsState.pricingConfig.price_coefficient;
  }
  if (profitInp) profitInp.value = settingsState.pricingConfig.default_profit_coeff;

  if (pathMacInp) pathMacInp.value = settingsState.storagePaths.mac || "/Users/gx/Desktop/products";
  if (pathWinInp) pathWinInp.value = settingsState.storagePaths.win || "D:\\products";
  if (relMainInp) {
    relMainInp.value = settingsState.storagePaths.rel_main || "main";
    if (previewRelMain) previewRelMain.innerText = `${relMainInp.value}/`;
  }
  if (relSkuInp) {
    relSkuInp.value = settingsState.storagePaths.rel_sku || "sku";
    if (previewRelSku) previewRelSku.innerText = `${relSkuInp.value}/`;
  }
}

// ============================================================================
// Store Accounts & Brands Management (1-to-1 required)
// ============================================================================
function renderStoreTable() {
  const tbody = document.getElementById("storeTableBody");
  const badge = document.getElementById("storeCountBadge");
  if (!tbody) return;

  tbody.innerHTML = "";
  if (badge) badge.innerText = `${settingsState.storeAccounts.length} 个店铺`;

  if (settingsState.storeAccounts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:20px; color:var(--text-muted);">暂无店铺配置，请在下方添加</td></tr>`;
    return;
  }

  settingsState.storeAccounts.forEach((item, idx) => {
    const sName = typeof item === "string" ? item : (item.store_name || item.store || "");
    const bName = typeof item === "string" ? item : (item.brand_name || item.brand || sName);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="text-align:center; font-weight:600; color:#64748b;">${idx + 1}</td>
      <td style="font-weight:600; color:#0f172a;">🏬 ${sName}</td>
      <td><span class="tag-badge" style="background:#fef3c7; color:#92400e; font-weight:700; border-color:#fde68a;">🏷️ ${bName}</span></td>
      <td style="text-align:center;">
        <button class="btn btn-outline btn-sm" style="color:var(--danger); border-color:#fecaca; padding:3px 8px; font-size:0.75rem;" onclick="removeStore(${idx})" title="删除该店铺与品牌">🗑️ 删除</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function addStore() {
  const storeInp = document.getElementById("newStoreInput");
  const brandInp = document.getElementById("newBrandInput");
  if (!storeInp || !brandInp) return;
  const sVal = storeInp.value.trim();
  const bVal = brandInp.value.trim();

  if (!sVal) {
    showToast("请输入店铺名称！", "error");
    return;
  }
  if (!bVal) {
    showToast("品牌名称为必填项，请输入对应品牌！", "error");
    return;
  }

  if (settingsState.storeAccounts.some(item => {
    const name = typeof item === "string" ? item : (item.store_name || item.store);
    return name === sVal;
  })) {
    showToast("该店铺名称已存在，请勿重复添加！", "error");
    return;
  }

  settingsState.storeAccounts.push({ store_name: sVal, brand_name: bVal });
  storeInp.value = "";
  brandInp.value = "";
  renderStoreTable();
  showToast(`已添加店铺【${sVal}】及其品牌【${bVal}】（请点击右上角保存配置）`);
}

function removeStore(idx) {
  const removed = settingsState.storeAccounts[idx];
  const sName = typeof removed === "string" ? removed : (removed.store_name || removed.store);
  settingsState.storeAccounts.splice(idx, 1);
  renderStoreTable();
  showToast(`已移除店铺【${sName}】（请记得点击右上角保存）`);
}

// ============================================================================
// Save & Reset Settings
// ============================================================================
async function saveSettings() {
  const taxVal = parseFloat(document.getElementById("taxRateInput")?.value) || 0.17;
  const exVal = parseFloat(document.getElementById("exchangeRateInput")?.value) || 23.0;
  const coeffVal = parseFloat(document.getElementById("priceCoeffInput")?.value) || 26.0;
  const profitVal = parseFloat(document.getElementById("defaultProfitCoeffInput")?.value) || 1.0;
  const macPath = (document.getElementById("storagePathMacInput")?.value || "/Users/gx/Desktop/products").trim();
  const winPath = (document.getElementById("storagePathWinInput")?.value || "D:\\products").trim();
  const relMain = (document.getElementById("storageRelMainInput")?.value || "main").trim();
  const relSku = (document.getElementById("storageRelSkuInput")?.value || "sku").trim();

  if (settingsState.storeAccounts.length === 0) {
    showToast("至少需要配置一个店铺账号！", "error");
    return;
  }

  const payload = {
    store_accounts: settingsState.storeAccounts,
    pricing_config: {
      tax_rate: taxVal,
      exchange_rate: exVal,
      price_coefficient: coeffVal,
      default_profit_coeff: profitVal
    },
    storage_paths: {
      mac: macPath,
      win: winPath,
      rel_main: relMain,
      rel_sku: relSku
    }
  };

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (result.code === 0) {
      settingsState.pricingConfig = result.data.pricing_config;
      if (result.data.storage_paths) {
        settingsState.storagePaths = result.data.storage_paths;
      }
      showToast("🎉 系统管理配置（店铺、计价、绝对/相对归档目录）已成功保存！");
    } else {
      showToast(`保存失败: ${result.msg}`, "error");
    }
  } catch (err) {
    showToast(`保存异常: ${err.message}`, "error");
  }
}

function resetDefaults() {
  if (confirm("确定要恢复全部默认设置吗？")) {
    settingsState.storeAccounts = ["金梧汇辰", "店小秘通用测试"];
    settingsState.pricingConfig = {
      tax_rate: 0.17,
      exchange_rate: 23.0,
      price_coefficient: 26.0,
      default_profit_coeff: 1.0
    };
    settingsState.storagePaths = {
      mac: "/Users/gx/Desktop/products",
      win: "D:\\products",
      rel_main: "main",
      rel_sku: "sku"
    };
    populateForm();
    showToast("已重置为默认值，请点击保存生效！");
  }
}

// ============================================================================
// Initialization
// ============================================================================
document.addEventListener("DOMContentLoaded", () => {
  loadSettings();

  const addBtn = document.getElementById("addStoreBtn");
  if (addBtn) addBtn.addEventListener("click", addStore);

  const newStoreInp = document.getElementById("newStoreInput");
  if (newStoreInp) {
    newStoreInp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addStore();
      }
    });
  }

  const coeffInp = document.getElementById("priceCoeffInput");
  const formulaPreview = document.getElementById("formulaCoeffPreview");
  if (coeffInp && formulaPreview) {
    coeffInp.addEventListener("input", (e) => {
      formulaPreview.innerText = e.target.value || "26.0";
    });
  }

  const relMainInp = document.getElementById("storageRelMainInput");
  const previewRelMain = document.getElementById("previewRelMain");
  if (relMainInp && previewRelMain) {
    relMainInp.addEventListener("input", (e) => {
      previewRelMain.innerText = `${e.target.value || "main"}/`;
    });
  }

  const relSkuInp = document.getElementById("storageRelSkuInput");
  const previewRelSku = document.getElementById("previewRelSku");
  if (relSkuInp && previewRelSku) {
    relSkuInp.addEventListener("input", (e) => {
      previewRelSku.innerText = `${e.target.value || "sku"}/`;
    });
  }

  const saveBtn = document.getElementById("saveSettingsBtn");
  if (saveBtn) saveBtn.addEventListener("click", saveSettings);

  const resetBtn = document.getElementById("resetDefaultsBtn");
  if (resetBtn) resetBtn.addEventListener("click", resetDefaults);
});
