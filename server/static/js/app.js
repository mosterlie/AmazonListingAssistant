/**
 * Product Management Dashboard - Interactive Frontend Logic
 * 集成产品信息、产品主图/附图图库、Amazon 核心产品属性、EAN-13 智能条码、Calcfee 物流比价与动态售价联动
 */

const state = {
  productMainImage: "",
  productExtraImages: [],
  colorInputs: ["", "", "", "", ""],
  sizeInputs: ["", "", "", "", ""],
  imageDimension: "color", // "color" 或 "size"
  colorImages: {}, // 颜色与图片的映射关系
  sizeImages: {},  // 尺寸与图片的映射关系
  pricingConfig: {
    tax_rate: 0.17,
    exchange_rate: 23.0,
    price_coefficient: 26.0,
    default_profit_coeff: 1.0
  },
  aiConfig: {
    generate_bullets_enabled: false,
    bullets_source: "public"
  },
  variations: []
};
window.state = state;
let editingProductId = null;
window.editingProductId = null;

// ============================================================================
// Helper Functions & Global Floating Tooltip
// ============================================================================
function showToast(msg, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast-msg toast-${type}`;
  toast.innerText = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

/**
 * 动态加载系统配置（店铺账号下拉列表与 Calcfee 核心参数）
 */
async function loadSystemSettings() {
  try {
    const res = await fetch("/api/settings");
    const result = await res.json();
    if (result.code === 0 && result.data) {
      if (result.data.pricing_config) {
        state.pricingConfig = { ...state.pricingConfig, ...result.data.pricing_config };
        const batchProfitInp = document.getElementById("batchProfitCoeffInput");
        if (batchProfitInp && (!batchProfitInp.value || batchProfitInp.value === "1.0")) {
          batchProfitInp.value = state.pricingConfig.default_profit_coeff || 1.0;
        }
      }
      if (result.data.ai_config) {
        state.aiConfig = { ...state.aiConfig, ...result.data.ai_config };
      }
      if (result.data.store_accounts && Array.isArray(result.data.store_accounts)) {
        const storeSel = document.getElementById("storeAccountSelect");
        if (storeSel) {
          const defaultStore = result.data.store_accounts.find(st => typeof st === "object" && st.is_default) || result.data.store_accounts[0];
          const defaultStoreName = defaultStore ? (typeof defaultStore === "string" ? defaultStore : (defaultStore.store_name || defaultStore.store)) : "";

          storeSel.innerHTML = result.data.store_accounts.map((st, idx) => {
            const sName = typeof st === "string" ? st : (st.store_name || st.store || "");
            const bName = typeof st === "string" ? st : (st.brand_name || st.brand || sName);
            const isDef = (typeof st === "object" && st.is_default) || (idx === 0 && !result.data.store_accounts.some(x => x.is_default));

            // 新增商品模式：必须严格默认选中设定的默认店铺
            // 编辑商品模式：先保留占位，稍后由 loadProductForEdit() 精准回填
            const isSelected = (!editingProductId && isDef);
            const labelSuffix = isDef ? " ⭐[默认]" : "";
            return `<option value="${sName}" data-brand="${bName}" data-default="${isDef ? 'true' : 'false'}" ${isSelected ? "selected" : ""}>${sName}${labelSuffix}</option>`;
          }).join("");

          // 在新建模式下明确设置 value 确保 select 控件立即处于选中状态
          if (!editingProductId && defaultStoreName) {
            storeSel.value = defaultStoreName;
          }

          // 绑定切换店铺事件监听
          storeSel.onchange = onStoreAccountChanged;
          // 初次加载：若为新建模式触发自动带入品牌、Parent SKU、型号；若为编辑模式则由已有数据回填
          if (!editingProductId) {
            await onStoreAccountChanged();
          }
        }
      }
    }
  } catch (err) {
    console.error("加载系统配置失败:", err);
  }
}

/**
 * 当店铺切换时：
 * 1. 自动带入品牌 (1对1)
 * 2. 自动填入品番・型番 = 品牌
 * 3. 请求接口自动生成 Parent SKU (用户名+第几个品) 和 モデル名 (品牌+该品牌第几个品)
 */
async function onStoreAccountChanged() {
  if (window.isLoadingProductForEdit) return;
  const storeSel = document.getElementById("storeAccountSelect");
  const brandInp = document.getElementById("brandInput");
  const modelNumInp = document.getElementById("modelNumberInput");
  const modelNameInp = document.getElementById("modelNameInput");
  const parentSkuInp = document.getElementById("parentSkuInput");
  if (!storeSel) return;

  const selectedOpt = storeSel.options[storeSel.selectedIndex];
  const brandName = selectedOpt?.getAttribute("data-brand") || selectedOpt?.value || "";

  if (brandInp) brandInp.value = brandName;
  if (modelNumInp) modelNumInp.value = brandName;

  try {
    const res = await fetch(`/api/products/seq-numbers?brand=${encodeURIComponent(brandName)}`);
    const result = await res.json();
    if (result.code === 0 && result.data) {
      const baseSku = result.data.parent_sku || "";
      window.autoParentSkuBase = baseSku;
      if (parentSkuInp) {
        const rawTrans = (document.getElementById("identifierTranslationInput")?.value || "").trim();
        const newP = computeParentSkuWithTranslation(baseSku, rawTrans);
        const oldP = window.lastParentSkuValue || parentSkuInp.value.trim();
        parentSkuInp.value = newP;
        const baseSkuInp = document.getElementById("baseSkuInput");
        if (baseSkuInp) baseSkuInp.value = newP;
        window.lastParentSkuValue = newP;
        if (oldP && oldP !== newP) {
          syncChildSkusWithParent(oldP, newP);
        }
      }
      if (modelNameInp) modelNameInp.value = result.data.model_name || (brandName ? `${brandName}1` : "");
      if (modelNumInp && !modelNumInp.value) modelNumInp.value = result.data.model_number || brandName;
    }
  } catch (e) {
    console.error("获取自动序列号异常:", e);
  }
}

/**
 * 根据商品标识英文翻译计算最新的父 SKU:
 * 规则:
 * 1. 如果父 SKU 存在 "-", 则取第一个 "-" 前部分的内容与 "-英文翻译" 做拼接；
 * 2. 如果父 SKU 不存在 "-", 则直接用父 SKU 与 "-英文翻译" 做拼接。
 *
 * 示例:
 * 1. 父sku: admin, 英文翻译: table -> 拼接结果: admin-table
 * 2. 父sku: admin-hello, 英文翻译: table -> 拼接结果: admin-table
 * 3. 父sku: admin-hello-123, 英文翻译: table -> 拼接结果: admin-table
 * 4. 父sku: admin--hello--123, 英文翻译: table -> 拼接结果: admin-table
 */
function computeParentSkuWithTranslation(currentParentSku, rawTranslation) {
  const trans = (rawTranslation || "").trim().replace(/\s+/g, "");
  const curParent = (currentParentSku || "").trim();

  // 若当前父 SKU 为空，回退全局自动前缀或直接使用翻译
  if (!curParent) {
    const baseFallback = (window.autoParentSkuBase || "").trim();
    if (baseFallback) {
      return trans ? `${baseFallback}-${trans.replace(/^-+/, "")}` : baseFallback;
    }
    return trans ? trans.replace(/^-+/, "") : "";
  }

  // 判断是否存在 "-"
  let prefix = curParent;
  const firstDashIdx = curParent.indexOf("-");
  if (firstDashIdx !== -1) {
    // 存在 -，取第一个 - 前部分的内容
    prefix = curParent.slice(0, firstDashIdx);
  }

  prefix = prefix.trim();

  // 若英文翻译为空，则仅保留前缀部分 (如原 admin-table 清空翻译后回退为 admin)
  if (!trans) {
    return prefix;
  }

  // 确保清洗翻译前导的短横线，避免生成类似 admin--table 的双横线
  const cleanTrans = trans.replace(/^-+/, "");

  if (!prefix) {
    return cleanTrans;
  }

  return `${prefix}-${cleanTrans}`;
}

/**
 * 监听 Parent SKU 与 商品标识翻译联动:
 * 1. 允许自由手动修改父 SKU (卡片 2 或卡片 7 SKU前缀)，修改后实时联动修改所有子 SKU 并双向同步
 * 2. 商品标识英文翻译变更时，根据首个 "-" 截取前缀或直接拼接 "-英文翻译"，并联动修改子 SKU
 */
function bindIdentifierToParentSku() {
  const idTransInp = document.getElementById("identifierTranslationInput");
  const parentSkuInp = document.getElementById("parentSkuInput");
  const baseSkuInp = document.getElementById("baseSkuInput");

  // 记录初始父 SKU 值
  window.lastParentSkuValue = (parentSkuInp?.value || baseSkuInp?.value || "").trim();

  // 1. 商品标识英文翻译变更 -> 联动更新父 SKU -> 联动更新所有子 SKU 与 baseSkuInput
  if (idTransInp) {
    const updateParentSkuFromTranslation = () => {
      if (window.isLoadingProductForEdit) return;

      const rawTrans = idTransInp.value;
      const currentParent = (parentSkuInp?.value || baseSkuInp?.value || window.lastParentSkuValue || "").trim();
      const oldParent = window.lastParentSkuValue || currentParent;

      const newSku = computeParentSkuWithTranslation(currentParent, rawTrans);

      if (newSku !== oldParent) {
        if (parentSkuInp) parentSkuInp.value = newSku;
        if (baseSkuInp) baseSkuInp.value = newSku;
        syncChildSkusWithParent(oldParent, newSku);
        window.lastParentSkuValue = newSku;
      }
    };

    idTransInp.addEventListener("input", updateParentSkuFromTranslation);
    idTransInp.addEventListener("change", updateParentSkuFromTranslation);
  }

  // 2. 卡片 2 父 SKU (Parent SKU) 允许手动修改，修改后实时联动修改所有子 SKU 与 baseSkuInput
  if (parentSkuInp) {
    const handleParentSkuManualChange = () => {
      if (window.isLoadingProductForEdit) return;
      const curVal = parentSkuInp.value.trim();
      const oldVal = window.lastParentSkuValue || "";

      if (curVal !== oldVal) {
        if (baseSkuInp && baseSkuInp.value !== curVal) {
          baseSkuInp.value = curVal;
        }
        syncChildSkusWithParent(oldVal, curVal);
        window.lastParentSkuValue = curVal;
      }
    };

    parentSkuInp.addEventListener("input", handleParentSkuManualChange);
    parentSkuInp.addEventListener("change", handleParentSkuManualChange);
  }

  // 3. 卡片 7 SKU 前缀 (baseSkuInput) 双向实时联动更新父 SKU 与所有子 SKU
  if (baseSkuInp) {
    const handleBaseSkuManualChange = () => {
      if (window.isLoadingProductForEdit) return;
      const curVal = baseSkuInp.value.trim();
      const oldVal = window.lastParentSkuValue || parentSkuInp?.value.trim() || "";

      if (curVal !== oldVal) {
        if (parentSkuInp && parentSkuInp.value !== curVal) {
          parentSkuInp.value = curVal;
        }
        syncChildSkusWithParent(oldVal, curVal);
        window.lastParentSkuValue = curVal;
      }
    };

    baseSkuInp.addEventListener("input", handleBaseSkuManualChange);
    baseSkuInp.addEventListener("change", handleBaseSkuManualChange);
  }
}

/**
 * 父 SKU 变更时, 联动同步刷新所有子 SKU
 * 规则: 子 SKU = 父 SKU + "-" + 序号 (如 admin25-DogToilet-01、admin25-DogToilet-02...)
 * 特性:
 * 1. 自动去除多余横杠，防止出现双横杠 (如 admin--01)
 * 2. 完美支持序号提取或按变体行序号 (01、02...) 重建
 * 3. 同步平滑就地刷新所有变体表格中的 .sku-inp 输入框 (不丢失光标与输入焦点)
 * 4. 同步更新 parentSkuInput 与 baseSkuInput 两处输入框及缓存
 */
function syncChildSkusWithParent(oldParent, newParent) {
  if (!state.variations || state.variations.length === 0) return;
  const rawNewP = (newParent || "").trim();
  const rawOldP = (oldParent || "").trim();
  // 去除尾部多余的横线，便于拼接规范的 -01 序号
  const cleanNewP = rawNewP.replace(/-+$/, "");
  const cleanOldP = rawOldP.replace(/-+$/, "");
  const seqWidth = state.variations.length >= 100 ? 3 : 2;

  let changed = false;
  state.variations.forEach((v, idx) => {
    const curSku = (v.sku || "").trim();
    const defaultSeq = String(idx + 1).padStart(seqWidth, "0");
    let suffix = "";

    // 优先从旧父 SKU 中剥离原有后缀 (如 -01 或 -Red-01)
    if (cleanOldP && curSku.startsWith(cleanOldP)) {
      suffix = curSku.slice(cleanOldP.length).replace(/^-+/, "");
    }
    // 若未能剥离，则尝试正则提取末尾序号 (-01、-001 等)
    if (!suffix) {
      const match = curSku.match(/-(\d{2,})$/);
      if (match) {
        suffix = match[1];
      }
    }
    // 默认回退为当前变体行固有序列号 (01, 02...)
    if (!suffix) {
      suffix = defaultSeq;
    }

    // 拼装全新子 SKU
    const newChildSku = cleanNewP ? `${cleanNewP}-${suffix}` : `-${suffix}`;

    if (v.sku !== newChildSku) {
      v.sku = newChildSku;
      v.sku_manual = false;
      changed = true;
    }
  });

  if (changed) {
    // 平滑就地更新表格中的 .sku-inp 元素与相关属性，保持用户焦点不丢失
    const skuInputs = document.querySelectorAll(".sku-inp");
    if (skuInputs && skuInputs.length === state.variations.length) {
      skuInputs.forEach((inp, idx) => {
        inp.value = state.variations[idx].sku;
        inp.setAttribute("value", state.variations[idx].sku);
        inp.title = state.variations[idx].sku;
      });
    } else {
      renderMatrixTable();
    }
  }

  // 保证两处输入框与全局缓存始终与最新父 SKU 保持完全一致
  const parentSkuInp = document.getElementById("parentSkuInput");
  const baseSkuInp = document.getElementById("baseSkuInput");
  if (parentSkuInp && parentSkuInp.value !== rawNewP) {
    parentSkuInp.value = rawNewP;
  }
  if (baseSkuInp && baseSkuInp.value !== rawNewP) {
    baseSkuInp.value = rawNewP;
  }
  window.lastParentSkuValue = rawNewP;
}

/**
 * 全局浮动 Tooltip 气泡框 (Popper 机制，直接挂载于 body，绝不破坏表格排版)
 */
let globalTooltipEl = null;

function initGlobalTooltip() {
  if (!globalTooltipEl) {
    globalTooltipEl = document.createElement("div");
    globalTooltipEl.id = "globalSkuTooltip";
    globalTooltipEl.style.cssText = `
      position: fixed;
      background: #0f172a;
      color: #ffffff;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-family: monospace;
      font-weight: 600;
      white-space: nowrap;
      pointer-events: none;
      z-index: 999999;
      box-shadow: 0 6px 16px rgba(0,0,0,0.35);
      border: 1px solid #334155;
      display: none;
      transition: opacity 0.1s ease;
      transform: translate(-50%, -100%);
    `;
    document.body.appendChild(globalTooltipEl);
  }
}

function showSkuTooltip(e, text) {
  if (!text) return;
  initGlobalTooltip();
  const rect = e.target.getBoundingClientRect();
  globalTooltipEl.innerText = text;
  globalTooltipEl.style.left = `${rect.left + rect.width / 2}px`;
  globalTooltipEl.style.top = `${rect.top - 8}px`;
  globalTooltipEl.style.display = "block";
  globalTooltipEl.style.opacity = "1";
}

function hideSkuTooltip() {
  if (globalTooltipEl) {
    globalTooltipEl.style.display = "none";
  }
}

function showChannelTooltip(e, selectEl) {
  if (!selectEl) return;
  const selectedOption = selectEl.options[selectEl.selectedIndex];
  if (selectedOption && selectedOption.value) {
    showSkuTooltip(e, selectedOption.innerText.trim());
  }
}

/**
 * 将本地绝对路径或相对路径转换为可在浏览器 <img> 中正常显示的静态 URL
 */
function getImagePreviewUrl(path) {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `/api/images/preview?path=${encodeURIComponent(path)}`;
}

// ============================================================================
// Product Main & Extra Gallery Images Management (产品主图与 8 张附图)
// ============================================================================
let currentProductImgTargetSlot = null;

function triggerProductImgUpload(slotIdx) {
  currentProductImgTargetSlot = slotIdx;
  currentUploadTargetIdx = null;
  currentAttrUploadKey = null;
  const fileInput = document.getElementById("globalFileInput");
  if (!fileInput) return;
  fileInput.multiple = false;
  fileInput.click();
}

function triggerExtraMultiUpload() {
  const inp = document.getElementById("batchExtraFileInput");
  if (inp) {
    inp.value = "";
    inp.click();
  }
}

function removeExtraImgByIndex(idx) {
  const validExtra = state.productExtraImages.filter(Boolean);
  validExtra.splice(idx, 1);
  state.productExtraImages = validExtra;
  renderProductGallery();
  showToast("已删除附图");
}

function clearAllExtraImages() {
  if (confirm("确定要清空所有已上传的产品附图吗？")) {
    state.productExtraImages = [];
    renderProductGallery();
    showToast("已清空所有产品附图");
  }
}

async function handleBatchExtraFileSelect(e) {
  const files = e.target.files;
  if (!files || files.length === 0) return;

  const validExtra = state.productExtraImages.filter(Boolean);
  const remainingSlots = 8 - validExtra.length;
  if (remainingSlots <= 0) {
    showToast("附图已达到 8 张上限，无法再添加！", "error");
    e.target.value = "";
    return;
  }

  const formData = new FormData();
  const uploadCount = Math.min(files.length, remainingSlots);
  for (let i = 0; i < uploadCount; i++) {
    formData.append("files", files[i]);
  }

  try {
    showToast(`正在上传 ${uploadCount} 张附图...`);
    const res = await fetch("/api/upload/multiple", { method: "POST", body: formData });
    const data = await res.json();
    if (data.code === 0 && Array.isArray(data.data)) {
      const currentValid = state.productExtraImages.filter(Boolean);
      data.data.forEach(item => {
        if (currentValid.length < 8) {
          currentValid.push(item.absolute_path);
        }
      });
      state.productExtraImages = currentValid;
      renderProductGallery();
      showToast(`🎉 成功上传 ${data.data.length} 张附图！`);
    } else {
      showToast(`上传失败: ${data.msg || "接口异常"}`, "error");
    }
  } catch (err) {
    showToast(`上传异常: ${err.message}`, "error");
  }

  e.target.value = "";
}

function removeProductImg(e, slotIdx) {
  e.stopPropagation();
  if (slotIdx === 0) {
    state.productMainImage = "";
    showToast("已清除产品主图");
  } else {
    const validExtra = state.productExtraImages.filter(Boolean);
    validExtra.splice(slotIdx - 1, 1);
    state.productExtraImages = validExtra;
    showToast(`已删除附图 ${slotIdx}`);
  }
  renderProductGallery();
}

function renderProductGallery() {
  // 1. 主图
  const mainSlot = document.getElementById("mainProductImgSlot");
  if (mainSlot) {
    if (state.productMainImage) {
      mainSlot.innerHTML = `
        <img src="${getImagePreviewUrl(state.productMainImage)}">
        <span class="img-slot-del" onclick="removeProductImg(event, 0)">&times;</span>
      `;
    } else {
      mainSlot.innerHTML = `
        <span style="font-size:1.4rem;">📷</span>
        <span class="img-slot-label" style="font-size:10px; color:#1d4ed8; font-weight:700;">点击上传主图</span>
      `;
    }
  }

  // 2. 附图列表与唯一的上传附图按钮
  const galleryList = document.getElementById("extraImagesGalleryList");
  const countBadge = document.getElementById("extraImgCountBadge");
  const clearBtn = document.getElementById("clearAllExtraBtn");

  const validExtra = state.productExtraImages.filter(Boolean);
  state.productExtraImages = validExtra;

  if (countBadge) countBadge.innerText = `已上传 ${validExtra.length}/8 张`;
  if (clearBtn) clearBtn.style.display = validExtra.length > 0 ? "inline-block" : "none";

  if (galleryList) {
    let html = "";
    // 已上传附图卡片
    validExtra.forEach((imgPath, idx) => {
      html += `
        <div class="gallery-item-wrapper" style="text-align:center;">
          <div class="img-slot" style="width:78px; height:78px; background:#ffffff;">
            <img src="${getImagePreviewUrl(imgPath)}">
            <span class="img-slot-del" onclick="removeExtraImgByIndex(${idx})">&times;</span>
          </div>
          <div style="font-size:0.75rem; color:var(--text-muted); margin-top:4px;">附图 ${idx + 1}</div>
        </div>
      `;
    });

    // 如果未满 8 张，展示唯一的【➕ 上传附图 (支持多选)】槽位
    if (validExtra.length < 8) {
      html += `
        <div class="gallery-item-wrapper" style="text-align:center;">
          <div class="img-slot" id="extraUploadSlotBtn" onclick="triggerExtraMultiUpload()" style="width:78px; height:78px; border:2px dashed #2563eb; background:#eff6ff; cursor:pointer;" title="点击选择 1 张或多张图片">
            <span style="font-size:1.5rem; color:#2563eb; line-height:1;">➕</span>
            <span class="img-slot-label" style="font-size:9px; color:#1d4ed8; font-weight:700;">上传附图<br>(支持多选)</span>
          </div>
          <div style="font-size:0.75rem; color:#2563eb; font-weight:600; margin-top:4px;">+ 上传附图</div>
        </div>
      `;
    }

    galleryList.innerHTML = html;
  }
}

// ============================================================================
// EAN-13 Barcode Generator (严格遵循 ean13_generator.html 规范)
// ============================================================================
function generateNonAdjacentDigits(length) {
  if (length <= 0) return "";
  const digits = [];
  for (let i = 0; i < length; i++) {
    let candidates = [];
    if (i === 0) {
      candidates = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
    } else {
      const prev = digits[i - 1];
      const excluded = new Set([prev, prev - 1, prev + 1]);
      for (let d = 0; d <= 9; d++) {
        if (!excluded.has(d)) {
          candidates.push(d);
        }
      }
    }
    const picked = candidates[Math.floor(Math.random() * candidates.length)];
    digits.push(picked);
  }
  return digits.join("");
}

function calculateEAN13Checksum(s12) {
  const digits = s12.split("").map(Number);
  let evenSum = 0;
  let oddSum = 0;
  for (let i = 0; i < 12; i++) {
    if (i % 2 === 1) {
      evenSum += digits[i];
    } else {
      oddSum += digits[i];
    }
  }
  const total = (evenSum * 3) + oddSum;
  const checkDigit = (10 - (total % 10)) % 10;
  return checkDigit;
}

function generateSingleEAN13(country = "485") {
  const cStr = String(country || Math.floor(450 + Math.random() * 50)).padStart(3, "0").slice(-3);
  const mfg = generateNonAdjacentDigits(4);
  const prod = generateNonAdjacentDigits(5);
  const s12 = cStr + mfg + prod;
  const checkDigit = calculateEAN13Checksum(s12);
  return s12 + checkDigit;
}

// ============================================================================
// Calcfee 智能物流比价与日元售价推导引擎 (支持 10 大渠道比价、人工调换与实时联动)
// ============================================================================
function calculateSkuPricingClient(length, width, height, weight, purchasePrice, profitCoeff, chosenChannel = null) {
  const L = parseFloat(length) || 0;
  const W = parseFloat(width) || 0;
  const H = parseFloat(height) || 0;
  const actWt = parseFloat(weight) || 0;
  const cost = parseFloat(purchasePrice) || 0;
  const coeff = parseFloat(profitCoeff) || 1.0;
  const pCoeff = (state.pricingConfig && state.pricingConfig.price_coefficient) ? parseFloat(state.pricingConfig.price_coefficient) : 26.0;

  const sumSides = L + W + H;
  const maxSide = sumSides > 0 ? Math.max(L, W, H) : 0;
  const minSide = sumSides > 0 ? Math.min(L, W, H) : 0;
  const midSide = sumSides - maxSide - minSide;

  // 如果尺寸或重量未录入完整
  if (L <= 0 || W <= 0 || H <= 0 || actWt <= 0) {
    return {
      hasValidPricing: false,
      optimalChannel: "",
      optimalFreight: 0,
      selectedChannel: "",
      selectedFreight: 0,
      priceJpy: cost > 0 ? Math.round(cost * (1 + coeff) * pCoeff) : "",
      freights: []
    };
  }

  const vol6000 = Math.ceil((L * W * H / 6000) * 1000) / 1000;
  const vol8000 = Math.ceil((L * W * H / 8000) * 1000) / 1000;

  // 1. 各物流计费重计算
  let cwRiChuan = null;
  if (sumSides <= 960) {
    let raw = sumSides < 100 ? actWt : (actWt > vol6000 ? actWt : (actWt + vol6000) / 2);
    cwRiChuan = Math.ceil(raw / 0.5) * 0.5;
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

  // 2. 测算 10 大物流渠道
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
    if (cwRiChuan < 21) base = 60 + (mathCeilStep(cwRiChuan) - 1) * 18;
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

  // 3. 按照价格从小到大排序所有可用渠道
  freights.sort((a, b) => a.cost - b.cost);

  let optimalChannel = "";
  let optimalFreight = 0;

  if (freights.length > 0) {
    optimalChannel = freights[0].channel;
    optimalFreight = freights[0].cost;
  }

  // 默认使用最优快递；若用户手工选择了其他渠道且存在，则使用所选渠道
  let selectedChannel = optimalChannel;
  let selectedFreight = optimalFreight;

  if (chosenChannel) {
    const matched = freights.find(f => f.channel === chosenChannel);
    if (matched) {
      selectedChannel = matched.channel;
      selectedFreight = matched.cost;
    }
  }

  const totalCost = cost + selectedFreight;
  const plannedProfit = totalCost * coeff;
  const priceJpy = Math.round((totalCost + plannedProfit) * pCoeff);

  return {
    hasValidPricing: true,
    optimalChannel,
    optimalFreight,
    selectedChannel,
    selectedFreight,
    priceJpy: priceJpy > 0 ? priceJpy : 0,
    freights
  };
}

function mathCeilStep(val) {
  return Math.ceil(val / 0.5);
}

function recalcRowPricing(idx) {
  const row = state.variations[idx];
  if (!row) return;

  // 默认选择最便宜的渠道，除非用户已手动切换过
  const chosenChannel = row.manually_selected ? row.selected_channel : null;

  const res = calculateSkuPricingClient(
    row.length_cm,
    row.width_cm,
    row.height_cm,
    row.weight,
    row.purchase_price,
    row.profit_coefficient,
    chosenChannel
  );

  row.optimal_channel = res.optimalChannel;
  row.optimal_freight = res.optimalFreight;
  row.selected_channel = res.selectedChannel;
  row.selected_freight = res.selectedFreight;
  row.price_jpy = res.priceJpy;
  row.freights = res.freights;

  // 更新价格输入框
  const priceInp = document.getElementById(`price_inp_${idx}`);
  if (priceInp) priceInp.value = res.priceJpy || "";

  // 更新快递下拉选择框 Options (默认最便宜排第一并高亮显示)
  const channelSelect = document.getElementById(`channel_select_${idx}`);
  if (channelSelect) {
    if (res.freights.length > 0) {
      channelSelect.innerHTML = res.freights.map(f => `
        <option value="${f.channel}" ${f.channel === res.selectedChannel ? "selected" : ""}>
          ¥${f.cost} ${f.channel}${f.channel === res.optimalChannel ? " (最便宜)" : ""}
        </option>
      `).join("");
    } else {
      channelSelect.innerHTML = `<option value="">未核算</option>`;
    }
  }
}

function handleChannelChange(idx, newChannel) {
  const row = state.variations[idx];
  if (!row) return;

  row.manually_selected = true;
  row.selected_channel = newChannel;
  const matched = (row.freights || []).find(f => f.channel === newChannel);
  if (matched) {
    row.selected_freight = matched.cost;
  }

  const cost = parseFloat(row.purchase_price) || 0;
  const coeff = parseFloat(row.profit_coefficient) || 1.0;
  const freight = parseFloat(row.selected_freight) || 0;
  const pCoeff = (state.pricingConfig && state.pricingConfig.price_coefficient) ? parseFloat(state.pricingConfig.price_coefficient) : 26.0;

  const totalCost = cost + freight;
  const plannedProfit = totalCost * coeff;
  const newPriceJpy = Math.round((totalCost + plannedProfit) * pCoeff);

  row.price_jpy = newPriceJpy;
  const priceInp = document.getElementById(`price_inp_${idx}`);
  if (priceInp) priceInp.value = newPriceJpy || "";

  const channelSelect = document.getElementById(`channel_select_${idx}`);
  if (channelSelect && globalTooltipEl && globalTooltipEl.style.display !== "none") {
    const opt = channelSelect.options[channelSelect.selectedIndex];
    if (opt) globalTooltipEl.innerText = opt.innerText.trim();
  }

  showToast(`第 ${idx + 1} 行已切换为【¥${freight} ${newChannel}】，日元售价自动更新为 ¥${newPriceJpy}`);
}

function recalcAllPricing() {
  state.variations.forEach((row, idx) => {
    const chosenChannel = row.manually_selected ? row.selected_channel : null;
    const res = calculateSkuPricingClient(
      row.length_cm,
      row.width_cm,
      row.height_cm,
      row.weight,
      row.purchase_price,
      row.profit_coefficient,
      chosenChannel
    );
    row.optimal_channel = res.optimalChannel;
    row.optimal_freight = res.optimalFreight;
    row.selected_channel = res.selectedChannel;
    row.selected_freight = res.selectedFreight;
    row.price_jpy = res.priceJpy;
    row.freights = res.freights;
  });
  renderMatrixTable();
  showToast("⚡ 已基于最新计价参数为所有变体完成智能比价，默认选用最便宜快递！");
}

// ============================================================================
// Attribute Box Grid Management (5 Default Inputs + Add Button + Hyphen Join)
// ============================================================================
function getValidColors() {
  return state.colorInputs.map(c => (c || "").trim()).filter(Boolean);
}

function getValidSizes() {
  return state.sizeInputs.map(s => (s || "").trim()).filter(Boolean);
}

function updateColorBoxes(skipMatrix = false) {
  const container = document.getElementById("colorBoxesGrid");
  if (!container) return;
  container.innerHTML = "";

  state.colorInputs.forEach((val, idx) => {
    const item = document.createElement("div");
    item.className = "attr-box-item";
    item.innerHTML = `
      <input type="text" class="attr-box-input" placeholder="颜色 ${idx + 1}" value="${val}" data-idx="${idx}">
      ${state.colorInputs.length > 5 ? `<span class="attr-box-remove" title="删除该框" data-idx="${idx}">&times;</span>` : ""}
    `;
    const inp = item.querySelector(".attr-box-input");
    inp.addEventListener("input", (e) => {
      state.colorInputs[idx] = e.target.value;
      updatePreviewsAndMatrix();
    });

    const rem = item.querySelector(".attr-box-remove");
    if (rem) {
      rem.addEventListener("click", () => {
        state.colorInputs.splice(idx, 1);
        updateColorBoxes();
        updatePreviewsAndMatrix();
      });
    }

    container.appendChild(item);
  });

  const validColors = getValidColors();
  const colorPreview = document.getElementById("colorJoinedPreview");
  if (colorPreview) {
    colorPreview.innerText = validColors.length > 0 ? validColors.join("-") : "未输入";
  }

  if (!skipMatrix && !window.isLoadingProductForEdit) {
    updatePreviewsAndMatrix();
  }
}

function updateSizeBoxes(skipMatrix = false) {
  const container = document.getElementById("sizeBoxesGrid");
  if (!container) return;
  container.innerHTML = "";

  state.sizeInputs.forEach((val, idx) => {
    const item = document.createElement("div");
    item.className = "attr-box-item";
    item.innerHTML = `
      <input type="text" class="attr-box-input" placeholder="尺寸 ${idx + 1}" value="${val}" data-idx="${idx}">
      ${state.sizeInputs.length > 5 ? `<span class="attr-box-remove" title="删除该框" data-idx="${idx}">&times;</span>` : ""}
    `;
    const inp = item.querySelector(".attr-box-input");
    inp.addEventListener("input", (e) => {
      state.sizeInputs[idx] = e.target.value;
      updatePreviewsAndMatrix();
    });

    const rem = item.querySelector(".attr-box-remove");
    if (rem) {
      rem.addEventListener("click", () => {
        state.sizeInputs.splice(idx, 1);
        updateSizeBoxes();
        updatePreviewsAndMatrix();
      });
    }

    container.appendChild(item);
  });

  const validSizes = getValidSizes();
  const sizePreview = document.getElementById("sizeJoinedPreview");
  if (sizePreview) {
    sizePreview.innerText = validSizes.length > 0 ? validSizes.join("-") : "未输入";
  }

  if (!skipMatrix && !window.isLoadingProductForEdit) {
    updatePreviewsAndMatrix();
  }
}

function updatePreviewsAndMatrix(skipMatrix = false) {
  const validColors = getValidColors();
  const validSizes = getValidSizes();

  const colorPreview = document.getElementById("colorJoinedPreview");
  if (colorPreview) {
    colorPreview.innerText = validColors.length > 0 ? validColors.join("-") : "未输入";
  }

  const sizePreview = document.getElementById("sizeJoinedPreview");
  if (sizePreview) {
    sizePreview.innerText = validSizes.length > 0 ? validSizes.join("-") : "未输入";
  }

  renderAttrImageCards();
  if (!skipMatrix && !window.isLoadingProductForEdit) {
    autoGenerateMatrix();
  }
}

function initAttributeBoxManagers() {
  const addColorBoxBtn = document.getElementById("addMoreColorBoxBtn");
  if (addColorBoxBtn) {
    addColorBoxBtn.addEventListener("click", () => {
      state.colorInputs.push("");
      updateColorBoxes();
    });
  }

  const addSizeBoxBtn = document.getElementById("addMoreSizeBoxBtn");
  if (addSizeBoxBtn) {
    addSizeBoxBtn.addEventListener("click", () => {
      state.sizeInputs.push("");
      updateSizeBoxes();
    });
  }

  // 监听按颜色/按尺寸单选切换
  document.querySelectorAll("input[name='imageDimensionRadio']").forEach(radio => {
    radio.addEventListener("change", (e) => {
      state.imageDimension = e.target.value;
      // 切换按颜色/按尺寸后，清空已上传的图片（包括维度图片与所有变体 SKU 图片）
      state.colorImages = {};
      state.sizeImages = {};
      state.variations.forEach(v => {
        v.main_image = "";
      });
      renderAttrImageCards();
      renderMatrixTable();
      showToast(`已切换为【${state.imageDimension === "color" ? "按颜色" : "按尺寸"}】录入，并已清空历史变体图片`);
    });
  });

  updateColorBoxes();
  updateSizeBoxes();
}

// ============================================================================
// Attribute Dimension Image Entry Cards (按颜色 / 按尺寸批量配置)
// ============================================================================
function renderAttrImageCards() {
  const grid = document.getElementById("attrImgCardsGrid");
  if (!grid) return;
  grid.innerHTML = "";

  const isColor = (state.imageDimension === "color");
  const items = isColor ? getValidColors() : getValidSizes();

  if (items.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1/-1; text-align:center; padding: 24px; color:var(--text-muted); background:var(--bg-card-sub); border-radius:var(--radius-sm);">
        请先在上方【5. 变体属性设定】中输入【${isColor ? "颜色" : "尺寸"}】选项
      </div>
    `;
    return;
  }

  items.forEach(attrVal => {
    const card = document.createElement("div");
    card.className = "attr-img-card";

    const currentImg = isColor ? (state.colorImages[attrVal] || "") : (state.sizeImages[attrVal] || "");
    const matchCount = state.variations.filter(v => isColor ? (v.color === attrVal) : (v.size === attrVal)).length;

    card.innerHTML = `
      <div class="attr-img-card-title">
        <span class="tag-badge" style="font-size:0.9rem; padding: 4px 10px;">
          ${isColor ? `🎨 ${attrVal}` : `📏 ${attrVal}`}
        </span>
      </div>
      <div class="attr-img-slot" onclick="triggerAttrUpload('${attrVal}')">
        ${currentImg ? `<img src="${getImagePreviewUrl(currentImg)}"><span class="img-slot-del" onclick="removeAttrImg(event, '${attrVal}')">&times;</span>` : `<span style="font-size:1.4rem;">📷</span><span class="img-slot-label" style="font-size:0.75rem;">点击上传图片</span>`}
      </div>
      <div class="attr-img-card-hint">
        自动同步至 ${matchCount > 0 ? matchCount : (isColor ? getValidSizes().length : getValidColors().length)} 个变体
      </div>
    `;
    grid.appendChild(card);
  });
}

let currentAttrUploadKey = null;

function triggerAttrUpload(attrKey) {
  currentAttrUploadKey = attrKey;
  currentUploadTargetIdx = null;
  currentProductImgTargetSlot = null;
  const fileInput = document.getElementById("globalFileInput");
  if (!fileInput) return;
  fileInput.multiple = false;
  fileInput.click();
}

function removeAttrImg(e, attrKey) {
  e.stopPropagation();
  const isColor = (state.imageDimension === "color");
  if (isColor) {
    delete state.colorImages[attrKey];
    state.variations.forEach(v => {
      if (v.color === attrKey) v.main_image = "";
    });
  } else {
    delete state.sizeImages[attrKey];
    state.variations.forEach(v => {
      if (v.size === attrKey) v.main_image = "";
    });
  }
  renderAttrImageCards();
  renderMatrixTable();
  showToast(`已清除【${attrKey}】对应的变体图片`);
}

// ============================================================================
// Variation Matrix Auto Calculation & Table Rendering
// ============================================================================
async function autoGenerateMatrix() {
  if (window.isLoadingProductForEdit) return;
  const tbody = document.getElementById("matrixTableBody");
  if (!tbody) return;

  const validColors = getValidColors();
  const validSizes = getValidSizes();

  if (validColors.length === 0 && validSizes.length === 0) {
    state.variations = [];
    renderMatrixTable();
    renderAttrImageCards();
    return;
  }

  // 子 SKU 规则: 父 SKU + 两位序号 (父SKU01、父SKU02...), 优先取父 SKU, 其次批量前缀
  const baseSku = (document.getElementById("parentSkuInput")?.value || document.getElementById("baseSkuInput")?.value || "SKU").trim();
  const basePurchasePrice = parseFloat(document.getElementById("batchPurchasePriceInput")?.value) || 0;
  const baseProfitCoeff = parseFloat(document.getElementById("batchProfitCoeffInput")?.value) || (state.pricingConfig.default_profit_coeff || 1.0);
  const baseQty = parseInt(document.getElementById("batchQtyInput")?.value || 40, 10);

  try {
    const res = await fetch("/api/products/generate-matrix", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        colors: validColors,
        sizes: validSizes,
        base_sku: baseSku,
        base_purchase_price: basePurchasePrice,
        base_profit_coefficient: baseProfitCoeff,
        base_quantity: baseQty
      })
    });
    const result = await res.json();
    if (result.code === 0) {
      const oldMap = {};
      state.variations.forEach(v => {
        const key = `${v.color}-${v.size}`;
        oldMap[key] = { ...v };
      });

      state.variations = result.data.map(item => {
        const key = `${item.color}-${item.size}`;
        const old = oldMap[key];
        if (old) {
          item.main_image = old.main_image || "";
          item.length_cm = old.length_cm || 0;
          item.width_cm = old.width_cm || 0;
          item.height_cm = old.height_cm || 0;
          item.weight = old.weight !== undefined ? old.weight : 0;
          item.purchase_price = old.purchase_price !== undefined ? old.purchase_price : (basePurchasePrice || 0);
          item.profit_coefficient = old.profit_coefficient !== undefined ? old.profit_coefficient : baseProfitCoeff;
          // 手工改过的子 SKU 保留, 自动生成的按父 SKU+序号 规则重新生成
          if (old.sku_manual && old.sku) item.sku = old.sku;
          if (old.ean && old.ean.trim()) item.ean = old.ean.trim();
          if (old.price_jpy) item.price_jpy = old.price_jpy;
          if (old.quantity) item.quantity = old.quantity;
          if (old.optimal_channel) item.optimal_channel = old.optimal_channel;
          if (old.optimal_freight) item.optimal_freight = old.optimal_freight;
          if (old.selected_channel) item.selected_channel = old.selected_channel;
          if (old.selected_freight) item.selected_freight = old.selected_freight;
          if (old.freights) item.freights = old.freights;
        }

        // 确保每个变体均具备有效合规的 EAN-13 条码
        if (!item.ean || item.ean.length !== 13) {
          item.ean = generateSingleEAN13();
        }

        // 实时核算运费比价与日元售价（默认选中最便宜渠道）
        const chosenChannel = (old && old.manually_selected) ? old.selected_channel : null;
        const pricingRes = calculateSkuPricingClient(
          item.length_cm,
          item.width_cm,
          item.height_cm,
          item.weight,
          item.purchase_price,
          item.profit_coefficient,
          chosenChannel
        );
        item.optimal_channel = pricingRes.optimalChannel;
        item.optimal_freight = pricingRes.optimalFreight;
        item.selected_channel = pricingRes.selectedChannel;
        item.selected_freight = pricingRes.selectedFreight;
        item.price_jpy = pricingRes.priceJpy;
        item.freights = pricingRes.freights;

        // 优先使用属性维度映射图片，若无则使用原有图片
        if (state.imageDimension === "color" && state.colorImages[item.color]) {
          item.main_image = state.colorImages[item.color];
        } else if (state.imageDimension === "size" && state.sizeImages[item.size]) {
          item.main_image = state.sizeImages[item.size];
        }

        return item;
      });

      // 保持两个输入框与全局缓存对齐
      const parentSkuInp = document.getElementById("parentSkuInput");
      const baseSkuInp = document.getElementById("baseSkuInput");
      if (baseSkuInp && !baseSkuInp.value && baseSku) baseSkuInp.value = baseSku;
      if (parentSkuInp && !parentSkuInp.value && baseSku) parentSkuInp.value = baseSku;
      window.lastParentSkuValue = (parentSkuInp?.value || baseSkuInp?.value || baseSku).trim();

      renderMatrixTable();
      renderAttrImageCards();
    }
  } catch (err) {
    console.error("生成矩阵失败:", err);
  }
}

function renderMatrixTable() {
  const tbody = document.getElementById("matrixTableBody");
  const countBadge = document.getElementById("variationCountBadge");
  if (!tbody) return;

  tbody.innerHTML = "";
  if (countBadge) countBadge.innerText = `${state.variations.length} 个组合`;

  if (state.variations.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="15" style="text-align:center; padding:36px; color:var(--text-muted);">
          暂无变体组合，请在上方【5. 变体属性设定】中输入颜色或尺寸选项自动生成
        </td>
      </tr>
    `;
    return;
  }

  state.variations.forEach((row, idx) => {
    const tr = document.createElement("tr");

    // 生成渠道下拉菜单 options（最低价在最顶部，默认选中最便宜的渠道，标记 (最便宜)）
    let channelOptionsHtml = `<option value="">未核算</option>`;
    if (row.freights && row.freights.length > 0) {
      const activeChannel = row.selected_channel || row.optimal_channel || row.freights[0].channel;
      const cheapestChannel = row.optimal_channel || row.freights[0].channel;
      channelOptionsHtml = row.freights.map(f => `
        <option value="${f.channel}" ${f.channel === activeChannel ? "selected" : ""}>
          ¥${f.cost} ${f.channel}${f.channel === cheapestChannel ? " (最便宜)" : ""}
        </option>
      `).join("");
    }

    tr.innerHTML = `
      <td style="font-weight:600; color:var(--primary); text-align:center;">${idx + 1}</td>
      <td style="text-align:center;">
        <div class="img-slot" id="main_slot_${idx}" onclick="triggerUpload(${idx})" style="width:48px; height:48px; margin:0 auto;">
          ${row.main_image ? `<img src="${getImagePreviewUrl(row.main_image)}"><span class="img-slot-del" onclick="removeImg(event, ${idx})">&times;</span>` : `<span style="font-size:0.95rem;">📷</span><span class="img-slot-label" style="font-size:8px;">上传</span>`}
        </div>
      </td>
      <td style="text-align:center;"><span class="tag-badge" style="padding:2px 5px; font-size:0.78rem;">${row.color || "-"}</span></td>
      <td style="text-align:center;"><span class="tag-badge" style="background:#f3e8ff; color:#7e22ce; border-color:#e9d5ff; padding:2px 5px; font-size:0.78rem;">${row.size || "-"}</span></td>
      <td><input type="text" inputmode="decimal" class="table-input len-inp" placeholder="长" style="width:52px; text-align:center;" value="${row.length_cm || ""}" data-idx="${idx}"></td>
      <td><input type="text" inputmode="decimal" class="table-input width-inp" placeholder="宽" style="width:52px; text-align:center;" value="${row.width_cm || ""}" data-idx="${idx}"></td>
      <td><input type="text" inputmode="decimal" class="table-input height-inp" placeholder="高" style="width:52px; text-align:center;" value="${row.height_cm || ""}" data-idx="${idx}"></td>
      <td><input type="text" inputmode="decimal" class="table-input weight-inp" placeholder="重量" style="width:58px; text-align:center;" value="${row.weight ? row.weight : ""}" data-idx="${idx}"></td>
      <td><input type="text" inputmode="decimal" class="table-input purchase-price-inp" placeholder="进价¥" style="width:68px; text-align:center; font-weight:600; color:#b45309;" value="${row.purchase_price ? row.purchase_price : ""}" data-idx="${idx}"></td>
      <td><input type="text" inputmode="decimal" class="table-input profit-coeff-inp" placeholder="系数" style="width:54px; text-align:center;" value="${row.profit_coefficient !== undefined ? row.profit_coefficient : 1.0}" data-idx="${idx}"></td>
      <td style="text-align:center;">
        <select class="channel-select" id="channel_select_${idx}" data-idx="${idx}" onchange="handleChannelChange(${idx}, this.value)" onmouseenter="showChannelTooltip(event, this)" onmouseleave="hideSkuTooltip()" onfocus="showChannelTooltip(event, this)" onblur="hideSkuTooltip()">
          ${channelOptionsHtml}
        </select>
      </td>
      <td><input type="text" readonly class="table-input price-inp" id="price_inp_${idx}" style="width:75px; text-align:center; font-weight:700; color:var(--primary);" value="${row.price_jpy || ""}" data-idx="${idx}" title="由尺寸、重量、采购价与所选物流自动推导计算，不可手工修改"></td>
      <td><input type="text" inputmode="numeric" class="table-input qty-inp" style="width:52px; text-align:center;" value="${row.quantity !== undefined ? row.quantity : 40}" data-idx="${idx}"></td>
      <td style="text-align:center;">
        <input type="text" class="table-input ean-inp" placeholder="EAN条码" value="${row.ean || ""}" style="width:75px; font-size:0.8rem;" data-idx="${idx}" onmouseenter="showSkuTooltip(event, this.value)" onmouseleave="hideSkuTooltip()" onfocus="showSkuTooltip(event, this.value)" onblur="hideSkuTooltip()">
      </td>
      <td style="text-align:center;">
        <input type="text" class="table-input sku-inp" value="${row.sku || ""}" style="width:75px; font-size:0.8rem;" data-idx="${idx}" onmouseenter="showSkuTooltip(event, this.value)" onmouseleave="hideSkuTooltip()" onfocus="showSkuTooltip(event, this.value)" onblur="hideSkuTooltip()">
      </td>
    `;
    tbody.appendChild(tr);
  });

  // 绑定数据输入与价格实时联动事件
  tbody.querySelectorAll(".len-inp").forEach(inp => {
    inp.addEventListener("input", (e) => {
      const idx = e.target.dataset.idx;
      state.variations[idx].length_cm = parseFloat(e.target.value) || 0;
      recalcRowPricing(idx);
      syncPackageDimFromMaxVolumeSku();
    });
  });
  tbody.querySelectorAll(".width-inp").forEach(inp => {
    inp.addEventListener("input", (e) => {
      const idx = e.target.dataset.idx;
      state.variations[idx].width_cm = parseFloat(e.target.value) || 0;
      recalcRowPricing(idx);
      syncPackageDimFromMaxVolumeSku();
    });
  });
  tbody.querySelectorAll(".height-inp").forEach(inp => {
    inp.addEventListener("input", (e) => {
      const idx = e.target.dataset.idx;
      state.variations[idx].height_cm = parseFloat(e.target.value) || 0;
      recalcRowPricing(idx);
      syncPackageDimFromMaxVolumeSku();
    });
  });
  tbody.querySelectorAll(".weight-inp").forEach(inp => {
    inp.addEventListener("input", (e) => {
      const idx = e.target.dataset.idx;
      state.variations[idx].weight = parseFloat(e.target.value) || 0;
      recalcRowPricing(idx);
      syncPackageDimFromMaxVolumeSku();
    });
  });
  tbody.querySelectorAll(".purchase-price-inp").forEach(inp => {
    inp.addEventListener("input", (e) => {
      const idx = e.target.dataset.idx;
      state.variations[idx].purchase_price = parseFloat(e.target.value) || 0;
      recalcRowPricing(idx);
    });
  });
  tbody.querySelectorAll(".profit-coeff-inp").forEach(inp => {
    inp.addEventListener("input", (e) => {
      const idx = e.target.dataset.idx;
      state.variations[idx].profit_coefficient = parseFloat(e.target.value) || 1.0;
      recalcRowPricing(idx);
    });
  });
  tbody.querySelectorAll(".qty-inp").forEach(inp => {
    inp.addEventListener("input", (e) => state.variations[e.target.dataset.idx].quantity = parseInt(e.target.value, 10) || 0);
  });
  tbody.querySelectorAll(".sku-inp").forEach(inp => {
    inp.addEventListener("input", (e) => {
      const idx = e.target.dataset.idx;
      state.variations[idx].sku = e.target.value;
      // 标记为手工修改, 父 SKU 变更与矩阵重生成时不再自动覆盖
      state.variations[idx].sku_manual = true;
      if (globalTooltipEl && globalTooltipEl.style.display !== "none") {
        globalTooltipEl.innerText = e.target.value;
      }
    });
  });
  tbody.querySelectorAll(".ean-inp").forEach(inp => {
    inp.addEventListener("input", (e) => {
      const idx = e.target.dataset.idx;
      state.variations[idx].ean = e.target.value;
      if (globalTooltipEl && globalTooltipEl.style.display !== "none") {
        globalTooltipEl.innerText = e.target.value;
      }
    });
  });

  // 自动将变体SKU中体积最大的参数填入包装尺寸与包装重量
  syncPackageDimFromMaxVolumeSku();
}

/**
 * 自动计算并同步：将变体明细表中体积 (长x宽x高) 最大的 SKU 尺寸与重量填入产品包装属性
 */
function syncPackageDimFromMaxVolumeSku() {
  if (!state.variations || state.variations.length === 0) return;

  let maxVol = -1;
  let maxVar = null;

  state.variations.forEach(v => {
    const len = parseFloat(v.length_cm) || 0;
    const wid = parseFloat(v.width_cm) || 0;
    const hgt = parseFloat(v.height_cm) || 0;
    const vol = len * wid * hgt;
    if (vol > maxVol) {
      maxVol = vol;
      maxVar = v;
    }
  });

  if (maxVar) {
    const pkgLenInp = document.getElementById("pkgLengthInput");
    const pkgWidthInp = document.getElementById("pkgWidthInput");
    const pkgHeightInp = document.getElementById("pkgHeightInput");
    const pkgWeightInp = document.getElementById("pkgWeightInput");

    if (pkgLenInp && maxVar.length_cm !== undefined && maxVar.length_cm > 0) {
      pkgLenInp.value = maxVar.length_cm;
    }
    if (pkgWidthInp && maxVar.width_cm !== undefined && maxVar.width_cm > 0) {
      pkgWidthInp.value = maxVar.width_cm;
    }
    if (pkgHeightInp && maxVar.height_cm !== undefined && maxVar.height_cm > 0) {
      pkgHeightInp.value = maxVar.height_cm;
    }
    if (pkgWeightInp && maxVar.weight !== undefined && maxVar.weight > 0) {
      pkgWeightInp.value = maxVar.weight;
    }
  }
}

// ============================================================================
// Single Image Upload Handler per SKU, Attribute or Product Gallery
// ============================================================================
let currentUploadTargetIdx = null;

function triggerUpload(rowIdx) {
  currentUploadTargetIdx = rowIdx;
  currentAttrUploadKey = null;
  currentProductImgTargetSlot = null;
  const fileInput = document.getElementById("globalFileInput");
  if (!fileInput) return;
  fileInput.multiple = false;
  fileInput.click();
}

function removeImg(e, idx) {
  e.stopPropagation();
  state.variations[idx].main_image = "";
  renderMatrixTable();
}

async function handleFileSelect(e) {
  const files = e.target.files;
  if (!files || files.length === 0) return;

  const formData = new FormData();
  formData.append("file", files[0]);

  try {
    const res = await fetch("/api/upload/single", { method: "POST", body: formData });
    const data = await res.json();
    if (data.code === 0) {
      const savedPath = data.data.absolute_path;

      // 1. 产品主图与附图上传
      if (currentProductImgTargetSlot !== null) {
        const slot = currentProductImgTargetSlot;
        if (slot === 0) {
          state.productMainImage = savedPath;
          showToast("★ 产品主图上传成功！");
        } else {
          state.productExtraImages[slot - 1] = savedPath;
          showToast(`产品附图 ${slot} 上传成功！`);
        }
        renderProductGallery();
      }
      // 2. 按颜色/按尺寸维度图片上传
      else if (currentAttrUploadKey !== null) {
        const attrKey = currentAttrUploadKey;
        const isColor = (state.imageDimension === "color");

        if (isColor) {
          state.colorImages[attrKey] = savedPath;
          let syncCount = 0;
          state.variations.forEach(v => {
            if (v.color === attrKey) {
              v.main_image = savedPath;
              syncCount++;
            }
          });
          showToast(`已成功为【颜色: ${attrKey}】上传图片并同步应用至 ${syncCount} 个变体！`);
        } else {
          state.sizeImages[attrKey] = savedPath;
          let syncCount = 0;
          state.variations.forEach(v => {
            if (v.size === attrKey) {
              v.main_image = savedPath;
              syncCount++;
            }
          });
          showToast(`已成功为【尺寸: ${attrKey}】上传图片并同步应用至 ${syncCount} 个变体！`);
        }
        renderAttrImageCards();
        renderMatrixTable();
      }
      // 3. 单个变体 SKU 行上传
      else if (currentUploadTargetIdx !== null) {
        const rowIdx = currentUploadTargetIdx;
        state.variations[rowIdx].main_image = savedPath;
        showToast("单个变体图片上传成功！");
        renderMatrixTable();
      }
    } else {
      showToast(`上传失败: ${data.msg}`, "error");
    }
  } catch (err) {
    showToast(`上传异常: ${err.message}`, "error");
  }

  e.target.value = "";
}

// ============================================================================
// Batch Operations
// ============================================================================
function initBatchOperations() {
  const batchPurchasePriceBtn = document.getElementById("applyBatchPurchasePriceBtn");
  const batchProfitCoeffBtn = document.getElementById("applyBatchProfitCoeffBtn");
  const batchQtyBtn = document.getElementById("applyBatchQtyBtn");
  const batchRecalcPricingBtn = document.getElementById("batchRecalcPricingBtn");
  const regenerateEanBtn = document.getElementById("regenerateEanBtn");

  if (batchPurchasePriceBtn) {
    batchPurchasePriceBtn.addEventListener("click", () => {
      const p = parseFloat(document.getElementById("batchPurchasePriceInput")?.value) || 0;
      state.variations.forEach(v => v.purchase_price = p);
      recalcAllPricing();
      showToast(`已批量设置所有变体采购价为: ¥${p} 并重新核算日元售价`);
    });
  }

  if (batchProfitCoeffBtn) {
    batchProfitCoeffBtn.addEventListener("click", () => {
      const coeff = parseFloat(document.getElementById("batchProfitCoeffInput")?.value) || (state.pricingConfig.default_profit_coeff || 1.0);
      state.variations.forEach(v => v.profit_coefficient = coeff);
      recalcAllPricing();
      showToast(`已批量设置所有变体利润系数为: ${coeff} 并重新核算日元售价`);
    });
  }

  if (batchQtyBtn) {
    batchQtyBtn.addEventListener("click", () => {
      const q = parseInt(document.getElementById("batchQtyInput")?.value || 40, 10);
      state.variations.forEach(v => v.quantity = q);
      renderMatrixTable();
      showToast(`已批量设置所有变体库存为: ${q}`);
    });
  }

  if (batchRecalcPricingBtn) {
    batchRecalcPricingBtn.addEventListener("click", () => {
      recalcAllPricing();
    });
  }

  if (regenerateEanBtn) {
    regenerateEanBtn.addEventListener("click", () => {
      const seen = new Set();
      state.variations.forEach(v => {
        let ean = generateSingleEAN13();
        while (seen.has(ean)) {
          ean = generateSingleEAN13();
        }
        seen.add(ean);
        v.ean = ean;
      });
      renderMatrixTable();
      showToast("🎲 已按照 EAN-13 规范为所有变体生成全新合规条码！");
    });
  }

  const applyBatchSkuBtn = document.getElementById("applyBatchSkuBtn");
  if (applyBatchSkuBtn) {
    applyBatchSkuBtn.addEventListener("click", () => {
      const parentSkuInp = document.getElementById("parentSkuInput");
      const baseSkuInp = document.getElementById("baseSkuInput");
      const val = (baseSkuInp?.value || parentSkuInp?.value || "").trim();
      if (!val) {
        showToast("请输入有效的前缀/父 SKU 编码！", "warning");
        return;
      }
      const oldVal = window.lastParentSkuValue || "";
      if (parentSkuInp) parentSkuInp.value = val;
      if (baseSkuInp) baseSkuInp.value = val;
      syncChildSkusWithParent(oldVal, val);
      window.lastParentSkuValue = val;
      showToast(`已批量同步更新父 SKU 与所有子变体 SKU 编码为: ${val}`);
    });
  }
}

// ============================================================================
// Save Product & Publish to Dianxiaomi
// ============================================================================
async function saveProduct() {
  const store_account = document.getElementById("storeAccountSelect")?.value;
  const site = "日本";
  const parent_sku = document.getElementById("parentSkuInput")?.value.trim() || "";
  const manufacturer = document.getElementById("manufacturerInput")?.value.trim() || "";
  const title = document.getElementById("titleInput")?.value.trim();
  const title_translation = document.getElementById("titleTranslationInput")?.value.trim() || "";
  const product_identifier = document.getElementById("productIdentifierInput")?.value.trim() || "";
  const identifier_translation = document.getElementById("identifierTranslationInput")?.value.trim() || "";
  const sale_type = document.querySelector("input[name='saleTypeRadio']:checked")?.value || document.getElementById("saleTypeSelect")?.value || "variation";
  const variation_theme = document.getElementById("variationThemeSelect")?.value || "カラー/サイズ(颜色/尺寸)";

  // 产品属性
  const model_number = document.getElementById("modelNumberInput")?.value.trim() || "";
  const model_name = document.getElementById("modelNameInput")?.value.trim() || "";
  const item_length = parseFloat(document.getElementById("itemLengthInput")?.value) || 0;
  const item_width = parseFloat(document.getElementById("itemWidthInput")?.value) || 0;
  const item_height = parseFloat(document.getElementById("itemHeightInput")?.value) || 0;
  const item_dimension_unit = document.getElementById("itemDimUnitSelect")?.value || "cm";

  const package_length = parseFloat(document.getElementById("pkgLengthInput")?.value) || 0;
  const package_width = parseFloat(document.getElementById("pkgWidthInput")?.value) || 0;
  const package_height = parseFloat(document.getElementById("pkgHeightInput")?.value) || 0;
  const package_dimension_unit = document.getElementById("pkgDimUnitSelect")?.value || "cm";

  const package_weight = parseFloat(document.getElementById("pkgWeightInput")?.value) || 0;
  const package_weight_unit = document.getElementById("pkgWeightUnitSelect")?.value || "kg";

  const bullet_points = [];
  document.querySelectorAll(".bullet-point-inp").forEach(inp => {
    const v = inp.value.trim();
    if (v) bullet_points.push(v);
  });

  const chinese_translations = [];
  document.querySelectorAll(".bullet-point-cn-hint").forEach(el => {
    let txt = el.textContent.replace(/^🇨🇳\s*中文翻译参考[:：]?\s*/, "").trim();
    if (txt) chinese_translations.push(txt);
  });

  // 商品描述：值为 5 点描述的内容 (带序号, 每点一行)
  let description = document.getElementById("descriptionInput")?.value.trim() || "";
  if (!description && bullet_points.length > 0) {
    description = bullet_points.map((bp, i) => `${i + 1}. ${bp}`).join("\n");
  }

  // 关键词 Search Terms：内容为标题信息
  const search_terms = document.getElementById("searchTermsInput")?.value.trim() || title;
  const fulfillment_channel = document.getElementById("fulfillmentChannelSelect")?.value || "FBM";

  if (!store_account || !title) {
    showToast("请填写必填项：店铺账号与商品标题！", "error");
    return;
  }

  // 必填项校验: 商品标识英文翻译不能为空
  if (!identifier_translation) {
    showToast("请填写商品标识的英文翻译！", "error");
    const idTransInp = document.getElementById("identifierTranslationInput");
    if (idTransInp) {
      idTransInp.focus();
      idTransInp.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    return;
  }

  const validColors = getValidColors();
  const validSizes = getValidSizes();
  const colorJoined = validColors.join("-");
  const sizeJoined = validSizes.join("-");
  const imgDim = document.querySelector("input[name='imageDimensionRadio']:checked")?.value || state.imageDimension || "color";
  const varDimImages = imgDim === "size" ? state.sizeImages : state.colorImages;

  // 同步变体明细表中所有输入框与下拉选择框的最新值
  const tbody = document.getElementById("matrixTableBody");
  if (tbody) {
    const rows = tbody.querySelectorAll("tr");
    rows.forEach((tr, idx) => {
      if (state.variations[idx]) {
        const lenVal = tr.querySelector(".len-inp")?.value;
        const widthVal = tr.querySelector(".width-inp")?.value;
        const heightVal = tr.querySelector(".height-inp")?.value;
        const weightVal = tr.querySelector(".weight-inp")?.value;
        const purchaseVal = tr.querySelector(".purchase-price-inp")?.value;
        const coeffVal = tr.querySelector(".profit-coeff-inp")?.value;
        const channelVal = tr.querySelector(".channel-select")?.value;
        const skuVal = tr.querySelector(".sku-inp")?.value;
        const eanVal = tr.querySelector(".ean-inp")?.value;
        const priceVal = tr.querySelector(".price-inp")?.value;
        const qtyVal = tr.querySelector(".qty-inp")?.value;

        if (lenVal !== undefined) state.variations[idx].length_cm = parseFloat(lenVal) || 0;
        if (widthVal !== undefined) state.variations[idx].width_cm = parseFloat(widthVal) || 0;
        if (heightVal !== undefined) state.variations[idx].height_cm = parseFloat(heightVal) || 0;
        if (weightVal !== undefined) {
          state.variations[idx].weight = parseFloat(weightVal) || 0;
          state.variations[idx].weight_kg = parseFloat(weightVal) || 0;
        }
        if (purchaseVal !== undefined) state.variations[idx].purchase_price = parseFloat(purchaseVal) || 0;
        if (coeffVal !== undefined) state.variations[idx].profit_coefficient = parseFloat(coeffVal) || 1.0;
        if (channelVal) {
          state.variations[idx].selected_channel = channelVal;
          state.variations[idx].shipping_channel = channelVal;
        }
        if (skuVal !== undefined) state.variations[idx].sku = skuVal.trim();
        if (eanVal !== undefined) state.variations[idx].ean = eanVal.trim();
        if (priceVal !== undefined) state.variations[idx].price_jpy = parseFloat(priceVal) || 0;
        if (qtyVal !== undefined) state.variations[idx].quantity = parseInt(qtyVal, 10) || 0;
        state.variations[idx].variant_image = state.variations[idx].main_image || "";
      }
    });
  }

  const payload = {
    store_account,
    site,
    parent_sku,
    manufacturer,
    product_id_type: "EAN",
    product_id_value: "",
    title,
    title_translation,
    product_identifier,
    identifier_translation,
    brand: document.getElementById("brandInput")?.value.trim() || "",
    category_name: "厕所托盘(トイレトレー)",
    category_type: "LITTER_BOX",
    model_number,
    model_name,
    item_length,
    item_width,
    item_height,
    item_dimension_unit,
    package_length,
    package_width,
    package_height,
    package_dimension_unit,
    package_weight,
    package_weight_unit,
    main_image: state.productMainImage,
    extra_images: state.productExtraImages.filter(Boolean),
    sale_type,
    variation_theme,
    color_options: validColors,
    size_options: validSizes,
    variant_image_dimension: imgDim,
    variant_dimension_images: varDimImages,
    attributes: {
      color: validColors,
      size: validSizes,
      color_joined: colorJoined,
      size_joined: sizeJoined,
      color_images: imgDim === "color" ? state.colorImages : {},
      size_images: imgDim === "size" ? state.sizeImages : {}
    },
    bullet_points,
    chinese_translations,
    description,
    search_terms,
    fulfillment_channel,
    variations: state.variations
  };

  try {
    const isEdit = (editingProductId !== null && editingProductId !== undefined);
    const apiUrl = isEdit ? `/api/products/${editingProductId}` : "/api/products";
    const method = isEdit ? "PUT" : "POST";
    const actionDesc = isEdit ? "修改" : "保存";

    showToast(`正在${actionDesc}商品数据到本地数据库并自动归档文件...`);
    const res = await fetch(apiUrl, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    if (result.code === 0) {
      const productId = (result.data && result.data.id) ? result.data.id : (editingProductId || 1);
      showToast(`✅ 商品${actionDesc}成功！正在跳转商品管理列表...`);

      // 录入/编辑商品提交成功后，自动跳转到商品列表页面
      setTimeout(() => {
        window.location.href = "/list";
      }, 600);
    } else {
      showToast(`${actionDesc}失败: ${result.msg}`, "error");
    }
  } catch (err) {
    showToast(`系统异常: ${err.message}`, "error");
  }
}

/**
 * 编辑模式：加载已有商品的全部数据并自动回填至表单各卡片与状态树
 */
async function loadProductForEdit(productId) {
  window.isLoadingProductForEdit = true;
  try {
    const banner = document.getElementById("editModeBanner");
    const hint = document.getElementById("editModeHintText");
    if (banner) banner.style.display = "inline-flex";
    if (hint) hint.textContent = `正在加载商品 #${productId} 结构化数据...`;

    const res = await fetch(`/api/products/${productId}`);
    const result = await res.json();
    if (result.code !== 0 || !result.data) {
      showToast(`加载商品数据失败: ${result.msg || '商品不存在'}`, "error");
      if (hint) hint.textContent = `❌ 商品 #${productId} 加载失败`;
      return;
    }

    const p = result.data;
    if (hint) {
      hint.textContent = `商品 ID: #${p.id} | Parent SKU: ${p.parent_sku || p.sku || '-'} | 标题: ${p.title || '-'}`;
    }

    // 动态调整保存按钮文案
    const saveBtn = document.getElementById("saveProductBtn");
    if (saveBtn) saveBtn.textContent = "保存修改";

    // 1. 店铺与基础配置
    const storeSel = document.getElementById("storeAccountSelect");
    if (storeSel && p.store_account) {
      storeSel.value = p.store_account;
    }
    const brandInp = document.getElementById("brandInput");
    if (brandInp) brandInp.value = p.brand || "";

    const titleInp = document.getElementById("titleInput");
    if (titleInp) {
      titleInp.value = p.title || "";
      // 编辑模式下锁定标题：不支持修改产品标题
      titleInp.readOnly = true;
      titleInp.style.backgroundColor = "#f1f5f9";
      titleInp.style.cursor = "not-allowed";
      titleInp.title = "编辑商品模式下已锁定标题，不支持修改产品标题";
      const lockBadge = document.getElementById("titleEditLockBadge");
      if (lockBadge) lockBadge.style.display = "inline-block";
      const transTitleBtn = document.getElementById("translateTitleBtn");
      if (transTitleBtn) {
        transTitleBtn.disabled = true;
        transTitleBtn.style.opacity = "0.5";
        transTitleBtn.title = "编辑模式下标题已锁定，无需重新翻译";
      }
    }

    const prodIdInp = document.getElementById("productIdentifierInput");
    if (prodIdInp) prodIdInp.value = p.product_identifier || "";
    const titleTransInp = document.getElementById("titleTranslationInput");
    if (titleTransInp) titleTransInp.value = p.title_translation || "";
    const idTransInp = document.getElementById("identifierTranslationInput");
    if (idTransInp) idTransInp.value = p.identifier_translation || "";

    const saleType = p.sale_type || "variation";
    const saleRadio = document.querySelector(`input[name='saleTypeRadio'][value='${saleType}']`);
    if (saleRadio) saleRadio.checked = true;

    // 2. 产品信息
    const parentSkuInp = document.getElementById("parentSkuInput");
    if (parentSkuInp) {
      const pSku = p.parent_sku || p.sku || "";
      parentSkuInp.value = pSku;
      parentSkuInp.dataset.baseSku = pSku;
      window.lastParentSkuValue = pSku;
    }
    const baseSkuInp = document.getElementById("baseSkuInput");
    if (baseSkuInp) baseSkuInp.value = p.parent_sku || p.sku || "";

    // 3. 产品属性
    const modelNumInp = document.getElementById("modelNumberInput");
    if (modelNumInp) modelNumInp.value = p.model_number || "";
    const modelNameInp = document.getElementById("modelNameInput");
    if (modelNameInp) modelNameInp.value = p.model_name || "";

    const itemLenInp = document.getElementById("itemLengthInput");
    if (itemLenInp) itemLenInp.value = p.item_length || "";
    const itemWidthInp = document.getElementById("itemWidthInput");
    if (itemWidthInp) itemWidthInp.value = p.item_width || "";
    const itemHeightInp = document.getElementById("itemHeightInput");
    if (itemHeightInp) itemHeightInp.value = p.item_height || "";
    const itemDimUnitSel = document.getElementById("itemDimUnitSelect");
    if (itemDimUnitSel && (p.item_dim_unit || p.item_dimension_unit)) {
      itemDimUnitSel.value = p.item_dim_unit || p.item_dimension_unit;
    }

    const pkgLenInp = document.getElementById("pkgLengthInput");
    if (pkgLenInp) pkgLenInp.value = p.package_length || "";
    const pkgWidthInp = document.getElementById("pkgWidthInput");
    if (pkgWidthInp) pkgWidthInp.value = p.package_width || "";
    const pkgHeightInp = document.getElementById("pkgHeightInput");
    if (pkgHeightInp) pkgHeightInp.value = p.package_height || "";
    const pkgDimUnitSel = document.getElementById("pkgDimUnitSelect");
    if (pkgDimUnitSel && (p.package_dim_unit || p.package_dimension_unit)) {
      pkgDimUnitSel.value = p.package_dim_unit || p.package_dimension_unit;
    }

    const pkgWeightInp = document.getElementById("pkgWeightInput");
    if (pkgWeightInp) pkgWeightInp.value = p.package_weight || "";
    const pkgWeightUnitSel = document.getElementById("pkgWeightUnitSelect");
    if (pkgWeightUnitSel && p.package_weight_unit) {
      pkgWeightUnitSel.value = p.package_weight_unit;
    }

    // 4. 图片回填
    state.productMainImage = p.main_image || "";
    state.productExtraImages = Array.isArray(p.extra_images) ? [...p.extra_images] : [];
    renderProductGallery();

    // 5. 变体属性设定 (颜色 & 尺寸)
    const varThemeSel = document.getElementById("variationThemeSelect");
    if (varThemeSel && p.variation_theme) {
      varThemeSel.value = p.variation_theme;
    }

    const colors = Array.isArray(p.color_options) && p.color_options.length > 0 ? p.color_options : (p.attributes?.color || []);
    const sizes = Array.isArray(p.size_options) && p.size_options.length > 0 ? p.size_options : (p.attributes?.size || []);

    state.colorInputs = colors.length > 0 ? [...colors] : ["", "", "", "", ""];
    while (state.colorInputs.length < 5) state.colorInputs.push("");

    state.sizeInputs = sizes.length > 0 ? [...sizes] : ["", "", "", "", ""];
    while (state.sizeInputs.length < 5) state.sizeInputs.push("");

    // 6. 变体图片录入维度与映射
    const hasSizeImgs = p.attributes?.size_images && Object.keys(p.attributes.size_images).length > 0;
    state.imageDimension = p.variant_image_dimension || (hasSizeImgs ? "size" : "color");
    const dimRadio = document.querySelector(`input[name='imageDimensionRadio'][value='${state.imageDimension}']`);
    if (dimRadio) dimRadio.checked = true;

    state.colorImages = {};
    state.sizeImages = {};
    const dimImgs = p.variant_dimension_images || (state.imageDimension === "size" ? (p.attributes?.size_images || {}) : (p.attributes?.color_images || {}));
    if (state.imageDimension === "color") {
      state.colorImages = { ...dimImgs, ...(p.attributes?.color_images || {}) };
    } else {
      state.sizeImages = { ...dimImgs, ...(p.attributes?.size_images || {}) };
    }

    updateColorBoxes(true);
    updateSizeBoxes(true);

    // 7. 变体明细矩阵数据精准回填
    if (Array.isArray(p.variations) && p.variations.length > 0) {
      state.variations = p.variations.map(v => ({
        sku: v.sku || "",
        ean: v.ean || "",
        color: v.color || "",
        size: v.size || "",
        length_cm: v.length_cm || 0,
        width_cm: v.width_cm || 0,
        height_cm: v.height_cm || 0,
        weight: v.weight_kg !== undefined ? v.weight_kg : (v.weight || 0),
        weight_kg: v.weight_kg !== undefined ? v.weight_kg : (v.weight || 0),
        purchase_price: v.purchase_price !== undefined ? v.purchase_price : 50.0,
        profit_coefficient: v.profit_coefficient !== undefined ? v.profit_coefficient : 1.0,
        selected_channel: v.shipping_channel || v.selected_channel || v.optimal_channel || "",
        shipping_channel: v.shipping_channel || v.selected_channel || v.optimal_channel || "",
        optimal_channel: v.optimal_channel || "",
        optimal_freight: v.optimal_freight || 0,
        price_jpy: v.price_jpy || 0,
        quantity: v.quantity !== undefined ? v.quantity : 40,
        main_image: v.variant_image || v.main_image || "",
        variant_image: v.variant_image || v.main_image || "",
        condition: v.condition || "新品",
        description: v.description || ""
      }));
    }

    renderAttrImageCards();
    renderMatrixTable();
    syncPackageDimFromMaxVolumeSku();

    // 8. 描述信息
    const descInp = document.getElementById("descriptionInput");
    if (descInp) descInp.value = p.description || "";

    const bullets = Array.isArray(p.bullet_points) ? p.bullet_points : [];
    const trans = Array.isArray(p.chinese_translations) ? p.chinese_translations : [];
    if (bullets.length > 0) {
      populateBulletPoints(bullets, trans);
    }

    // 9. 运输信息
    const fulfillSel = document.getElementById("fulfillmentChannelSelect");
    if (fulfillSel && p.fulfillment_channel) {
      fulfillSel.value = p.fulfillment_channel;
    }

    // 10. 关键词
    const searchTermsInp = document.getElementById("searchTermsInput");
    if (searchTermsInp) {
      searchTermsInp.value = p.search_terms || "";
    }

    showToast(`✅ 已成功加载商品 #${productId} 的全部数据，可直接修改！`);
  } catch (err) {
    console.error("加载商品编辑数据异常:", err);
    showToast(`加载商品异常: ${err.message}`, "error");
  } finally {
    window.isLoadingProductForEdit = false;
  }
}

/**
 * 通用提取器：从文本中提取任意数量 & 构成的分隔区间 (如 &&&&&&&&& 或 &&&&&&&&&&&&&&&&&&&)
 * 并提取对应的中文翻译段落
 */
function extractAmpersandSection(text) {
  if (!text) return { extractedText: "", bullets: [], chineseTranslations: [] };

  let bullets = [];
  let chineseTranslations = [];

  // 提取中文翻译
  if (text.includes("中文翻译") || text.includes("二、") || text.includes("翻訳")) {
    const parts = text.split(/二[、.·\s]*中文翻译|中文翻译|二、|翻訳/);
    if (parts.length > 1) {
      const cnPart = parts[1];
      const cnLines = cnPart.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith("&") && !l.startsWith("-") && !l.startsWith("="));
      chineseTranslations = cnLines.map(l => l.replace(/^\d+[\.、\s\-]+/, "").trim()).filter(Boolean);
    }
  }

  // 1. 如果包含 & 标记
  if (text.includes("&")) {
    const rawLines = text.split(/\r?\n/).map(l => l.trim());
    const extracted = [];
    let insideAmp = false;
    let foundAmp = false;

    for (const line of rawLines) {
      // 只要包含 2 个及以上连续/夹带空格的 & 即视作分隔行
      const stripped = line.replace(/\s+/g, '');
      if (/^&{2,}$/.test(stripped)) {
        if (!insideAmp) {
          insideAmp = true;
          foundAmp = true;
          continue;
        } else {
          insideAmp = false;
          break; // 遇到闭合标记，提取结束
        }
      }

      if (insideAmp && line) {
        extracted.push(line);
      }
    }

    if (foundAmp && extracted.length > 0) {
      bullets = extracted.map(l => l.replace(/^\d+[\.、\s\-]+/, "").trim()).filter(Boolean);
      const numberedText = bullets.map((b, idx) => `${idx + 1}. ${b}`).join("\n");
      return {
        extractedText: numberedText,
        bullets: bullets,
        chineseTranslations: chineseTranslations
      };
    }
  }

  // 2. 备选：若未找到 & 标记，根据 "一、日文版" 和 "二、中文翻译" 截取
  if (text.includes("日文版") || text.includes("日本語版")) {
    const rawLines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    const extracted = [];
    let inJpSection = false;

    for (const rLine of rawLines) {
      if (rLine.includes("日文版") || rLine.includes("日本語版")) {
        inJpSection = true;
        continue;
      }
      if (rLine.includes("中文翻译") || rLine.includes("二、") || rLine.includes("翻訳")) {
        inJpSection = false;
        break;
      }
      if (inJpSection) {
        if (rLine.startsWith("&") || rLine.startsWith("-") || rLine.startsWith("=") || rLine.startsWith("*")) continue;
        extracted.push(rLine);
      }
    }

    if (extracted.length > 0) {
      bullets = extracted.map(l => l.replace(/^\d+[\.、\s\-]+/, "").trim()).filter(Boolean);
      const numberedText = bullets.map((b, idx) => `${idx + 1}. ${b}`).join("\n");
      return {
        extractedText: numberedText,
        bullets: bullets,
        chineseTranslations: chineseTranslations
      };
    }
  }

  // 3. 备选：普通多行文本
  const cleanLines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith("&") && !l.startsWith("-"));
  bullets = cleanLines.map(l => l.replace(/^\d+[\.、\s\-]+/, "").trim()).filter(Boolean);
  const numberedText = bullets.map((b, idx) => `${idx + 1}. ${b}`).join("\n");
  return {
    extractedText: numberedText,
    bullets: bullets,
    chineseTranslations: chineseTranslations
  };
}

function syncBulletPointsFromDescription() {
  const descInp = document.getElementById("descriptionInput");
  const container = document.getElementById("bulletPointsContainer");
  if (!descInp || !container) return;

  const rawText = descInp.value || "";

  // 1. 若商品描述内容为空，立刻清空下方全部五点描述！
  if (!rawText.trim()) {
    populateBulletPoints([]);
    return;
  }

  const parsed = extractAmpersandSection(rawText);

  // 如果粘贴进来的内容包含外层包装结构，则净化商品描述框只保留核心 5 点日文 (带 1.2.3. 序号)
  if (rawText.includes("&") || rawText.includes("日文版") || rawText.includes("中文翻译")) {
    if (parsed.extractedText && parsed.extractedText !== rawText) {
      descInp.value = parsed.extractedText;
    }
  }

  populateBulletPoints(parsed.bullets, parsed.chineseTranslations || []);
}

function reindexBulletPoints() {
  const container = document.getElementById("bulletPointsContainer");
  if (!container) return;
  const items = container.querySelectorAll(".bullet-point-item");
  items.forEach((item, idx) => {
    const numSpan = item.querySelector(".bullet-point-row span:first-child");
    const inp = item.querySelector(".bullet-point-inp");
    if (numSpan) numSpan.textContent = `${idx + 1}.`;
    if (inp) inp.placeholder = `Bullet Point ${idx + 1}`;
  });
}

function initBulletPointsManager() {
  const descInp = document.getElementById("descriptionInput");
  const addBtn = document.getElementById("addBulletPointBtn");
  const container = document.getElementById("bulletPointsContainer");

  // 输入或粘贴商品描述后，实时自动提取填入下方五点描述；清空时同步清空
  if (descInp) {
    descInp.addEventListener("input", syncBulletPointsFromDescription);
    descInp.addEventListener("change", syncBulletPointsFromDescription);
    descInp.addEventListener("paste", () => {
      setTimeout(syncBulletPointsFromDescription, 60);
    });
  }

  if (addBtn && container) {
    addBtn.addEventListener("click", () => {
      const currentCount = container.querySelectorAll(".bullet-point-item").length;
      if (currentCount >= 10) {
        showToast("最多添加 10 条 Bullet Point！", "error");
        return;
      }
      const item = document.createElement("div");
      item.className = "bullet-point-item";
      item.style.cssText = "display:flex; flex-direction:column; gap:4px;";
      item.innerHTML = `
        <div class="bullet-point-row" style="display:flex; gap:8px; align-items:center;">
          <span style="font-size:0.8rem; font-weight:600; color:var(--text-muted); width:20px;">${currentCount + 1}.</span>
          <input type="text" class="form-input bullet-point-inp" placeholder="Bullet Point ${currentCount + 1}">
          <span style="cursor:pointer; color:var(--danger); font-size:1.1rem; font-weight:bold;" title="删除" onclick="this.closest('.bullet-point-item').remove(); reindexBulletPoints();">&times;</span>
        </div>
        <div class="bullet-point-cn-hint" style="margin-left:28px; font-size:0.78rem; color:#475569; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:4px; padding:3px 8px; display:flex; align-items:center; gap:6px;">
          <span style="color:#6366f1; font-weight:600; font-size:0.75rem; flex-shrink:0;">🇨🇳 中文翻译参考:</span>
          <span class="cn-text" style="color:var(--text-muted); line-height:1.4;">(暂无翻译)</span>
        </div>
      `;
      container.appendChild(item);
      reindexBulletPoints();
    });
  }

  // 页面初始根据商品描述自动拆分联动一次
  syncBulletPointsFromDescription();
}

function initKeywordsManager() {
  const titleInp = document.getElementById("titleInput");
  const termsInp = document.getElementById("searchTermsInput");
  if (titleInp && termsInp) {
    termsInp.value = titleInp.value;
    titleInp.addEventListener("input", () => {
      termsInp.value = titleInp.value;
    });
  }
  // 标题自动级联: 输入停顿 1.2s 自动触发, 失焦时若标题已变化则立即触发
  if (titleInp) {
    titleInp.addEventListener("input", scheduleAutoTranslateTitle);
    titleInp.addEventListener("blur", () => {
      const title = titleInp.value.trim();
      if (title && title !== lastAutoTranslatedTitle) {
        clearTimeout(autoTranslateTimer);
        runTitleAiCascade(title);
      }
    });
  }
}

/**
 * 本地 Ollama AI 级联处理: 标题翻译 -> 商品标识提炼 -> 商品标识英文翻译
 * @param {string} mode   title_translation | identifier | identifier_translation
 * @param {string} btnId  触发按钮 id
 * @param {string} inpId  结果回填输入框 id
 * @param {string} source 源文本 (title_translation 用产品标题, 其余用上游字段内容)
 * @param {string} emptyHint 源文本为空时的提示
 */
// 同一按钮同时只允许一个 AI 请求, 防止并发覆盖按钮文案导致卡在"处理中"
const aiBusyButtons = new Set();

async function runAiTextProcess(mode, btnId, inpId, source, emptyHint) {
  if (!source || !source.trim()) {
    showToast(emptyHint, "error");
    return false;
  }
  const btn = document.getElementById(btnId);
  const inp = document.getElementById(inpId);
  if (!btn || !inp) return false;
  if (aiBusyButtons.has(btnId)) return false;

  aiBusyButtons.add(btnId);
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ 处理中...";
  try {
    const res = await fetch("/api/products/extract-identifier", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, title: source, content: source })
    });
    const result = await res.json();
    if (result.code === 0 && result.data?.result) {
      inp.value = result.data.result;
      // 程序赋值不触发 input 事件, 手动派发以驱动 Parent SKU 等下游联动
      inp.dispatchEvent(new Event("input", { bubbles: true }));
      showToast(`🤖 AI 处理完成: ${result.data.result}`);
      return true;
    }
    showToast(`AI 处理失败: ${result.detail || result.msg || "未知错误"}`, "error");
    return false;
  } catch (err) {
    showToast(`AI 处理异常: ${err.message}`, "error");
    return false;
  } finally {
    aiBusyButtons.delete(btnId);
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// 标题自动翻译: 输入停顿或失焦后自动触发 (标题变化时才重新翻译)
let autoTranslateTimer = null;
let lastAutoTranslatedTitle = "";

/**
 * 输入标题后全自动级联: 标题翻译 -> 商品标识提炼 -> 商品标识英文翻译
 */
async function runTitleAiCascade(title) {
  const ok1 = await runAiTextProcess(
    "title_translation", "translateTitleBtn", "titleTranslationInput",
    title, "请先填写产品标题，再进行 AI 翻译！"
  );
  if (!ok1) return;
  lastAutoTranslatedTitle = title;

  const translation = document.getElementById("titleTranslationInput")?.value.trim() || "";
  const ok2 = await runAiTextProcess(
    "identifier", "extractIdentifierBtn", "productIdentifierInput",
    translation, "请先完成标题翻译，再提炼商品标识！"
  );
  if (!ok2) return;

  const identifier = document.getElementById("productIdentifierInput")?.value.trim() || "";
  await runAiTextProcess(
    "identifier_translation", "translateIdentifierBtn", "identifierTranslationInput",
    identifier, "请先填写商品标识，再翻译成英文！"
  );

  // 标题级联完成后, 仅当系统管理配置中开启了「是否5点描述通过大模型生成」时, 才自动调用大模型生成五点描述
  if (state.aiConfig?.generate_bullets_enabled) {
    autoGenerateBullets(title);
  } else {
    console.log("五点描述大模型生成未开启 (系统管理中配置为否)，跳过生成");
  }
}

/**
 * 输入标题后自动调用大模型生成日文五点描述并回填 (提示词同 DeepSeek 助手)
 * 仅在系统管理开启「是否5点描述通过大模型生成」时调用
 * 生成来源 (本地 Ollama / 公共 API) 由管理台「AI 大模型配置」决定
 */
async function autoGenerateBullets(title) {
  if (!title || !title.trim()) return;
  // 校验配置: 只有系统管理中开启「是否5点描述通过大模型生成」时才执行
  if (!state.aiConfig?.generate_bullets_enabled) {
    return;
  }
  try {
    // 调用后端: 后端按管理台配置的来源 (local/public) 生成
    const res = await fetch("/api/products/generate-bullets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title })
    });
    const result = await res.json();
    if (result.code !== 0 || !result.data?.raw) {
      showToast(`五点描述生成失败: ${result.detail || result.msg || "未知错误"}`, "error");
      return;
    }

    // 3. 解析并回填 (复用 DeepSeek 回答的解析逻辑)
    const parsed = extractAmpersandSection(result.data.raw);
    if (parsed.extractedText && parsed.bullets.length >= 2) {
      const descInp = document.getElementById("descriptionInput");
      if (descInp) descInp.value = parsed.extractedText;
      populateBulletPoints(parsed.bullets, parsed.chineseTranslations || []);
      showToast(`🎉 AI 已自动生成 ${parsed.bullets.length} 条五点描述！`);
    } else {
      showToast("AI 生成结果解析失败，请检查五点描述区域或手动生成", "error");
    }
  } catch (err) {
    showToast(`五点描述自动生成异常: ${err.message}`, "error");
  }
}

function scheduleAutoTranslateTitle() {
  const title = document.getElementById("titleInput")?.value.trim() || "";
  if (!title || title === lastAutoTranslatedTitle) return;
  clearTimeout(autoTranslateTimer);
  autoTranslateTimer = setTimeout(() => {
    const t = document.getElementById("titleInput")?.value.trim() || "";
    if (!t || t === lastAutoTranslatedTitle) return;
    runTitleAiCascade(t);
  }, 1200);
}

function translateTitle() {
  const title = document.getElementById("titleInput")?.value.trim() || "";
  runTitleAiCascade(title);
}

function extractProductIdentifier() {
  const translation = document.getElementById("titleTranslationInput")?.value.trim() || "";
  runAiTextProcess("identifier", "extractIdentifierBtn", "productIdentifierInput", translation, "请先完成标题翻译，再提炼商品标识！");
}

function translateIdentifier() {
  const identifier = document.getElementById("productIdentifierInput")?.value.trim() || "";
  runAiTextProcess("identifier_translation", "translateIdentifierBtn", "identifierTranslationInput", identifier, "请先填写商品标识，再翻译成英文！");
}

/**
 * 从后端获取五点描述提示词 (与「📝 查看提示词」及自动生成共用同一模板, 后端为唯一来源)
 */
async function fetchBulletsPrompt() {
  const title = (document.getElementById("titleInput")?.value || "").trim();
  if (!title) {
    showToast("请先填写产品标题，再使用提示词功能！", "error");
    return null;
  }
  try {
    const res = await fetch("/api/products/ai-prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "bullets", title })
    });
    const result = await res.json();
    if (result.code === 0 && result.data?.prompt) return result.data.prompt;
    showToast(result.detail || result.msg || "获取提示词失败", "error");
  } catch (e) {
    showToast("获取提示词失败: " + e.message, "error");
  }
  return null;
}

/**
 * 将提取出来的多条 Bullet Points 及中文翻译直接整齐填入下方 5 点描述各输入框与参考栏
 */
function populateBulletPoints(bullets, chineseTranslations = []) {
  const container = document.getElementById("bulletPointsContainer");
  if (!container) return;

  const validBullets = Array.isArray(bullets) ? bullets : [];
  const validCn = Array.isArray(chineseTranslations) ? chineseTranslations : [];

  // 若为空列表，立刻清空所有五点描述输入框与中文参考
  if (validBullets.length === 0) {
    container.querySelectorAll(".bullet-point-inp").forEach(inp => {
      inp.value = "";
    });
    container.querySelectorAll(".cn-text").forEach(el => {
      el.textContent = "(暂无翻译)";
      el.style.color = "var(--text-muted)";
    });
    return;
  }

  const neededRows = Math.max(5, Math.min(validBullets.length, 10));
  let currentItems = container.querySelectorAll(".bullet-point-item");

  while (currentItems.length < neededRows) {
    const nextIdx = currentItems.length + 1;
    const item = document.createElement("div");
    item.className = "bullet-point-item";
    item.style.cssText = "display:flex; flex-direction:column; gap:4px;";
    item.innerHTML = `
      <div class="bullet-point-row" style="display:flex; gap:8px; align-items:center;">
        <span style="font-size:0.8rem; font-weight:600; color:var(--text-muted); width:20px;">${nextIdx}.</span>
        <input type="text" class="form-input bullet-point-inp" placeholder="Bullet Point ${nextIdx}">
        <span style="cursor:pointer; color:var(--danger); font-size:1.1rem; font-weight:bold;" title="删除" onclick="this.closest('.bullet-point-item').remove(); reindexBulletPoints();">&times;</span>
      </div>
      <div class="bullet-point-cn-hint" style="margin-left:28px; font-size:0.78rem; color:#475569; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:4px; padding:3px 8px; display:flex; align-items:center; gap:6px;">
        <span style="color:#6366f1; font-weight:600; font-size:0.75rem; flex-shrink:0;">🇨🇳 中文翻译参考:</span>
        <span class="cn-text" style="color:var(--text-muted); line-height:1.4;">(暂无翻译)</span>
      </div>
    `;
    container.appendChild(item);
    currentItems = container.querySelectorAll(".bullet-point-item");
  }

  currentItems.forEach((item, idx) => {
    const inp = item.querySelector(".bullet-point-inp");
    const cnEl = item.querySelector(".cn-text");

    if (inp) {
      inp.value = (idx < validBullets.length) ? validBullets[idx] : "";
    }
    if (cnEl) {
      if (idx < validCn.length && validCn[idx]) {
        cnEl.textContent = validCn[idx];
        cnEl.style.color = "#0f172a";
      } else {
        cnEl.textContent = "(暂无翻译)";
        cnEl.style.color = "var(--text-muted)";
      }
    }
  });

  reindexBulletPoints();
}

function initAiPromptAssistant() {
  const genBtn = document.getElementById("generatePromptBtn");
  if (genBtn) {
    genBtn.addEventListener("click", async () => {
      const promptText = await fetchBulletsPrompt();
      if (!promptText) return;
      copyTextToClipboard(promptText, true);
    });
  }

  // 跳转 DeepSeek 按钮 (仅复制提示词 + 打开 DeepSeek 页面, 不做自动回填)
  const jumpOnlyBtn = document.getElementById("jumpDeepSeekOnlyBtn");
  if (jumpOnlyBtn) {
    jumpOnlyBtn.addEventListener("click", async () => {
      const promptText = await fetchBulletsPrompt();
      if (!promptText) return;

      // 自动复制提示词到剪贴板
      copyTextToClipboard(promptText, false);

      // 在当前浏览器打开 DeepSeek 页面
      window.open(DEEPSEEK_TARGET_URL, "_blank");

      showToast("🚀 提示词已复制，DeepSeek 页面已打开（直接按 Ctrl+V 粘贴发送即可）！");
    });
  }
}

// DeepSeek 会话页面地址
const DEEPSEEK_TARGET_URL = "https://chat.deepseek.com/a/chat/s/7d257fd5-a7f7-482f-bec5-ba53f94f6725";

function copyTextToClipboard(text, notify = true) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      if (notify) showToast("✨ 提示词已成功生成并自动复制到剪贴板！请前往 DeepSeek 直接粘贴使用。");
    }).catch(() => {
      fallbackCopyText(text, notify);
    });
  } else {
    fallbackCopyText(text, notify);
  }
}

function fallbackCopyText(text, notify = true) {
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    const successful = document.execCommand("copy");
    if (successful && notify) {
      showToast("✨ 提示词已成功生成并自动复制到剪贴板！请前往 DeepSeek 直接粘贴使用。");
    }
  } catch (err) {
    if (notify) showToast("复制异常: " + err.message, "error");
  }
  document.body.removeChild(textArea);
}


// ============================================================================
// Initialization
// ============================================================================
document.addEventListener("DOMContentLoaded", async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const editId = urlParams.get("id");
  if (editId) {
    editingProductId = parseInt(editId, 10);
  }

  await loadSystemSettings();
  initGlobalTooltip();
  renderProductGallery();
  initAttributeBoxManagers();
  initBatchOperations();
  initBulletPointsManager();
  initKeywordsManager();
  bindIdentifierToParentSku();
  initAiPromptAssistant();

  if (editingProductId) {
    await loadProductForEdit(editingProductId);
  }

  const fileInput = document.getElementById("globalFileInput");
  if (fileInput) fileInput.addEventListener("change", handleFileSelect);

  const batchExtraFileInput = document.getElementById("batchExtraFileInput");
  if (batchExtraFileInput) batchExtraFileInput.addEventListener("change", handleBatchExtraFileSelect);

  const clearAllExtraBtn = document.getElementById("clearAllExtraBtn");
  if (clearAllExtraBtn) clearAllExtraBtn.addEventListener("click", clearAllExtraImages);

  const extractIdentifierBtn = document.getElementById("extractIdentifierBtn");
  if (extractIdentifierBtn) extractIdentifierBtn.addEventListener("click", extractProductIdentifier);

  const translateTitleBtn = document.getElementById("translateTitleBtn");
  if (translateTitleBtn) translateTitleBtn.addEventListener("click", translateTitle);

  const translateIdentifierBtn = document.getElementById("translateIdentifierBtn");
  if (translateIdentifierBtn) translateIdentifierBtn.addEventListener("click", translateIdentifier);

  // 📝 按钮: 查看各 AI 字段当前使用的 Ollama 提示词
  document.querySelectorAll(".js-view-prompt").forEach(btn => {
    btn.addEventListener("click", () => viewOllamaPrompt(btn.dataset.mode));
  });

  const saveBtn = document.getElementById("saveProductBtn");
  if (saveBtn) saveBtn.addEventListener("click", () => saveProduct());
});

/**
 * 查看指定模式当前实际使用的 Ollama 提示词 (取当前输入框内容)
 */
async function viewOllamaPrompt(mode) {
  const title = (document.getElementById("titleInput")?.value || "").trim();
  const contentMap = {
    title_translation: null,
    identifier: (document.getElementById("titleTranslationInput")?.value || "").trim(),
    identifier_translation: (document.getElementById("productIdentifierInput")?.value || "").trim()
  };
  const content = contentMap[mode];
  try {
    const res = await fetch("/api/products/ai-prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, title, content })
    });
    const result = await res.json();
    if (result.code !== 0 || !result.data?.prompt) {
      showToast(result.detail || result.msg || "获取提示词失败", "error");
      return;
    }
    showPromptModal(mode, result.data.prompt);
  } catch (e) {
    showToast("获取提示词失败: " + e.message, "error");
  }
}

/**
 * 提示词查看弹窗
 */
function showPromptModal(mode, promptText) {
  const modeNames = {
    title_translation: "标题翻译",
    identifier: "商品标识提炼",
    identifier_translation: "商品标识英文翻译",
    bullets: "五点描述生成"
  };
  let modal = document.getElementById("promptViewModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "promptViewModal";
    modal.style.cssText = "position:fixed; inset:0; background:rgba(15,23,42,0.55); z-index:9999; display:flex; align-items:center; justify-content:center; padding:24px;";
    modal.innerHTML = `
      <div style="background:#fff; border-radius:12px; max-width:680px; width:100%; max-height:80vh; display:flex; flex-direction:column; box-shadow:0 20px 50px rgba(0,0,0,0.3);">
        <div style="display:flex; justify-content:space-between; align-items:center; padding:14px 18px; border-bottom:1px solid #e2e8f0;">
          <strong style="font-size:0.95rem;">📝 大模型提示词 (五点描述生成)</strong>
          <button id="promptModalCloseBtn" type="button" style="border:none; background:none; font-size:1.1rem; cursor:pointer; color:#64748b;">✕</button>
        </div>
        <pre id="promptModalText" style="margin:0; padding:16px 18px; overflow:auto; white-space:pre-wrap; word-break:break-all; font-size:0.82rem; line-height:1.6; color:#334155; background:#f8fafc; flex:1;"></pre>
        <div style="padding:10px 18px; border-top:1px solid #e2e8f0; text-align:right;">
          <button id="promptModalOkBtn" type="button" class="btn btn-primary btn-sm">关闭</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    // 点击遮罩或关闭按钮关闭
    modal.addEventListener("click", e => { if (e.target === modal) modal.style.display = "none"; });
    modal.querySelector("#promptModalCloseBtn").addEventListener("click", () => { modal.style.display = "none"; });
    modal.querySelector("#promptModalOkBtn").addEventListener("click", () => { modal.style.display = "none"; });
  }
  modal.querySelector("strong").textContent = `📝 大模型提示词 (${modeNames[mode] || mode})`;
  modal.querySelector("#promptModalText").textContent = promptText;
  modal.style.display = "flex";
}

/* ====================================================================
 * 全局 fetch 拦截: 会话过期静默跳转登录页
 * 旧页面停留后 session 过期, 接口返回 401 时不弹"请先登录"提示,
 * 直接跳转 /login?next=<当前页>, 登录成功后由 login 页回跳原页面。
 * 说明: 登录页不加载本文件; /api/auth/login 失败返回 HTTP 200 + code 401,
 * 不会误触发本拦截。
 * ==================================================================== */
(function () {
  if (window.__authRedirectInstalled) return;
  window.__authRedirectInstalled = true;
  const _origFetch = window.fetch.bind(window);
  window.fetch = async function (...args) {
    const res = await _origFetch(...args);
    if (res && res.status === 401 && !window.__redirectingToLogin) {
      window.__redirectingToLogin = true;
      const next = encodeURIComponent(location.pathname + location.search);
      window.location.href = "/login?next=" + next;
    }
    return res;
  };
})();
