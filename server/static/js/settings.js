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
  },
  session_expire_hours: 1.0,
  chrome_user_data_dirs: {
    mac: "~/ChromeDebugUser",
    win: "C:\\ChromeDebugUser"
  },
  submit_ad_enabled: false,
  ai_config: {
    generate_bullets_enabled: false,
    bullets_source: "public",
    ollama_model: "qwen2.5:1.5b-instruct-q4_K_M",
    api_base_url: "https://api.deepseek.com",
    model_name: "deepseek-v4-flash",
    api_key: ""
  },
  // 桌面上件助手远程通道令牌 (内嵌图片服务 X-DB-Token, 原 db_agent 8765)
  db_agent_token: "",
  // 货代在线登记文档定时采集配置
  doc_sync: {
    sync_mode: "daily", sync_time: "08:00", interval_hours: 24,
    alert_days: 7, date_column: "采购日期", ship_column: "仓库发货日期", sheet_name: "发货数据",
    email_enabled: false, smtp_host: "smtp.qq.com", smtp_port: 465, smtp_ssl: true,
    smtp_user: "", smtp_password: "", mail_from: "", mail_to: "", subject_prefix: "[货代发货提醒]"
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
      const rawStores = result.data.store_accounts || [
        { store_name: "金梧汇辰", brand_name: "JINWU", is_default: true },
        { store_name: "店小秘通用测试", brand_name: "DXM", is_default: false }
      ];
      settingsState.storeAccounts = rawStores.map((st, i) => {
        const sName = typeof st === "string" ? st : (st.store_name || st.store || "");
        const bName = typeof st === "string" ? st : (st.brand_name || st.brand || sName);
        const isDef = typeof st === "object" ? !!st.is_default : (i === 0);
        return { store_name: sName, brand_name: bName, is_default: isDef };
      });
      if (settingsState.storeAccounts.length > 0 && !settingsState.storeAccounts.some(s => s.is_default)) {
        settingsState.storeAccounts[0].is_default = true;
      }

      if (result.data.pricing_config) {
        settingsState.pricingConfig = { ...result.data.pricing_config };
      }
      if (result.data.storage_paths) {
        settingsState.storagePaths = { ...result.data.storage_paths };
      }
      settingsState.session_expire_hours = result.data.session_expire_hours !== undefined ? parseFloat(result.data.session_expire_hours) : 1.0;
      if (result.data.chrome_user_data_dirs) {
        settingsState.chrome_user_data_dirs = { ...settingsState.chrome_user_data_dirs, ...result.data.chrome_user_data_dirs };
      }
      if (result.data.submit_ad_enabled !== undefined) {
        settingsState.submit_ad_enabled = !!result.data.submit_ad_enabled;
      }
      if (result.data.ai_config) {
        settingsState.ai_config = { ...settingsState.ai_config, ...result.data.ai_config };
      }
      if (result.data.db_agent_token !== undefined) {
        settingsState.db_agent_token = result.data.db_agent_token || "";
      }
      if (result.data.doc_sync) {
        settingsState.doc_sync = { ...settingsState.doc_sync, ...result.data.doc_sync };
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
  const sessionExpInp = document.getElementById("sessionExpireHoursInput");
  const chromeDirMacInp = document.getElementById("chromeUserDataDirMacInput");
  const chromeDirWinInp = document.getElementById("chromeUserDataDirWinInput");

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
  
  if (chromeDirMacInp) chromeDirMacInp.value = settingsState.chrome_user_data_dirs.mac || "~/ChromeDebugUser";
  if (chromeDirWinInp) chromeDirWinInp.value = settingsState.chrome_user_data_dirs.win || "C:\\ChromeDebugUser";

  const dbAgentTokenInp = document.getElementById("dbAgentTokenInput");
  if (dbAgentTokenInp) dbAgentTokenInp.value = settingsState.db_agent_token || "";

  // 货代文档采集配置回填
  const ds = settingsState.doc_sync;
  const dsMap = {
    docSyncModeSelect: ds.sync_mode, docSyncTimeInput: ds.sync_time,
    docSyncIntervalInput: ds.interval_hours, docAlertDaysInput: ds.alert_days,
    docDateColumnInput: ds.date_column, docShipColumnInput: ds.ship_column,
    docSheetNameInput: ds.sheet_name, docSmtpHostInput: ds.smtp_host,
    docSmtpPortInput: ds.smtp_port, docSmtpUserInput: ds.smtp_user,
    docSmtpPasswordInput: ds.smtp_password, docMailFromInput: ds.mail_from,
    docMailToInput: ds.mail_to, docSubjectPrefixInput: ds.subject_prefix
  };
  for (const [id, val] of Object.entries(dsMap)) {
    const el = document.getElementById(id);
    if (el) el.value = val == null ? "" : val;
  }
  const dsEnabled = document.getElementById("docEmailEnabledCheckbox");
  if (dsEnabled) dsEnabled.checked = !!ds.email_enabled;
  const dsSsl = document.getElementById("docSmtpSslCheckbox");
  if (dsSsl) dsSsl.checked = !!ds.smtp_ssl;

  const submitYes = document.getElementById("submitAdYes");
  const submitNo = document.getElementById("submitAdNo");
  if (submitYes && submitNo) {
    (settingsState.submit_ad_enabled ? submitYes : submitNo).checked = true;
  }

  const bulletsGenYes = document.getElementById("aiGenerateBulletsYes");
  const bulletsGenNo = document.getElementById("aiGenerateBulletsNo");
  if (bulletsGenYes && bulletsGenNo) {
    (settingsState.ai_config.generate_bullets_enabled ? bulletsGenYes : bulletsGenNo).checked = true;
  }

  const aiLocalRadio = document.getElementById("aiSourceLocal");
  const aiPublicRadio = document.getElementById("aiSourcePublic");
  if (aiLocalRadio && aiPublicRadio) {
    (settingsState.ai_config.bullets_source === "local" ? aiLocalRadio : aiPublicRadio).checked = true;
  }
  const aiOllamaInp = document.getElementById("aiOllamaModelInput");
  if (aiOllamaInp) aiOllamaInp.value = settingsState.ai_config.ollama_model || "qwen2.5:1.5b-instruct-q4_K_M";
  const aiBaseInp = document.getElementById("aiApiBaseUrlInput");
  if (aiBaseInp) aiBaseInp.value = settingsState.ai_config.api_base_url || "https://api.deepseek.com";
  const aiModelInp = document.getElementById("aiModelNameInput");
  if (aiModelInp) aiModelInp.value = settingsState.ai_config.model_name || "deepseek-v4-flash";
  const aiKeyInp = document.getElementById("aiApiKeyInput");
  if (aiKeyInp) aiKeyInp.value = settingsState.ai_config.api_key || "";

  const isNever = (settingsState.session_expire_hours !== undefined && parseFloat(settingsState.session_expire_hours) <= 0);
  const neverChk = document.getElementById("sessionNeverExpireCheckbox");
  const badge = document.getElementById("sessionBadge");
  if (sessionExpInp) {
    sessionExpInp.value = isNever ? 0 : (settingsState.session_expire_hours || 1.0);
    sessionExpInp.disabled = isNever;
  }
  if (neverChk) {
    neverChk.checked = isNever;
  }
  if (badge) {
    if (isNever) {
      badge.innerText = "♾️ 永久有效 (永不过期)";
      badge.style.background = "#dcfce7";
      badge.style.color = "#15803d";
      badge.style.borderColor = "#86efac";
    } else {
      badge.innerText = `${settingsState.session_expire_hours || 1.0}h 过期自动防护`;
      badge.style.background = "#f1f5f9";
      badge.style.color = "#475569";
      badge.style.borderColor = "#cbd5e1";
    }
  }
}

function setSessionPreset(hours) {
  const sessionExpInp = document.getElementById("sessionExpireHoursInput");
  const neverChk = document.getElementById("sessionNeverExpireCheckbox");
  const badge = document.getElementById("sessionBadge");
  const isNever = (hours <= 0);

  if (sessionExpInp) {
    sessionExpInp.value = isNever ? 0 : hours;
    sessionExpInp.disabled = isNever;
  }
  if (neverChk) {
    neverChk.checked = isNever;
  }
  if (badge) {
    if (isNever) {
      badge.innerText = "♾️ 永久有效 (永不过期)";
      badge.style.background = "#dcfce7";
      badge.style.color = "#15803d";
      badge.style.borderColor = "#86efac";
    } else {
      badge.innerText = `${hours}h 过期自动防护`;
      badge.style.background = "#f1f5f9";
      badge.style.color = "#475569";
      badge.style.borderColor = "#cbd5e1";
    }
  }
  showToast(`已选择预设：${isNever ? "♾️ 永久有效 (永不过期)" : hours + " 小时"}（请点击右上角保存配置）`);
}

// ============================================================================
// Store Accounts & Brands Management (1-to-1 required + Default Single Choice)
// ============================================================================
function renderStoreTable() {
  const tbody = document.getElementById("storeTableBody");
  const badge = document.getElementById("storeCountBadge");
  if (!tbody) return;

  tbody.innerHTML = "";
  if (badge) badge.innerText = `${settingsState.storeAccounts.length} 个店铺`;

  if (settingsState.storeAccounts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--text-muted);">暂无店铺配置，请在下方添加</td></tr>`;
    return;
  }

  // 确保有且仅有一个 is_default
  const hasDef = settingsState.storeAccounts.some(s => s.is_default);
  if (!hasDef && settingsState.storeAccounts.length > 0) {
    settingsState.storeAccounts[0].is_default = true;
  }

  settingsState.storeAccounts.forEach((item, idx) => {
    const sName = typeof item === "string" ? item : (item.store_name || item.store || "");
    const bName = typeof item === "string" ? item : (item.brand_name || item.brand || sName);
    const isDef = !!item.is_default;
    const tr = document.createElement("tr");
    if (isDef) {
      tr.style.background = "#f0fdf4";
    }

    tr.innerHTML = `
      <td style="text-align:center; font-weight:600; color:#64748b;">${idx + 1}</td>
      <td style="text-align:center;">
        <label style="cursor:pointer; display:inline-flex; align-items:center; justify-content:center; gap:4px; margin:0;" title="${isDef ? '当前默认店铺' : '点击设为默认店铺'}">
          <input type="radio" name="defaultStoreRadio" value="${idx}" ${isDef ? "checked" : ""} onchange="setDefaultStore(${idx})" style="accent-color:var(--primary); cursor:pointer; width:16px; height:16px;">
          ${isDef ? '<span class="tag-badge" style="background:#dcfce7; color:#15803d; font-weight:700; border-color:#86efac; font-size:0.72rem; padding:1px 6px;">默认</span>' : '<span style="font-size:0.75rem; color:#94a3b8;">设为默认</span>'}
        </label>
      </td>
      <td style="font-weight:600; color:#0f172a;">
        🏬 ${sName}
        ${isDef ? '<span style="color:#16a34a; font-size:0.8rem; margin-left:6px;" title="录入商品时默认排在第一项并自动选中">⭐ (默认展示)</span>' : ''}
      </td>
      <td><span class="tag-badge" style="background:#fef3c7; color:#92400e; font-weight:700; border-color:#fde68a;">🏷️ ${bName}</span></td>
      <td style="text-align:center;">
        <button class="btn btn-outline btn-sm" style="color:var(--danger); border-color:#fecaca; padding:3px 8px; font-size:0.75rem;" onclick="removeStore(${idx})" title="删除该店铺与品牌">🗑️ 删除</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function setDefaultStore(idx) {
  if (idx < 0 || idx >= settingsState.storeAccounts.length) return;
  settingsState.storeAccounts.forEach((st, i) => {
    st.is_default = (i === idx);
  });
  renderStoreTable();
  const defStore = settingsState.storeAccounts[idx];
  showToast(`已将【${defStore.store_name}】设为默认店铺（请点击右上角保存系统配置）`);
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

  const isFirst = settingsState.storeAccounts.length === 0;
  settingsState.storeAccounts.push({
    store_name: sVal,
    brand_name: bVal,
    is_default: isFirst
  });

  storeInp.value = "";
  brandInp.value = "";
  renderStoreTable();
  showToast(`已添加店铺【${sVal}】及其品牌【${bVal}】（可在上方列表中单选设为默认店铺）`);
}

function removeStore(idx) {
  const removed = settingsState.storeAccounts[idx];
  const sName = typeof removed === "string" ? removed : (removed.store_name || removed.store);
  const wasDefault = typeof removed === "object" ? !!removed.is_default : false;

  settingsState.storeAccounts.splice(idx, 1);
  if (wasDefault && settingsState.storeAccounts.length > 0) {
    settingsState.storeAccounts[0].is_default = true;
  }

  renderStoreTable();
  showToast(`已移除店铺【${sName}】（请记得点击右上角保存配置）`);
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
  const neverChk = document.getElementById("sessionNeverExpireCheckbox");
  let sessionExp = 1.0;
  if (neverChk && neverChk.checked) {
    sessionExp = 0;
  } else {
    const rawVal = document.getElementById("sessionExpireHoursInput")?.value;
    sessionExp = (rawVal !== undefined && rawVal !== "") ? parseFloat(rawVal) : 1.0;
    if (isNaN(sessionExp) || sessionExp < 0) sessionExp = 0;
  }

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
    },
    session_expire_hours: sessionExp,
    chrome_user_data_dirs: {
      mac: (document.getElementById("chromeUserDataDirMacInput")?.value || "").trim(),
      win: (document.getElementById("chromeUserDataDirWinInput")?.value || "").trim()
    },
    submit_ad_enabled: !!document.getElementById("submitAdYes")?.checked,
    ai_config: {
      generate_bullets_enabled: !!document.getElementById("aiGenerateBulletsYes")?.checked,
      bullets_source: document.getElementById("aiSourceLocal")?.checked ? "local" : "public",
      ollama_model: (document.getElementById("aiOllamaModelInput")?.value || "qwen2.5:1.5b-instruct-q4_K_M").trim(),
      api_base_url: (document.getElementById("aiApiBaseUrlInput")?.value || "https://api.deepseek.com").trim(),
      model_name: (document.getElementById("aiModelNameInput")?.value || "deepseek-v4-flash").trim(),
      api_key: (document.getElementById("aiApiKeyInput")?.value || "").trim()
    },
    db_agent_token: (document.getElementById("dbAgentTokenInput")?.value || "").trim(),
    doc_sync: {
      sync_mode: document.getElementById("docSyncModeSelect")?.value || "daily",
      sync_time: document.getElementById("docSyncTimeInput")?.value || "08:00",
      interval_hours: parseInt(document.getElementById("docSyncIntervalInput")?.value) || 24,
      alert_days: parseInt(document.getElementById("docAlertDaysInput")?.value) || 7,
      date_column: (document.getElementById("docDateColumnInput")?.value || "采购日期").trim(),
      ship_column: (document.getElementById("docShipColumnInput")?.value || "仓库发货日期").trim(),
      sheet_name: (document.getElementById("docSheetNameInput")?.value || "发货数据").trim(),
      email_enabled: !!document.getElementById("docEmailEnabledCheckbox")?.checked,
      smtp_host: (document.getElementById("docSmtpHostInput")?.value || "smtp.qq.com").trim(),
      smtp_port: parseInt(document.getElementById("docSmtpPortInput")?.value) || 465,
      smtp_ssl: !!document.getElementById("docSmtpSslCheckbox")?.checked,
      smtp_user: (document.getElementById("docSmtpUserInput")?.value || "").trim(),
      smtp_password: (document.getElementById("docSmtpPasswordInput")?.value || "").trim(),
      mail_from: (document.getElementById("docMailFromInput")?.value || "").trim(),
      mail_to: (document.getElementById("docMailToInput")?.value || "").trim(),
      subject_prefix: (document.getElementById("docSubjectPrefixInput")?.value || "[货代发货提醒]").trim()
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
      if (result.data.session_expire_hours !== undefined) {
        settingsState.session_expire_hours = result.data.session_expire_hours;
      }
      if (result.data.chrome_user_data_dirs !== undefined) {
        settingsState.chrome_user_data_dirs = result.data.chrome_user_data_dirs;
      }
      if (result.data.submit_ad_enabled !== undefined) {
        settingsState.submit_ad_enabled = !!result.data.submit_ad_enabled;
      }
      if (result.data.ai_config !== undefined) {
        settingsState.ai_config = result.data.ai_config;
      }
      if (result.data.db_agent_token !== undefined) {
        settingsState.db_agent_token = result.data.db_agent_token || "";
      }
      if (result.data.doc_sync !== undefined) {
        settingsState.doc_sync = { ...settingsState.doc_sync, ...result.data.doc_sync };
      }
      // 状态全部更新后再刷新表单, 避免用旧值覆盖刚保存的选项 (如五点描述生成来源单选框)
      populateForm();
      const isNever = (parseFloat(settingsState.session_expire_hours) <= 0);
      showToast(`🎉 系统管理配置（店铺、计价、归档目录、Session【${isNever ? '♾️ 永久有效' : settingsState.session_expire_hours + 'h'}】）已成功保存！`);
    } else {
      showToast(`保存失败: ${result.msg}`, "error");
    }
  } catch (err) {
    showToast(`保存异常: ${err.message}`, "error");
  }
}

function resetDefaults() {
  if (confirm("确定要恢复全部默认设置吗？")) {
    settingsState.storeAccounts = [
      { store_name: "金梧汇辰", brand_name: "JINWU", is_default: true },
      { store_name: "店小秘通用测试", brand_name: "DXM", is_default: false }
    ];
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
    settingsState.session_expire_hours = 1.0;
    settingsState.chrome_user_data_dirs = { mac: "~/ChromeDebugUser", win: "C:\\ChromeDebugUser" };
    settingsState.ai_config = {
      generate_bullets_enabled: false,
      bullets_source: "public",
      ollama_model: "qwen2.5:1.5b-instruct-q4_K_M",
      api_base_url: "https://api.deepseek.com",
      model_name: "deepseek-v4-flash",
      api_key: ""
    };
    populateForm();
    showToast("已重置为默认值，请点击保存生效！");
  }
}

// ============================================================================
// Sub-menu Tab Navigation (左侧子菜单切换面板)
// ============================================================================
function toggleTokenVisibility(btn, inputId) {
  const inp = document.getElementById(inputId);
  if (!inp) return;
  const show = inp.type === "password";
  inp.type = show ? "text" : "password";
  btn.textContent = show ? "🙈" : "👁";
  btn.title = show ? "隐藏令牌" : "显示令牌";
}

function activateSettingsTab(tabName) {
  document.querySelectorAll(".settings-nav-item").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".settings-panel").forEach(panel => {
    panel.classList.toggle("active", panel.dataset.panel === tabName);
  });
  if (history.replaceState) history.replaceState(null, "", `#${tabName}`);
}

function initSettingsTabs() {
  const nav = document.getElementById("settingsNav");
  if (!nav) return;
  nav.addEventListener("click", (e) => {
    const btn = e.target.closest(".settings-nav-item");
    if (btn && btn.dataset.tab) activateSettingsTab(btn.dataset.tab);
  });
  // 支持 #hash 直达对应配置面板 (如 /settings#ai)
  const hash = (location.hash || "").replace("#", "");
  const valid = hash && nav.querySelector(`.settings-nav-item[data-tab="${hash}"]`);
  if (valid) activateSettingsTab(hash);
}

// ============================================================================
// Initialization
// ============================================================================
document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  initSettingsTabs();

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

  const neverChk = document.getElementById("sessionNeverExpireCheckbox");
  const sessionExpInp = document.getElementById("sessionExpireHoursInput");
  const badge = document.getElementById("sessionBadge");
  if (neverChk && sessionExpInp) {
    neverChk.addEventListener("change", (e) => {
      if (e.target.checked) {
        sessionExpInp.value = 0;
        sessionExpInp.disabled = true;
        if (badge) {
          badge.innerText = "♾️ 永久有效 (永不过期)";
          badge.style.background = "#dcfce7";
          badge.style.color = "#15803d";
          badge.style.borderColor = "#86efac";
        }
      } else {
        sessionExpInp.value = 1.0;
        sessionExpInp.disabled = false;
        if (badge) {
          badge.innerText = "1.0h 过期自动防护";
          badge.style.background = "#f1f5f9";
          badge.style.color = "#475569";
          badge.style.borderColor = "#cbd5e1";
        }
      }
    });

    sessionExpInp.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      const isZero = (isNaN(val) || val <= 0);
      if (neverChk) neverChk.checked = isZero;
      if (badge) {
        if (isZero) {
          badge.innerText = "♾️ 永久有效 (永不过期)";
          badge.style.background = "#dcfce7";
          badge.style.color = "#15803d";
          badge.style.borderColor = "#86efac";
        } else {
          badge.innerText = `${val}h 过期自动防护`;
          badge.style.background = "#f1f5f9";
          badge.style.color = "#475569";
          badge.style.borderColor = "#cbd5e1";
        }
      }
    });
  }

  const saveBtn = document.getElementById("saveSettingsBtn");
  if (saveBtn) saveBtn.addEventListener("click", saveSettings);

  const resetBtn = document.getElementById("resetDefaultsBtn");
  if (resetBtn) resetBtn.addEventListener("click", resetDefaults);
});

// ============================================================================
// 货代文档采集: 测试邮件
// ============================================================================
async function sendDocSyncTestEmail() {
  const to = (document.getElementById("docMailToInput")?.value || "").trim();
  if (!to) {
    showToast("请先填写收件人再发送测试邮件", "error");
    return;
  }
  // 用表单当前值直接发送 (不落库), 避免"配置填了没保存导致测试误导"
  const payload = { doc_sync: {
    sync_mode: document.getElementById("docSyncModeSelect")?.value || "daily",
    sync_time: document.getElementById("docSyncTimeInput")?.value || "08:00",
    interval_hours: parseInt(document.getElementById("docSyncIntervalInput")?.value) || 24,
    alert_days: parseInt(document.getElementById("docAlertDaysInput")?.value) || 7,
    date_column: (document.getElementById("docDateColumnInput")?.value || "采购日期").trim(),
    ship_column: (document.getElementById("docShipColumnInput")?.value || "仓库发货日期").trim(),
    sheet_name: (document.getElementById("docSheetNameInput")?.value || "发货数据").trim(),
    email_enabled: true,
    smtp_host: (document.getElementById("docSmtpHostInput")?.value || "smtp.163.com").trim(),
    smtp_port: parseInt(document.getElementById("docSmtpPortInput")?.value) || 465,
    smtp_ssl: !!document.getElementById("docSmtpSslCheckbox")?.checked,
    smtp_user: (document.getElementById("docSmtpUserInput")?.value || "").trim(),
    smtp_password: (document.getElementById("docSmtpPasswordInput")?.value || "").trim(),
    mail_from: (document.getElementById("docMailFromInput")?.value || "").trim(),
    mail_to: to,
    subject_prefix: (document.getElementById("docSubjectPrefixInput")?.value || "[货代发货提醒]").trim()
  } };
  try {
    const res = await fetch("/api/forwarder-docs/test-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (res.ok && result.code === 0) {
      showToast(`📨 测试邮件已发送至 ${to} (测试通过后请记得点"保存设置")`, "success");
    } else {
      showToast(`发送失败: ${result.detail || result.msg || "未知错误"}`, "error");
    }
  } catch (err) {
    showToast(`发送异常: ${err.message}`, "error");
  }
}
