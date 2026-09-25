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
  // 邮件通知配置 (SMTP 发信通道 + 默认收件人; 存 fwd_doc_* 扁平键, 提醒规则在「提醒任务」页)
  email_notify: {
    smtp_host: "smtp.qq.com", smtp_port: 465, smtp_ssl: true,
    smtp_user: "", smtp_password: "", mail_from: "", mail_to: ""
  },
  // 物流渠道计费规则 (null=未自定义, 前端回退 pricing_tool.js 内置默认)
  channelRules: null
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
      if (result.data.email_notify) {
        settingsState.email_notify = { ...settingsState.email_notify, ...result.data.email_notify };
      }
      if (result.data.channel_rules !== undefined) {
        settingsState.channelRules = (Array.isArray(result.data.channel_rules) && result.data.channel_rules.length)
          ? result.data.channel_rules : null;
      }

      populateForm();
      renderChannelRules();
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

  // 邮件通知配置回填 (SMTP 通道 + 默认收件人; 提醒规则已迁往「提醒任务」页)
  const en = settingsState.email_notify;
  const enMap = {
    docSmtpHostInput: en.smtp_host,
    docSmtpPortInput: en.smtp_port, docSmtpUserInput: en.smtp_user,
    docSmtpPasswordInput: en.smtp_password, docMailFromInput: en.mail_from,
    docMailToInput: en.mail_to
  };
  for (const [id, val] of Object.entries(enMap)) {
    const el = document.getElementById(id);
    if (el) el.value = val == null ? "" : val;
  }
  const enSsl = document.getElementById("docSmtpSslCheckbox");
  if (enSsl) enSsl.checked = !!en.smtp_ssl;

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
    // 邮件通知配置 (SMTP 发信通道 + 默认收件人; 提醒规则在「提醒任务」页)
    email_notify: {
      smtp_host: (document.getElementById("docSmtpHostInput")?.value || "smtp.qq.com").trim(),
      smtp_port: parseInt(document.getElementById("docSmtpPortInput")?.value) || 465,
      smtp_ssl: !!document.getElementById("docSmtpSslCheckbox")?.checked,
      smtp_user: (document.getElementById("docSmtpUserInput")?.value || "").trim(),
      smtp_password: (document.getElementById("docSmtpPasswordInput")?.value || "").trim(),
      mail_from: (document.getElementById("docMailFromInput")?.value || "").trim(),
      mail_to: (document.getElementById("docMailToInput")?.value || "").trim()
    },
    // 物流渠道计费规则 (恢复默认时提交 null 清除自定义配置)
    channel_rules: crResetPending ? null : collectChannelRules()
  };
  crResetPending = false;

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
      if (result.data.email_notify !== undefined) {
        settingsState.email_notify = { ...settingsState.email_notify, ...result.data.email_notify };
      }
      if (result.data.channel_rules !== undefined) {
        settingsState.channelRules = (Array.isArray(result.data.channel_rules) && result.data.channel_rules.length)
          ? result.data.channel_rules : null;
        renderChannelRules();
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
    settingsState.channelRules = null;
    settingsState.ai_config = {
      generate_bullets_enabled: false,
      bullets_source: "public",
      ollama_model: "qwen2.5:1.5b-instruct-q4_K_M",
      api_base_url: "https://api.deepseek.com",
      model_name: "deepseek-v4-flash",
      api_key: ""
    };
    populateForm();
    renderChannelRules();
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

  // 物流渠道计费标准面板
  const crSaveBtn = document.getElementById("saveChannelRulesBtn");
  if (crSaveBtn) crSaveBtn.addEventListener("click", saveSettings);
  const crResetBtn = document.getElementById("resetChannelRulesBtn");
  if (crResetBtn) crResetBtn.addEventListener("click", resetChannelRules);
  const crAddBtn = document.getElementById("addChannelRuleBtn");
  if (crAddBtn) crAddBtn.addEventListener("click", addChannelRule);
  initChannelRulesEditor();
});

// ============================================================================
// 邮件通知: 测试汇总邮件 (用表单当前值直接发送, 不落库)
// ============================================================================
async function sendEmailTestEmail() {
  const to = (document.getElementById("docMailToInput")?.value || "").trim();
  if (!to) {
    showToast("请先填写收件人再发送测试邮件", "error");
    return;
  }
  const payload = { email_notify: {
    smtp_host: (document.getElementById("docSmtpHostInput")?.value || "smtp.qq.com").trim(),
    smtp_port: parseInt(document.getElementById("docSmtpPortInput")?.value) || 465,
    smtp_ssl: !!document.getElementById("docSmtpSslCheckbox")?.checked,
    smtp_user: (document.getElementById("docSmtpUserInput")?.value || "").trim(),
    smtp_password: (document.getElementById("docSmtpPasswordInput")?.value || "").trim(),
    mail_from: (document.getElementById("docMailFromInput")?.value || "").trim(),
    mail_to: to
  } };
  try {
    const res = await fetch("/api/forwarder-docs/test-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (res.ok && result.code === 0) {
      showToast(`📨 测试邮件已发送至 ${to} (测试通过后请记得点"保存配置")`, "success");
    } else {
      showToast(`发送失败: ${result.detail || result.msg || "未知错误"}`, "error");
    }
  } catch (err) {
    showToast(`发送异常: ${err.message}`, "error");
  }
}

// ============================================================================
// 物流渠道计费标准编辑器 (通用维度模型: limits / charge_weight / pricing / surcharges)
// 工作副本 crWorking 随渲染重建; 结构性增删先从 DOM 收集再改再渲染, 不丢已编辑内容
// ============================================================================
let crWorking = null;       // 当前编辑中的规则数组
let crResetPending = false; // 「恢复默认」标记: 下次保存提交 channel_rules=null
const crOpen = {};          // 卡片展开状态 (按索引)

function crDefaults() {
  const eng = window.PricingToolEngine;
  return JSON.parse(JSON.stringify(eng && eng.DEFAULT_CHANNEL_RULES ? eng.DEFAULT_CHANNEL_RULES : []));
}

function crEsc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function crNumField(f, label, val, ph) {
  return `<div style="flex:1;min-width:90px;"><label style="font-size:.72rem;color:#64748b;display:block;margin-bottom:2px;" title="${crEsc(label)}">${crEsc(label)}</label>` +
    `<input type="number" step="any" data-f="${f}" value="${val === null || val === undefined ? "" : crEsc(val)}" placeholder="${crEsc(ph || "")}" ` +
    `style="width:100%;box-sizing:border-box;padding:6px 8px;border:1px solid #cbd5e1;border-radius:6px;font-size:.82rem;"></div>`;
}

function crSelField(f, label, val, opts, w) {
  const o = opts.map(([v, t]) => `<option value="${crEsc(v)}" ${String(val === null || val === undefined ? "" : val) === String(v) ? "selected" : ""}>${crEsc(t)}</option>`).join("");
  return `<div style="flex:0 0 auto;"><label style="font-size:.72rem;color:#64748b;display:block;margin-bottom:2px;" title="${crEsc(label)}">${crEsc(label)}</label>` +
    `<select data-f="${f}" style="width:${w || "130px"};box-sizing:border-box;padding:6px 6px;border:1px solid #cbd5e1;border-radius:6px;font-size:.82rem;background:#fff;">${o}</select></div>`;
}

const CR_CMP = [["lte", "≤ 上限"], ["lt", "< 上限"]];
const CR_MODE = [
  ["actual", "实重"], ["max_actual_vol", "实重/体积重取大"],
  ["avg_actual_vol", "实重与体积重均值"], ["max_actual_avg", "实重与均值取大"],
  ["cond_vol_cap", "条件封顶(黑猫)"]
];
const CR_ACT = [["actual", "实重"], ["avg", "均值"]];
const CR_BASIS = [["sum_sides", "三边和"], ["max_side", "最长边"], ["weight", "实重"]];
const CR_PICK = [["add", "组内相加"], ["max", "组内取大"]];
const CR_PTYPE = [["tiered_step", "阶梯首续型"], ["first_continue", "首重续重型"]];
const CR_RT = [["", "不取整"], ["round2", "四舍五入2位"], ["ceil", "向上取整"]];
const CR_RTO = [["", "不进位"], ["0.5", "0.5kg进位"], ["1", "1kg进位"], ["0.001", "保留3位小数"]];

function crRow(inner) {
  return `<div style="display:flex;gap:6px;align-items:flex-end;flex-wrap:wrap;">${inner}</div>`;
}

function crSecTitle(txt) {
  return `<div style="font-size:.8rem;font-weight:700;color:#334155;margin:12px 0 6px;padding-left:8px;border-left:3px solid #8b5cf6;">${crEsc(txt)}</div>`;
}

function renderChannelCard(rule, ci) {
  const lim = rule.limits || {};
  const cw = rule.charge_weight || {};
  const p = rule.pricing || {};
  const open = !!crOpen[ci];

  const rboRows = (lim.reject_both_over || []).map((g, ri) => crRow(
    crNumField("rbo.mid", "中边>", g.mid, "80") +
    crNumField("rbo.min", "最小边>", g.min, "80") +
    `<button type="button" class="btn btn-outline btn-sm" data-act="del-rbo" data-ci="${ci}" data-ri="${ri}" style="margin-bottom:2px;">🗑</button>`
  )).join("");

  const bandRows = (cw.bands || []).map((b, bi) => {
    const isCond = b.mode === "cond_vol_cap";
    return `<div style="border:1px dashed #cbd5e1;border-radius:8px;padding:8px;margin-bottom:6px;" data-row="band">` +
      crRow(
        crNumField("band.max_sum", "三边和上限(空=兜底)", b.max_sum, "160") +
        crSelField("band.cmp", "比较", b.cmp || "lte", CR_CMP, "82px") +
        crSelField("band.mode", "模式", b.mode, CR_MODE, "150px") +
        `<div data-cond="${isCond ? 1 : 0}" style="display:${isCond ? "flex" : "none"};gap:6px;align-items:flex-end;flex-wrap:wrap;">` +
        crNumField("band.ref_vol_ratio", "条件体积÷", b.ref_vol_ratio, "6000") +
        crNumField("band.cap", "封顶cap(kg)", b.cap, "120") +
        crSelField("band.if_true", "满足→", b.if_true || "actual", CR_ACT, "82px") +
        crSelField("band.if_false", "否则→", b.if_false || "avg", CR_ACT, "82px") +
        `</div>` +
        `<button type="button" class="btn btn-outline btn-sm" data-act="del-band" data-ci="${ci}" data-bi="${bi}" style="margin-bottom:2px;">🗑</button>`
      ) + `</div>`;
  }).join("");

  const isFC = p.type === "first_continue";
  const tierRows = (p.tiers || []).map((t, ti) => `<div style="border:1px dashed #cbd5e1;border-radius:8px;padding:8px;margin-bottom:6px;" data-row="tier">` +
    crRow(
      crNumField("tier.max_cw", "计费重上限(空=兜底)", t.max_cw, "2") +
      crSelField("tier.cmp", "比较", t.cmp || "lte", CR_CMP, "82px") +
      crNumField("tier.base", "首费base", t.base, "38") +
      crNumField("tier.step", "步长step", t.step, "8") +
      crNumField("tier.rate", "单价rate", t.rate, "15") +
      crNumField("tier.min_charge", "最低计费重", t.min_charge, "20") +
      `<button type="button" class="btn btn-outline btn-sm" data-act="del-tier" data-ci="${ci}" data-ti="${ti}" style="margin-bottom:2px;">🗑</button>`
    ) + `</div>`).join("");

  const sgRows = (rule.surcharges || []).length ? (rule.surcharges || []).map((g, gi) => {
    const items = (g.items || []).map((item, ii) => {
      const sgt = (item.tiers || []).map((t, k) => crRow(
        crNumField("sgt.min", "值>", t.min, "159") +
        crNumField("sgt.fee", "加价", t.fee, "80") +
        `<button type="button" class="btn btn-outline btn-sm" data-act="del-sgtier" data-ci="${ci}" data-gi="${gi}" data-ii="${ii}" data-k="${k}" style="margin-bottom:2px;">🗑</button>`
      )).join("");
      return `<div style="border:1px dashed #cbd5e1;border-radius:8px;padding:8px;margin-bottom:6px;background:#fff;" data-row="sgitem">` +
        crRow(
          crSelField("sgi.basis", "依据", item.basis || "sum_sides", CR_BASIS, "100px") +
          crNumField("sgi.cw_below", "仅计费重<(空=不限)", item.cw_below, "300") +
          `<button type="button" class="btn btn-outline btn-sm" data-act="add-sgtier" data-ci="${ci}" data-gi="${gi}" data-ii="${ii}" style="margin-bottom:2px;">➕ 阶梯</button>` +
          `<button type="button" class="btn btn-outline btn-sm" data-act="del-item" data-ci="${ci}" data-gi="${gi}" data-ii="${ii}" style="margin-bottom:2px;">🗑</button>`
        ) + sgt + `</div>`;
    }).join("");
    return `<div style="border:1px solid #e2e8f0;border-radius:8px;padding:8px;margin-bottom:6px;background:#f8fafc;" data-row="sg">` +
      crRow(
        crSelField("sg.pick", "组内多条件", g.pick || "add", CR_PICK, "110px") +
        `<button type="button" class="btn btn-outline btn-sm" data-act="add-item" data-ci="${ci}" data-gi="${gi}" style="margin-bottom:2px;">➕ 条件</button>` +
        `<button type="button" class="btn btn-outline btn-sm" data-act="del-sg" data-ci="${ci}" data-gi="${gi}" style="margin-bottom:2px;">🗑 删组</button>`
      ) + items + `</div>`;
  }).join("") : `<div style="font-size:.78rem;color:#94a3b8;margin-bottom:6px;">无附加费</div>`;

  return `<div class="cr-card" data-ci="${ci}" style="border:1px solid #e2e8f0;border-radius:10px;margin-bottom:12px;background:#fff;overflow:hidden;">
    <div style="display:flex;gap:10px;align-items:center;padding:10px 14px;background:#f8fafc;border-bottom:1px solid #e2e8f0;flex-wrap:wrap;">
      <b style="font-size:.86rem;color:#64748b;">#${ci + 1}</b>
      <input data-f="name" value="${crEsc(rule.name)}" placeholder="渠道名称" style="width:150px;padding:6px 9px;border:1px solid #cbd5e1;border-radius:6px;font-weight:700;font-size:.86rem;">
      <input type="hidden" data-f="key" value="${crEsc(rule.key || ("ch_" + (ci + 1)))}">
      <label style="font-size:.8rem;display:flex;align-items:center;gap:4px;cursor:pointer;">
        <input type="checkbox" data-f="enabled" ${rule.enabled === false ? "" : "checked"}> 启用
      </label>
      <span style="flex:1;"></span>
      <button type="button" class="btn btn-outline btn-sm" data-act="del-ch" data-ci="${ci}">🗑 删除</button>
      <button type="button" class="btn btn-outline btn-sm" data-act="toggle" data-ci="${ci}">${open ? "▴ 收起" : "▾ 展开"}</button>
    </div>
    <div data-cb="${ci}" style="display:${open ? "block" : "none"};padding:6px 14px 14px;">
      ${crSecTitle("可收货限制 (留空=不限)")}
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
        ${crNumField("limits.max_weight", "实重≤ (kg)", lim.max_weight, "30")}
        ${crNumField("limits.max_single_side", "最长边≤ (cm)", lim.max_single_side, "120")}
        ${crNumField("limits.max_sum_sides", "三边和≤ (cm)", lim.max_sum_sides, "160")}
        ${crNumField("limits.max_cw", "计费重≤ (kg)", lim.max_cw, "900")}
        ${crNumField("limits.max_length", "长≤ (cm)", lim.max_length, "305")}
        ${crNumField("limits.max_width", "宽≤ (cm)", lim.max_width, "175")}
        ${crNumField("limits.max_height", "高≤ (cm)", lim.max_height, "155")}
        ${crNumField("limits.max_combined_girth", "长+2×(宽+高)≤", lim.max_combined_girth, "330")}
      </div>
      <div style="margin-top:6px;">
        <div style="font-size:.74rem;color:#64748b;margin-bottom:4px;">拒收规则: 中边与最小边同时超限则拒收 (顺丰大件)</div>
        ${rboRows}
        <button type="button" class="btn btn-outline btn-sm" data-act="add-rbo" data-ci="${ci}">➕ 拒收规则</button>
      </div>
      ${crSecTitle("计费重")}
      ${crRow(
        crNumField("cw.vol_ratio", "体积重÷ (空=不计)", cw.vol_ratio, "6000") +
        crSelField("cw.round_to", "进位", cw.round_to === null || cw.round_to === undefined ? "" : cw.round_to, CR_RTO, "110px") +
        crNumField("cw.min_cw", "最低计费重(kg)", cw.min_cw, "20")
      )}
      <div style="margin-top:6px;">${bandRows}
        <button type="button" class="btn btn-outline btn-sm" data-act="add-band" data-ci="${ci}">➕ 分段</button>
      </div>
      ${crSecTitle("运费价格")}
      ${crRow(
        crSelField("p.type", "价格类型", p.type || "tiered_step", CR_PTYPE, "130px") +
        `<div data-ptier="${isFC ? 0 : 1}" style="display:${isFC ? "none" : "block"};flex:1;min-width:90px;">${crNumField("p.step_unit", "递增单位kg", p.step_unit, "0.5")}</div>` +
        crNumField("p.op_fee", "固定操作费", p.op_fee, "20") +
        crNumField("p.discount", "折扣乘数(0.8=8折)", p.discount, "0.8") +
        crSelField("p.round_total", "总价取整", p.round_total === null || p.round_total === undefined ? "" : p.round_total, CR_RT, "120px")
      )}
      <div data-showif="tiered" style="display:${isFC ? "none" : "block"};margin-top:6px;">
        ${tierRows}
        <button type="button" class="btn btn-outline btn-sm" data-act="add-tier" data-ci="${ci}">➕ 费率档</button>
      </div>
      <div data-showif="fc" style="display:${isFC ? "flex" : "none"};gap:6px;align-items:flex-end;flex-wrap:wrap;margin-top:6px;">
        ${crNumField("p.first_weight_fee", "首重费(1kg起)", p.first_weight_fee, "124.2") +
          crNumField("p.continue_per_kg", "续重/公斤", p.continue_per_kg, "29.6") +
          crNumField("p.extra_fee", "操作费", p.extra_fee, "8")}
      </div>
      ${crSecTitle("附加费 (各组相加; 组内按 pick 合并; 阶梯取 值>min 的最大档)")}
      ${sgRows}
      <button type="button" class="btn btn-outline btn-sm" data-act="add-sg" data-ci="${ci}">➕ 附加费组</button>
    </div>
  </div>`;
}

function renderChannelRules(fromWorking) {
  const list = document.getElementById("channelRulesList");
  if (!list) return;
  if (!fromWorking) {
    crWorking = (Array.isArray(settingsState.channelRules) && settingsState.channelRules.length)
      ? JSON.parse(JSON.stringify(settingsState.channelRules))
      : crDefaults();
  }
  if (!Array.isArray(crWorking) || !crWorking.length) crWorking = crDefaults();
  list.innerHTML = crWorking.map(renderChannelCard).join("");
}

function crRowVal(scope, f) {
  const el = scope.querySelector(`[data-f="${f}"]`);
  return el ? el.value : "";
}

function crRowNum(scope, f) {
  const v = crRowVal(scope, f).trim();
  if (v === "") return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

/** 从 DOM 收集全部渠道规则 (数字空串→null); 保存与结构性操作共用 */
function collectChannelRules() {
  const list = document.getElementById("channelRulesList");
  if (!list) return null;
  const rules = [];
  list.querySelectorAll(".cr-card").forEach((card, ci) => {
    const qv = (f) => crRowVal(card, f);
    const qn = (f) => crRowNum(card, f);
    const qchk = (f) => { const el = card.querySelector(`[data-f="${f}"]`); return el ? !!el.checked : true; };
    const ptype = qv("p.type") || "tiered_step";
    const rule = {
      key: (qv("key") || ("ch_" + (ci + 1))).trim(),
      name: (qv("name") || ("渠道" + (ci + 1))).trim(),
      enabled: qchk("enabled"),
      limits: {
        max_weight: qn("limits.max_weight"),
        max_single_side: qn("limits.max_single_side"),
        max_sum_sides: qn("limits.max_sum_sides"),
        max_length: qn("limits.max_length"),
        max_width: qn("limits.max_width"),
        max_height: qn("limits.max_height"),
        max_combined_girth: qn("limits.max_combined_girth"),
        max_cw: qn("limits.max_cw"),
        reject_both_over: []
      },
      charge_weight: {
        vol_ratio: qn("cw.vol_ratio"),
        round_to: qn("cw.round_to"),
        min_cw: qn("cw.min_cw"),
        bands: []
      },
      pricing: {
        type: ptype, step_unit: null, tiers: [],
        first_weight_fee: null, continue_per_kg: null, extra_fee: null,
        op_fee: qn("p.op_fee"), discount: qn("p.discount")
      },
      surcharges: [],
      round_total: qv("p.round_total") || null
    };
    card.querySelectorAll('[data-row="rbo"]').forEach((row) => {
      const g = { mid: crRowNum(row, "rbo.mid"), min: crRowNum(row, "rbo.min") };
      if (g.mid !== null || g.min !== null) rule.limits.reject_both_over.push(g);
    });
    card.querySelectorAll('[data-row="band"]').forEach((row) => {
      const b = {
        max_sum: crRowNum(row, "band.max_sum"),
        cmp: crRowVal(row, "band.cmp") || "lte",
        mode: crRowVal(row, "band.mode") || "actual"
      };
      if (b.mode === "cond_vol_cap") {
        b.ref_vol_ratio = crRowNum(row, "band.ref_vol_ratio");
        b.cap = crRowNum(row, "band.cap");
        b.if_true = crRowVal(row, "band.if_true") || "actual";
        b.if_false = crRowVal(row, "band.if_false") || "avg";
      }
      rule.charge_weight.bands.push(b);
    });
    if (ptype === "first_continue") {
      rule.pricing.first_weight_fee = qn("p.first_weight_fee");
      rule.pricing.continue_per_kg = qn("p.continue_per_kg");
      rule.pricing.extra_fee = qn("p.extra_fee");
    } else {
      rule.pricing.step_unit = qn("p.step_unit");
      card.querySelectorAll('[data-row="tier"]').forEach((row) => {
        rule.pricing.tiers.push({
          max_cw: crRowNum(row, "tier.max_cw"),
          cmp: crRowVal(row, "tier.cmp") || "lte",
          base: crRowNum(row, "tier.base"),
          step: crRowNum(row, "tier.step"),
          rate: crRowNum(row, "tier.rate"),
          min_charge: crRowNum(row, "tier.min_charge")
        });
      });
    }
    card.querySelectorAll('[data-row="sg"]').forEach((gEl) => {
      const grp = { pick: crRowVal(gEl, "sg.pick") || "add", items: [] };
      gEl.querySelectorAll('[data-row="sgitem"]').forEach((iEl) => {
        const item = {
          basis: crRowVal(iEl, "sgi.basis") || "sum_sides",
          cw_below: crRowNum(iEl, "sgi.cw_below"),
          tiers: []
        };
        iEl.querySelectorAll('[data-row="sgtier"]').forEach((tEl) => {
          item.tiers.push({ min: crRowNum(tEl, "sgt.min"), fee: crRowNum(tEl, "sgt.fee") });
        });
        grp.items.push(item);
      });
      rule.surcharges.push(grp);
    });
    rules.push(rule);
  });
  return rules;
}

function addChannelRule() {
  const rules = collectChannelRules() || [];
  rules.push({
    key: "ch_new_" + Date.now(), name: "新渠道", enabled: true,
    limits: { max_weight: null, max_single_side: null, max_sum_sides: null, max_length: null, max_width: null, max_height: null, max_combined_girth: null, max_cw: null, reject_both_over: [] },
    charge_weight: { vol_ratio: null, round_to: null, min_cw: null, bands: [{ max_sum: null, cmp: "lte", mode: "actual" }] },
    pricing: { type: "tiered_step", step_unit: 0.5, tiers: [{ max_cw: null, cmp: "lte", base: null, step: null, rate: null, min_charge: null }], first_weight_fee: null, continue_per_kg: null, extra_fee: null, op_fee: 0, discount: null },
    surcharges: [], round_total: null
  });
  crWorking = rules;
  crOpen[rules.length - 1] = true;
  renderChannelRules(true);
  const listEl = document.getElementById("channelRulesList");
  if (listEl) listEl.lastElementChild && listEl.lastElementChild.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetChannelRules() {
  if (!confirm("确定恢复默认渠道计费标准吗？\n当前自定义配置将被清除 (需保存后生效)。")) return;
  crResetPending = true;
  settingsState.channelRules = null;
  saveSettings();
}

function initChannelRulesEditor() {
  const list = document.getElementById("channelRulesList");
  if (!list || list.dataset.crInit === "1") return;
  list.dataset.crInit = "1";

  list.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    const ci = parseInt(btn.dataset.ci);

    if (act === "toggle") {
      crOpen[ci] = !crOpen[ci];
      const body = list.querySelector(`[data-cb="${ci}"]`);
      if (body) body.style.display = crOpen[ci] ? "block" : "none";
      btn.textContent = crOpen[ci] ? "▴ 收起" : "▾ 展开";
      return;
    }

    // 结构性操作: 先收集 DOM → 修改 → 重渲染 (保证未保存编辑不丢失)
    const rules = collectChannelRules() || [];
    const rule = rules[ci];
    if (!rule) return;

    if (act === "del-ch") {
      if (!confirm(`确定删除渠道「${rule.name}」吗？`)) return;
      rules.splice(ci, 1);
    } else if (act === "add-rbo") {
      rule.limits.reject_both_over.push({ mid: null, min: null });
    } else if (act === "del-rbo") {
      rule.limits.reject_both_over.splice(parseInt(btn.dataset.ri), 1);
    } else if (act === "add-band") {
      rule.charge_weight.bands.push({ max_sum: null, cmp: "lte", mode: "actual" });
    } else if (act === "del-band") {
      rule.charge_weight.bands.splice(parseInt(btn.dataset.bi), 1);
    } else if (act === "add-tier") {
      rule.pricing.tiers.push({ max_cw: null, cmp: "lte", base: null, step: null, rate: null, min_charge: null });
    } else if (act === "del-tier") {
      rule.pricing.tiers.splice(parseInt(btn.dataset.ti), 1);
    } else if (act === "add-sg") {
      rule.surcharges.push({ pick: "add", items: [{ basis: "sum_sides", cw_below: null, tiers: [] }] });
    } else if (act === "del-sg") {
      rule.surcharges.splice(parseInt(btn.dataset.gi), 1);
    } else if (act === "add-item") {
      rule.surcharges[parseInt(btn.dataset.gi)].items.push({ basis: "sum_sides", cw_below: null, tiers: [] });
    } else if (act === "del-item") {
      rule.surcharges[parseInt(btn.dataset.gi)].items.splice(parseInt(btn.dataset.ii), 1);
    } else if (act === "add-sgtier") {
      rule.surcharges[parseInt(btn.dataset.gi)].items[parseInt(btn.dataset.ii)].tiers.push({ min: null, fee: null });
    } else if (act === "del-sgtier") {
      rule.surcharges[parseInt(btn.dataset.gi)].items[parseInt(btn.dataset.ii)].tiers.splice(parseInt(btn.dataset.k), 1);
    } else {
      return;
    }

    crWorking = rules;
    crOpen[ci] = true;
    renderChannelRules(true);
  });

  list.addEventListener("change", (e) => {
    const f = e.target.getAttribute && e.target.getAttribute("data-f");
    if (!f) return;
    if (f === "band.mode") {
      const row = e.target.closest('[data-row="band"]');
      const cond = row && row.querySelector("[data-cond]");
      if (cond) cond.style.display = e.target.value === "cond_vol_cap" ? "flex" : "none";
    } else if (f === "p.type") {
      const card = e.target.closest(".cr-card");
      if (!card) return;
      const isFC = e.target.value === "first_continue";
      const t = card.querySelector('[data-showif="tiered"]');
      if (t) t.style.display = isFC ? "none" : "block";
      const f2 = card.querySelector('[data-showif="fc"]');
      if (f2) f2.style.display = isFC ? "flex" : "none";
      const pt = card.querySelector("[data-ptier]");
      if (pt) pt.style.display = isFC ? "none" : "block";
    }
  });
}
