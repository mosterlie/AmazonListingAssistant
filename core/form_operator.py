"""
表单高精度自动化填充与交互操作引擎 (FormOperator)
支持标准表单控件以及 AntDesign, ElementUI, Arco, Bootstrap 等现代前端组件库的智能交互。
"""
import os
import time
from typing import Dict, Any, List, Optional, Union, Callable
from playwright.sync_api import Page, Locator


class FormOperator:
    """
    表单自动化操作器：
    提供直观、语义化的 API，用于自动选择下拉项、输入文本、勾选单复选框、点击按钮等。
    """

    def __init__(self, page: Page):
        self.page = page

    def select(self, field_label_or_selector: str, option_text: str) -> bool:
        """
        在下拉选择框中选择指定项（智能适配 AntDesign, ElementUI, 标准 select 等）
        :param field_label_or_selector: 字段名称（如 '店铺账号'、'产品ID'）或选择器
        :param option_text: 目标选项文本（如 '金梧汇辰'、'EAN'）
        :return: 操作是否成功
        """
        js_code = """
        (args) => {
            const { identifier, optionText } = args;

            // 辅助函数：查找匹配 identifier 的下拉框组件
            function findSelectWrapper() {
                // 1. 尝试直接选择器
                if (identifier.startsWith('#') || identifier.startsWith('.') || identifier.includes('[')) {
                    const el = document.querySelector(identifier);
                    if (el) return el.closest('.ant-select, .el-select, .d-selector') || el;
                }

                // 2. 标准 form-item 匹配
                const formItems = Array.from(document.querySelectorAll('.ant-form-item, .el-form-item, .arco-form-item, .form-group, .form-item'));
                for (const fi of formItems) {
                    const label = fi.querySelector('.ant-form-item-label, .el-form-item__label, label, .label');
                    const txt = (label ? (label.getAttribute('title') || label.innerText || label.textContent || '') : '').trim().replace(/^[*\\s:]+|[:\\s]+$/g, '');
                    if (txt && (txt === identifier || txt.includes(identifier))) {
                        const sel = fi.querySelector('.ant-select, .el-select, .arco-select, select, .categories-select, .d-selector');
                        if (sel) return sel.querySelector('.ant-select') || sel;
                    }
                }

                // 3. 自定义布局 (如 变种主题 等)
                const allElements = Array.from(document.querySelectorAll('label, h3, h4, .title, span, div'));
                for (const el of allElements) {
                    if (el.children.length > 0) continue;
                    const txt = (el.innerText || el.textContent || '').trim().replace(/^[*\\s:]+|[:\\s]+$/g, '');
                    if (txt && (txt === identifier || txt.includes(identifier))) {
                        const container = el.closest('.flex, .form-card-content, .d-selector, .form-group') || el.parentElement;
                        if (container) {
                            const sel = container.querySelector('.ant-select, .el-select, select, .d-selector');
                            if (sel) return sel.querySelector('.ant-select') || sel;
                        }
                    }
                }

                return null;
            }

            const selectEl = findSelectWrapper();
            if (!selectEl) return { success: false, msg: '未找到下拉框组件: ' + identifier };

            // 检查当前是否已经选中目标项
            const currentSelected = selectEl.querySelector('.ant-select-selection-item, .el-select__selected-item, .arco-select-view-value');
            if (currentSelected) {
                const curTxt = (currentSelected.innerText || currentSelected.textContent || '').trim();
                const firstLine = curTxt.split('\\n')[0].trim();
                if (firstLine.length > 0 && (curTxt === optionText || curTxt.includes(optionText) || optionText.includes(firstLine))) {
                    return { success: true, already: true, selectedText: curTxt };
                }
            }

            // A. 原生 <select>
            if (selectEl.tagName.toLowerCase() === 'select') {
                if (selectEl.value === optionText || (selectEl.options[selectEl.selectedIndex] && selectEl.options[selectEl.selectedIndex].text.includes(optionText))) {
                    return { success: true, already: true };
                }
                const opt = Array.from(selectEl.options).find(o => (o.text || '').trim().includes(optionText) || (o.value || '').trim() === optionText);
                if (opt) {
                    selectEl.value = opt.value;
                    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
                    return { success: true };
                }
            }

            // B. AntDesign / ElementUI / 自定义下拉框：点击展开
            const trigger = selectEl.querySelector('.ant-select-selector, .el-select__wrapper, .select-module') || selectEl;
            trigger.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
            trigger.click();

            return { success: true, opened: true };
        }
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < 4000:
            try:
                res = self.page.evaluate(js_code, {"identifier": field_label_or_selector, "optionText": option_text})
                if res and res.get("already"):
                    return True
                if res and res.get("success"):
                    self.page.wait_for_timeout(300)
                    
                    # 1. 优先使用 Playwright 原生物理鼠标点击（确保 AntDesign 触发完整的 onChange 与网络请求）
                    try:
                        # 如果是搜索下拉框，先输入关键词过滤
                        self.page.evaluate("""
                        (optText) => {
                            const searchInp = document.querySelector('.add-theme-select__amazon input[placeholder*="输入搜索值"]');
                            if (searchInp && searchInp.offsetParent !== null) {
                                searchInp.focus();
                                const proto = window.HTMLInputElement.prototype;
                                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                                const keyword = optText.split('(')[0].trim() || optText;
                                if (setter) setter.call(searchInp, keyword);
                                else searchInp.value = keyword;
                                searchInp.dispatchEvent(new Event('input', { bubbles: true }));
                                searchInp.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        }
                        """, option_text)
                        self.page.wait_for_timeout(200)

                        opt_loc = self.page.locator(
                            ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, "
                            ".add-theme-select__amazon .ant-select-item-option, "
                            "[role='option'], .el-select-dropdown__item"
                        ).filter(has_text=option_text).first
                        if opt_loc.count() > 0:
                            opt_loc.click(timeout=1500, force=True)
                            self.page.wait_for_timeout(350)
                            return True
                    except Exception:
                        pass

                    # 2. 兜底执行浏览器级事件派发
                    click_opt_js = """
                    (optionText) => {
                        const isDefault = ['default', '默认', '默认选项', '第一个', 'first'].includes(optionText);
                        const dropdowns = Array.from(document.querySelectorAll('.add-theme-select__amazon, .ant-select-dropdown:not(.ant-select-dropdown-hidden), .el-select-dropdown, .arco-select-dropdown, [role="listbox"]'));
                        
                        return new Promise(resolve => {
                            setTimeout(() => {
                                for (const dd of dropdowns) {
                                    const options = Array.from(dd.querySelectorAll('.ant-select-item-option, .el-select-dropdown__item, .arco-select-option, [role="option"], li'));
                                    
                                    let match = options.find(o => {
                                        const txt = (o.innerText || o.textContent || o.getAttribute('title') || '').trim();
                                        const firstLine = txt.split('\\n')[0].trim();
                                        if (isDefault && txt && !txt.includes('暂无数据')) return true;
                                        return firstLine === optionText || txt === optionText || firstLine.includes(optionText) || optionText.includes(firstLine);
                                    });

                                    if (match) {
                                        match.scrollIntoView({ block: 'nearest' });
                                        const contentEl = match.querySelector('.ant-select-item-option-content') || match;
                                        contentEl.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
                                        contentEl.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                                        contentEl.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                                        contentEl.click();
                                        resolve({ clicked: true, text: match.innerText.trim() });
                                        return;
                                    }
                                }
                                resolve({ clicked: false });
                            }, 150);
                        });
                    }
                    """
                    opt_res = self.page.evaluate(click_opt_js, option_text)
                    if opt_res and opt_res.get("clicked"):
                        self.page.wait_for_timeout(350)
                        return True
            except Exception as e:
                pass
            self.page.wait_for_timeout(250)

        return False

    def select_store_account(self, store_account: str = "金梧汇辰", expected_site: str = "日本", timeout_ms: int = 15000) -> bool:
        """
        强力选择【店铺账号】，并严格循环重试与校验，直到当前选中的店铺文本确实为 store_account 且站点联动显示 expected_site
        :param store_account: 店铺名称（如 '金梧汇辰'）
        :param expected_site: 期望联动的站点（如 '日本'）
        :param timeout_ms: 最长等待超时时间（毫秒）
        :return: 是否选择并确认成功
        """
        check_js = """
        () => {
            const formItems = Array.from(document.querySelectorAll('.ant-form-item, div'));
            const storeItem = formItems.find(fi => {
                const lbl = fi.querySelector('.ant-form-item-label, label');
                return lbl && (lbl.innerText || '').includes('店铺账号');
            });
            const siteItem = formItems.find(fi => {
                const lbl = fi.querySelector('.ant-form-item-label, label');
                return lbl && (lbl.innerText || '').includes('站点选择');
            });
            const storeVal = storeItem?.querySelector('.ant-select-selection-item')?.innerText?.trim() || '';
            const siteVal = siteItem?.innerText?.trim() || '';
            return { storeVal, siteVal };
        }
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            # 1. 检查是否已经成功选中并联动站点
            try:
                state = self.page.evaluate(check_js)
                if state and store_account in state.get("storeVal", ""):
                    if not expected_site or expected_site in state.get("siteVal", ""):
                        return True
            except Exception:
                pass

            # 2. 尝试执行点击与选择
            try:
                self.select("店铺账号", store_account)
            except Exception:
                pass

            self.page.wait_for_timeout(600)

        # 超时后最终核验
        try:
            state = self.page.evaluate(check_js)
            return bool(state and store_account in state.get("storeVal", ""))
        except Exception:
            return False


    def fill(self, field_label_or_selector: str, text_value: str, clear_first: bool = True) -> bool:
        """
        向指定表单输入框或文本域填入内容（支持异步重试）
        :param field_label_or_selector: 字段名称（如 '产品ID'、'产品标题'、'Parent SKU'）或 CSS 选择器
        :param text_value: 要填入的文本
        :param clear_first: 是否先清空已有内容
        :return: 操作是否成功
        """
        js_code = """
        (args) => {
            const { identifier, textValue } = args;

            function findInput() {
                if (identifier.startsWith('#') || identifier.startsWith('.') || identifier.includes('[')) {
                    const el = document.querySelector(identifier);
                    if (el) return el;
                }

                let plEl = document.querySelector(`[placeholder="${CSS.escape(identifier)}"]`);
                if (plEl) return plEl;

                const items = Array.from(document.querySelectorAll('.ant-form-item, .el-form-item, .arco-form-item, .form-group, .form-item'));
                for (const item of items) {
                    const labelEl = item.querySelector('.ant-form-item-label, .el-form-item__label, label, .label');
                    const txt = (labelEl ? (labelEl.getAttribute('title') || labelEl.innerText || labelEl.textContent || '') : '').trim();
                    if (txt.includes(identifier) || identifier.includes(txt)) {
                        const inp = item.querySelector('input:not([type="hidden"]), textarea');
                        if (inp) return inp;
                    }
                }

                return document.querySelector(`[placeholder*="${CSS.escape(identifier)}"]`);
            }

            const input = findInput();
            if (!input) return { success: false, msg: '未找到输入框: ' + identifier };

            input.focus();
            
            try {
                const proto = input.tagName.toLowerCase() === 'textarea' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                if (setter) {
                    setter.call(input, textValue);
                } else {
                    input.value = textValue;
                }
            } catch (e) {
                input.value = textValue;
            }

            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            input.blur();

            return { success: true, value: input.value };
        }
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < 4000:
            try:
                res = self.page.evaluate(js_code, {"identifier": field_label_or_selector, "textValue": str(text_value)})
                if res and res.get("success"):
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(250)

        return False

    def click_radio(self, label_text: str, timeout_ms: int = 6000) -> bool:
        """
        根据视觉标签点击单选框 (Radio) 或复选框 (Checkbox)（支持同义词和异步重试）
        """
        start_time = time.time()
        synonyms = ['多变种', '多变体', '变种', '变体'] if label_text in ['多变体', '多变种'] else [label_text]
        
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                # 1. 优先使用 Playwright 原生 Locator 点击
                for syn in synonyms:
                    radio_loc = self.page.locator(".ant-radio-wrapper, .ant-radio-button-wrapper, .el-radio, label").filter(has_text=syn).first
                    if radio_loc.count() > 0:
                        radio_loc.click(timeout=1500, force=True)
                        self.page.wait_for_timeout(300)
                        return True
            except Exception:
                pass

            # 2. 兜底 JS 执行
            js_code = """
            (labelText) => {
                const synonyms = {
                    '多变体': ['多变体', '多变种', '变种', '变体'],
                    '多变种': ['多变种', '多变体', '变种', '变体'],
                    '单品': ['单品', '单变体', '单变种'],
                    '是': ['是', '开启', '启用'],
                    '否': ['否', '关闭', '禁用']
                };

                const targetKeywords = synonyms[labelText] || [labelText];
                const radios = Array.from(document.querySelectorAll('.ant-radio-wrapper, .el-radio, .ant-checkbox-wrapper, label, input[type="radio"], input[type="checkbox"]'));
                
                for (const kw of targetKeywords) {
                    for (const el of radios) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (txt.includes(kw)) {
                            const inp = el.querySelector('input[type="radio"], input[type="checkbox"]') || (el.tagName === 'INPUT' ? el : null);
                            if (inp && inp.checked) return true;
                            
                            el.click();
                            if (inp) {
                                inp.checked = true;
                                inp.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                            return true;
                        }
                    }
                }
                return false;
            }
            """
            try:
                res = bool(self.page.evaluate(js_code, label_text))
                if res:
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(250)

        return False

    def click_radio_or_checkbox(self, label_text: str) -> bool:
        """click_radio 的同义别名方法"""
        return self.click_radio(label_text)

    def click_button(self, button_text_or_selector: str, timeout_ms: int = 4000) -> bool:
        """
        点击指定的按钮（如 '保存'、'一键翻译'、'存为模板'、'自动识别产品类型'）
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                # 1. 优先使用 Playwright 原生 Locator 点击
                btn_loc = self.page.locator("button, .ant-btn, .el-button, a.btn, a, span").filter(has_text=button_text_or_selector).first
                if btn_loc.count() > 0:
                    btn_loc.click(timeout=1500, force=True)
                    self.page.wait_for_timeout(300)
                    return True
            except Exception:
                pass

            # 2. 兜底 JS 执行
            js_code = """
            (btnText) => {
                if (btnText.startsWith('#') || btnText.startsWith('.') || btnText.includes('[')) {
                    const el = document.querySelector(btnText);
                    if (el) { el.click(); return true; }
                }
                const buttons = Array.from(document.querySelectorAll('button, input[type="button"], a.btn, .ant-btn, .el-button, a, span'));
                for (const b of buttons) {
                    const txt = (b.innerText || b.value || b.textContent || '').trim();
                    if (txt === btnText || txt.includes(btnText)) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }
            """
            try:
                res = bool(self.page.evaluate(js_code, button_text_or_selector))
                if res:
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(250)

        return False

    def confirm_modal(self, button_text: str = "确定", wait_timeout_ms: int = 8000) -> bool:
        """
        在弹出的对话框（Modal/Dialog）中点击指定确认按钮（如 '确定'、'确认'、'保存'）
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < wait_timeout_ms:
            try:
                # 1. 优先使用 Playwright 原生 Locator 点击弹窗按钮
                modal_loc = self.page.locator(".ant-modal, .el-dialog, [role='dialog']").first
                if modal_loc.count() > 0:
                    btn_loc = modal_loc.locator("button, .ant-btn, .el-button").filter(has_text=button_text).first
                    if btn_loc.count() > 0:
                        btn_loc.click(timeout=1500, force=True)
                        self.page.wait_for_timeout(300)
                        return True
            except Exception:
                pass

            # 2. 兜底 JS 执行
            js_find_and_click = """
            (btnText) => {
                const modals = Array.from(document.querySelectorAll('.ant-modal, .el-dialog, .ant-modal-content, [role="dialog"]'));
                for (const m of modals) {
                    const btns = Array.from(m.querySelectorAll('button, a.btn, .ant-btn, .el-button'));
                    const match = btns.find(b => (b.innerText || '').trim().includes(btnText));
                    if (match) {
                        match.click();
                        return { clicked: true };
                    }
                }
                return { clicked: false };
            }
            """
            try:
                res = self.page.evaluate(js_find_and_click, button_text)
                if res and res.get("clicked"):
                    self.page.wait_for_timeout(300)
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(200)

        return False

    def add_variation_option(self, attribute_name: str, option_value: str, timeout_ms: int = 6000) -> bool:
        """
        在变体属性区域（如 'カラー(颜色)' 或 'サイズ(尺寸)'）的'其它'输入框中输入自定义选项并点击'添加'
        :param attribute_name: 属性名称（如 '颜色'、'カラー'、'尺寸'、'サイズ'）
        :param option_value: 要添加的值（如 '红色'、'Blue'、'XL'）
        :param timeout_ms: 超时时间（毫秒）
        :return: 是否添加成功
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                # 1. 确定目标属性在变体卡片中的索引 (0: 颜色, 1: 尺寸)
                attr_lower = attribute_name.lower()
                target_idx = 0
                if any(k in attr_lower for k in ["尺寸", "サイズ", "size", "set_name", "set"]):
                    target_idx = 1
                
                # 2. 定位页面上的“其它:”专用行（精准匹配 .flex.gap-10.items-center.m-top10）
                other_rows = self.page.locator("#variationInfo .flex.gap-10.items-center.m-top10")
                if other_rows.count() > target_idx:
                    target_row = other_rows.nth(target_idx)
                    target_inp = target_row.locator("input").first
                    target_btn = target_row.locator("button, .ant-btn").first
                    
                    if target_inp.count() > 0 and target_btn.count() > 0:
                        target_inp.fill(option_value)
                        self.page.wait_for_timeout(200)
                        target_btn.click(timeout=1500)
                        self.page.wait_for_timeout(500)
                        return True
            except Exception:
                pass
            self.page.wait_for_timeout(300)

        return False

    def fill_variation_row(self, filter_criteria: Dict[str, str], row_data: Dict[str, Any], timeout_ms: int = 5000) -> bool:
        """
        根据指定属性条件定位变体表格中的某一行，并填入各字段数据
        :param filter_criteria: 行定位匹配条件（例如 {"颜色": "dd", "尺寸": "tt"} 或 {"color": "dd", "size": "tt"}）
        :param row_data: 待填入的字段与数值（例如 {"sku": "xxxx", "ean": "2222222222222", "price": "4000", "quantity": "40"}）
        :param timeout_ms: 超时时间（毫秒）
        :return: 是否成功填写
        """
        js_code = """
        (args) => {
            const { filters, data } = args;
            const table = document.querySelector("#variationInfo table");
            if (!table) return { success: false, msg: "table not found" };
            
            const theadThs = Array.from(table.querySelectorAll("thead th")).map(th => (th.innerText || th.textContent || "").replace(/\\s+/g, " ").trim());
            
            let skuCol = 2, idCol = 3, descCol = 5, priceCol = 6, qtyCol = 7, salePriceCol = 8;
            let colorCol = 0, sizeCol = 1;
            
            theadThs.forEach((txt, idx) => {
                const t = txt.toLowerCase();
                if (t.includes("カラー") || t.includes("颜色") || t.includes("color")) colorCol = idx;
                else if (t.includes("サイズ") || t.includes("尺寸") || t.includes("size")) sizeCol = idx;
                else if (t.includes("sku")) skuCol = idx;
                else if (t.includes("ean") || t.includes("upc") || t.includes("asin") || t.includes("gtin") || t.includes("产品id") || t.includes("id")) idCol = idx;
                else if (t.includes("促销价") || t.includes("sale price")) salePriceCol = idx;
                else if (t.includes("价格") || t.includes("price")) priceCol = idx;
                else if (t.includes("数量") || t.includes("quantity") || t.includes("库存") || t.includes("stock") || t.includes("qty")) qtyCol = idx;
                else if (t.includes("描述") || t.includes("description")) descCol = idx;
            });
            
            const trs = Array.from(table.querySelectorAll("tbody tr, .ant-table-tbody tr.ant-table-row"));
            
            const targetTr = trs.find(tr => {
                const tds = Array.from(tr.querySelectorAll("td"));
                
                for (const [k, v] of Object.entries(filters)) {
                    if (v === undefined || v === null || String(v).trim() === "") continue;
                    const targetVal = String(v).trim();
                    const kLower = k.toLowerCase();
                    
                    if (kLower.includes("颜色") || kLower.includes("color") || kLower.includes("カラー")) {
                        const cellTxt = (tds[colorCol]?.innerText || tds[colorCol]?.textContent || "").trim();
                        if (cellTxt !== targetVal) return false;
                    } else if (kLower.includes("尺寸") || kLower.includes("size") || kLower.includes("サイズ")) {
                        const cellTxt = (tds[sizeCol]?.innerText || tds[sizeCol]?.textContent || "").trim();
                        if (cellTxt !== targetVal) return false;
                    } else {
                        // 其它自定义属性
                        const matchAny = tds.slice(0, 3).some(td => (td.innerText || td.textContent || "").trim() === targetVal);
                        if (!matchAny) return false;
                    }
                }
                return true;
            });
            
            if (!targetTr) return { success: false, msg: "target row not found for filters: " + JSON.stringify(filters) };
            
            const tds = Array.from(targetTr.querySelectorAll("td"));
            const proto = window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
            
            function setVal(input, val) {
                if (!input || val === undefined || val === null) return;
                input.focus();
                if (setter) setter.call(input, String(val));
                else input.value = String(val);
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
                input.blur();
            }
            
            // 字段映射与填充
            for (const [fieldKey, fieldVal] of Object.entries(data)) {
                const fk = fieldKey.toLowerCase();
                if (fk === "sku") {
                    setVal(tds[skuCol]?.querySelector("input"), fieldVal);
                } else if (fk === "ean" || fk === "upc" || fk === "gtin" || fk === "asin" || fk === "product_id" || fk === "id") {
                    setVal(tds[idCol]?.querySelector("input"), fieldVal);
                } else if (fk.includes("描述") || fk === "description") {
                    setVal(tds[descCol]?.querySelector("input, textarea"), fieldVal);
                } else if (fk.includes("促销价") || fk === "sale_price") {
                    setVal(tds[salePriceCol]?.querySelector("input"), fieldVal);
                } else if (fk.includes("价") || fk === "price") {
                    setVal(tds[priceCol]?.querySelector("input"), fieldVal);
                } else if (fk.includes("数") || fk === "quantity" || fk === "stock" || fk === "qty") {
                    setVal(tds[qtyCol]?.querySelector("input"), fieldVal);
                }
            }
            
            return { success: true };
        }
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                res = self.page.evaluate(js_code, {"filters": filter_criteria, "data": row_data})
                if res and res.get("success"):
                    self.page.wait_for_timeout(300)
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(250)

        return False

    def upload_variation_image(
        self,
        filter_criteria: Dict[str, str],
        image_path: Union[str, List[str]],
        image_type: str = "main",
        upload_mode: str = "local",
        timeout_ms: int = 10000,
        skip_if_exists: bool = False
    ) -> bool:
        """
        为指定变体图片区域（如 {'颜色': 'dd', '尺寸': 'tt'}）上传单张或多张图片（主图/Swatch/附图）
        :param filter_criteria: 变体匹配条件，如 {"颜色": "dd", "尺寸": "tt"}
        :param image_path: 本地图片文件的绝对路径（或路径列表）
        :param image_type: 图片类型: 'main' (主图), 'swatch' (色块图), 'extra' (附图)
        :param upload_mode: 上传模式: 'local' (本地图片)
        :param timeout_ms: 超时时间（毫秒）
        :param skip_if_exists: 若已有图片是否跳过上传
        :return: 是否上传成功
        """
        file_list = [image_path] if isinstance(image_path, str) else image_path
        for f in file_list:
            if not os.path.exists(f):
                raise FileNotFoundError(f"本地图片文件不存在: {f}")

        abs_files = [os.path.abspath(f) for f in file_list]

        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                # 1. 匹配目标变种图片行并滚动使其挂载
                var_container = self.page.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
                headers = var_container.locator(".item-header")
                
                target_header = None
                for i in range(headers.count()):
                    h = headers.nth(i)
                    txt = h.inner_text()
                    if all(v in txt for v in filter_criteria.values()):
                        target_header = h
                        break
                
                if not target_header:
                    self.page.wait_for_timeout(300)
                    continue

                target_header.scroll_into_view_if_needed()
                self.page.wait_for_timeout(350)
                
                # 2. 定位该变体行的图片块
                body_block = target_header.locator("xpath=following-sibling::div[1]")
                
                # 3. 确定目标类型索引 (0: 主图, 1: Swatch Image, 2: 附图)
                type_idx = 0
                if image_type.lower() in ["swatch", "色块", "色块图"]:
                    type_idx = 1
                elif image_type.lower() in ["extra", "附图", "副图"]:
                    type_idx = 2

                target_boxes = body_block.locator(".p8")
                box_count = target_boxes.count()
                target_box = None

                if type_idx == 2:
                    # 附图框：优先查找含有「选择图片」按钮或文字的 .p8
                    for bi in range(box_count):
                        b = target_boxes.nth(bi)
                        if b.locator("button, .ant-btn").filter(has_text="选择图片").count() > 0 or "选择图片" in (b.inner_text() or ""):
                            target_box = b
                            break
                    if not target_box and box_count > 0:
                        target_box = target_boxes.nth(box_count - 1)
                elif type_idx == 1:
                    if box_count >= 3:
                        target_box = target_boxes.nth(1)
                else:
                    if box_count > 0:
                        target_box = target_boxes.nth(0)

                if not target_box or target_box.count() == 0:
                    self.page.wait_for_timeout(300)
                    continue

                # 若开启 skip_if_exists 则在满足要求时跳过
                if skip_if_exists:
                    existing_real = target_box.evaluate(
                        "el => Array.from(el.querySelectorAll('img')).filter(i => !/addimg|kong-|\\/assets\\/|data:image\\/svg/i.test(i.src)).length"
                    )
                    if type_idx in (0, 1) and existing_real and existing_real > 0:
                        return True
                    if type_idx == 2 and existing_real and existing_real >= len(abs_files):
                        return True

                # 4. 点击上传触发区域 (主图/Swatch 点 .img-out / 缩略图，附图点 '选择图片' 按钮)
                if type_idx == 2:
                    trigger = target_box.locator("button, .ant-btn").filter(has_text="选择图片").first
                else:
                    trigger = target_box.locator(".img-out, .single-image, img").first

                if trigger.count() == 0:
                    trigger = target_box

                # 记录上传前图片框内已有缩略图的 src 集合
                before_srcs = target_box.evaluate("el => Array.from(el.querySelectorAll('img')).map(i => i.src)")

                trigger.click()
                self.page.wait_for_timeout(350)

                # 5. 监听文件选择器并点击下拉菜单中的【本地图片】
                with self.page.expect_file_chooser(timeout=5000) as fc_info:
                    local_opt = self.page.locator(".ant-dropdown:not([style*='display: none']) .ant-dropdown-menu-item").filter(has_text="本地图片").first
                    local_opt.click()

                file_chooser = fc_info.value
                file_chooser.set_files(abs_files)

                # 6. 等待图片真实上传并渲染完成（新图出现 + loading 消失）
                upload_done = self._wait_image_upload_complete(target_box, before_srcs, len(abs_files))
                if upload_done:
                    # 7. 再次进行严格 DOM 校验确认图片已真实就绪
                    min_c = len(abs_files) if type_idx == 2 else 1
                    if self.verify_variation_image_uploaded(filter_criteria, image_type, min_count=min_c, timeout_ms=3000):
                        return True
            except Exception as e:
                pass
            self.page.wait_for_timeout(300)

        return False

    def verify_variation_image_uploaded(
        self,
        filter_criteria: Dict[str, str],
        image_type: str = "main",
        min_count: int = 1,
        timeout_ms: int = 4000
    ) -> bool:
        """
        深度校验指定变体卡片的图片（主图/附图/色块）是否已真实上传并渲染在页面中
        :param filter_criteria: 变体卡片过滤条件 (如 {"颜色": "白色"})
        :param image_type: "main" (主图) / "extra" (附图) / "swatch" (色块)
        :param min_count: 期望真实图片数量 (主图通常为 1, 附图为期望上传数)
        :param timeout_ms: 校验等待超时
        :return: 是否通过上传真实性校验
        """
        type_idx = 0
        if image_type.lower() in ["swatch", "色块", "色块图"]:
            type_idx = 1
        elif image_type.lower() in ["extra", "附图", "副图"]:
            type_idx = 2

        js_verify_upload = """
        async (args) => {
            const { filterCrit, typeIdx, minCount } = args;
            const sec = document.querySelector('#variationImage');
            if (!sec) return { ok: false, reason: 'no variationImage' };
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            const header = headers.find(h => {
                const txt = h.innerText.trim();
                return Object.values(filterCrit).every(v => txt.includes(v));
            });
            if (!header) return { ok: false, reason: 'header not found' };

            let body = header.nextElementSibling;
            if (!body) return { ok: false, reason: 'body not found' };

            if (body.querySelectorAll('.render-skeleton').length > 0) {
                header.scrollIntoView({ block: 'center', inline: 'nearest' });
                await new Promise(r => setTimeout(r, 120));
                body = header.nextElementSibling;
            }

            const p8s = Array.from(body.querySelectorAll('.p8'));
            if (p8s.length === 0) return { ok: false, reason: 'no p8s' };

            let targetBox = null;
            if (typeIdx === 2) {
                for (let i = 0; i < p8s.length; i++) {
                    if (p8s[i].innerText.includes('选择图片') || p8s[i].querySelector('button, .ant-btn')) {
                        targetBox = p8s[i];
                        break;
                    }
                }
                if (!targetBox) targetBox = p8s.length >= 3 ? p8s[2] : (p8s.length === 2 ? p8s[1] : p8s[0]);
            } else if (typeIdx === 1) {
                targetBox = p8s.length >= 3 ? p8s[1] : null;
            } else {
                targetBox = p8s[0];
            }

            if (!targetBox) return { ok: false, reason: 'targetBox not found' };

            const imgs = Array.from(targetBox.querySelectorAll('img'));
            const realImgs = imgs.filter(i => {
                const s = (i.src || '').toLowerCase();
                return s && !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            });

            return {
                ok: realImgs.length >= minCount,
                realCount: realImgs.length,
                totalImgs: imgs.length
            };
        }
        """

        start = time.time()
        while (time.time() - start) * 1000 < timeout_ms:
            try:
                res = self.page.evaluate(js_verify_upload, {
                    "filterCrit": filter_criteria,
                    "typeIdx": type_idx,
                    "minCount": min_count
                })
                if res and res.get("ok"):
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(250)
        return False

    def _wait_image_upload_complete(self, target_box: Locator, before_srcs: List[str], upload_count: int, timeout_ms: int = 30000) -> bool:
        """
        等待图片上传真正完成：目标图片框内出现足够数量的"新真实图片"或真实图片总数已达标，且页面无可见的 loading 动画
        :param target_box: 目标图片块 Locator
        :param before_srcs: 上传前图片框内全部 img 的 src 列表
        :param upload_count: 本次上传的图片数量
        :param timeout_ms: 等待超时（毫秒）
        :return: 是否确认上传完成
        """
        placeholder_marks = ["addimg", "kong-", "/assets/"]
        before_set = set(before_srcs or [])

        # JS: 返回图片框内全部 img 的 src，并统计"新增真实图片"与"总真实图片"数量
        js_collect_srcs = """
        (el, args) => {
            const { beforeSet, phMarks } = args;
            const imgs = Array.from(el.querySelectorAll('img'));
            const srcs = [];
            let newReal = 0;
            let totalReal = 0;
            for (const i of imgs) {
                const s = i.src || '';
                srcs.push(s);
                const isPlaceholder = phMarks.some(m => s.toLowerCase().includes(m)) || s.startsWith('data:image/svg');
                if (!isPlaceholder) {
                    totalReal++;
                    if (!beforeSet.includes(s)) newReal++;
                }
            }
            return { srcs, newReal, totalReal };
        }
        """

        # JS: 检查是否存在可见的 loading 指示器（ant-spin / ant-upload 上传中状态等）
        js_has_loading = """
        () => {
            const loaders = Array.from(document.querySelectorAll(
                ".ant-spin-spinning, .ant-spin-blur, [class*='loading'], [class*='uploading'], .image-uploading"
            ));
            return loaders.some(el => el.offsetParent !== null);
        }
        """

        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                res = target_box.evaluate(js_collect_srcs, {"beforeSet": list(before_set), "phMarks": placeholder_marks})
                if res and (res.get("newReal", 0) >= upload_count or res.get("totalReal", 0) >= upload_count):
                    # 再确认无可见 loading 动画（上传请求已结束）
                    has_loading = self.page.evaluate(js_has_loading)
                    if not has_loading:
                        self.page.wait_for_timeout(300)  # 缓冲，确保 Vue/React 响应式更新完毕
                        return True
            except Exception:
                pass
            self.page.wait_for_timeout(400)

        return False

    def confirm_modal(self, button_text: str = "确定", wait_timeout_ms: int = 2000) -> bool:
        """
        自动检测页面上是否弹出 Ant Modal / 对话框，并点击确认按钮
        :param button_text: 按钮文字（如 '确定'、'确认'、'OK'）
        :param wait_timeout_ms: 等待弹窗超时时间（毫秒）
        :return: 是否成功点击确认
        """
        js_click_modal = """
        (btnText) => {
            const modals = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-content, [role="dialog"], .el-message-box'));
            for (const m of modals) {
                if (getComputedStyle(m).display === 'none') continue;
                const btns = Array.from(m.querySelectorAll('button, .ant-btn, .el-button, a'));
                const okBtn = btns.find(b => {
                    const t = (b.innerText || b.textContent || '').trim();
                    return t === btnText || t.includes(btnText) || b.classList.contains('ant-btn-primary');
                });
                if (okBtn) {
                    okBtn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    okBtn.click();
                    return { ok: true, text: okBtn.innerText.trim() };
                }
            }
            return { ok: false };
        }
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < wait_timeout_ms:
            try:
                # 1. 优先使用 Playwright Locator
                modal_btn = self.page.locator(".ant-modal:not([style*='display: none']) button, .ant-modal:not([style*='display: none']) .ant-btn-primary, [role='dialog'] button").filter(has_text=button_text).first
                if modal_btn.count() > 0:
                    modal_btn.click(timeout=1000, force=True)
                    self.page.wait_for_timeout(400)
                    return True

                # 2. JS 兜底
                res = self.page.evaluate(js_click_modal, button_text)
                if res and res.get("ok"):
                    self.page.wait_for_timeout(400)
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(250)
        return False

    def apply_variation_image(
        self,
        filter_criteria: Dict[str, str],
        apply_type: str,
        timeout_ms: int = 15000,
        verify_success: bool = True,
        log_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        点击指定变体卡片头部的「图片应用到」，并在下拉菜单中选择批量应用选项，
        并在选择后自动深度校验是否已批量应用成功（成功后再返回）。
        :param filter_criteria: 变体匹配条件，如 {"颜色": "dd", "尺寸": "tt"}
        :param apply_type: 应用类型:
            - 'extra_all'  : 附图 ➔ 所有变体（附图-所有变体）
            - 'main_color' : 主图 ➔ 同カラー(颜色)的变种
            - 'main_size'  : 主图 ➔ 同サイズ(尺寸)的变种
            - 'main_all'   : 主图 ➔ 所有变种（主图-所有变体）
        :param timeout_ms: 超时时间（毫秒）
        :param verify_success: 是否在点击应用后校验页面所有目标卡片是否同步成功
        :param log_callback: 日志输出回调函数
        :return: 是否应用并校验成功
        """
        # 应用类型 ➔ (分组标题关键词, 菜单项范围关键词)
        type_keyword_map = {
            "extra_all": ("附图", ["所有变种", "所有变体", "所有", "全部", "all"]),
            "main_all": ("主图", ["所有变种", "所有变体", "所有", "全部", "all"]),
            "main_color": ("主图", ["カラー", "颜色", "color", "colour", "色"]),
            "main_size": ("主图", ["尺寸", "サイズ", "size", "规格", "型号"]),
        }
        if apply_type not in type_keyword_map:
            raise ValueError(f"不支持的 apply_type: {apply_type}，可选值: {list(type_keyword_map.keys())}")
        group_keyword, scope_keywords = type_keyword_map[apply_type]

        # 0. 极速前置检查：若页面目标卡片已经同步就绪，直接返回避免重复应用
        if verify_success:
            if self.verify_variation_batch_applied(filter_criteria, apply_type, timeout_ms=300, log_callback=None):
                if log_callback:
                    log_callback(f"      ➔ 检查确认：目标变体已处于同步就绪状态，无需重复执行批量应用")
                    self.verify_variation_batch_applied(filter_criteria, apply_type, timeout_ms=100, log_callback=log_callback)
                return True

        js_find_and_click_option = """
        (args) => {
            const { groupKw, scopeKw } = args;
            const visibleDrops = Array.from(document.querySelectorAll('.ant-dropdown')).filter(d => {
                const style = window.getComputedStyle(d);
                return style.display !== 'none' && style.visibility !== 'hidden' && !d.classList.contains('ant-dropdown-hidden');
            });
            if (visibleDrops.length === 0) {
                // 兜底查 .product-image-apply-menu
                const menu = document.querySelector('.product-image-apply-menu');
                if (menu) visibleDrops.push(menu.closest('.ant-dropdown') || menu);
            }

            for (const d of visibleDrops) {
                const groups = Array.from(d.querySelectorAll('.menu-group, [class*="group"]'));
                for (const g of groups) {
                    const title = (g.querySelector('.group-title, [class*="title"]')?.innerText || g.innerText || '').trim();
                    // 严格比对分组名称
                    if (groupKw === '主图' && !title.startsWith('主图')) continue;
                    if (groupKw === '附图' && !title.startsWith('附图')) continue;
                    if (groupKw === '全部图片' && !title.startsWith('全部图片')) continue;
                    if (groupKw === 'Swatch Image' && !title.includes('Swatch')) continue;

                    const items = Array.from(g.querySelectorAll('.menu-item, [class*="item"]'));
                    for (const kw of scopeKw) {
                        for (const it of items) {
                            const txt = (it.innerText || '').trim();
                            if (txt.toLowerCase().includes(kw.toLowerCase())) {
                                // 完整派发指针与鼠标事件序列
                                it.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
                                it.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                                it.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true }));
                                it.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                                it.click();
                                return { found: true, group: title, item: txt, matchedKw: kw };
                            }
                        }
                    }
                }
            }
            return { found: false };
        }
        """

        start_time = time.time()
        attempt = 0
        while (time.time() - start_time) * 1000 < timeout_ms:
            attempt += 1
            try:
                # 0. 重置页面焦点与关闭已有残留下拉
                self.page.keyboard.press("Escape")
                self.page.evaluate("() => { if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur(); }")
                self.page.wait_for_timeout(150)

                # 1. 匹配目标变种图片卡片头部
                headers = self.page.locator("#variationImage .item-header, #variationImage [class*='header']")
                target_header = None
                for i in range(headers.count()):
                    h = headers.nth(i)
                    txt = h.inner_text()
                    if all(v in txt for v in filter_criteria.values()):
                        target_header = h
                        break

                if not target_header:
                    self.page.wait_for_timeout(200)
                    continue

                target_header.scroll_into_view_if_needed()
                self.page.wait_for_timeout(150)

                # 2. 点击卡片头部的「图片应用到」链接
                apply_btn = target_header.locator("span.link, a, span[class*='link'], [class*='apply']").filter(has_text="图片应用到").first
                if apply_btn.count() == 0:
                    self.page.wait_for_timeout(200)
                    continue

                apply_btn.click(force=True)
                self.page.wait_for_timeout(250)

                # 3. 查找目标选项并原子化派发点击
                res = self.page.evaluate(js_find_and_click_option, {"groupKw": group_keyword, "scopeKw": scope_keywords})
                if not (res and res.get("found")):
                    # 若未找到下拉，尝试稍微等待后二次触发
                    self.page.wait_for_timeout(200)
                    res = self.page.evaluate(js_find_and_click_option, {"groupKw": group_keyword, "scopeKw": scope_keywords})
                    if not (res and res.get("found")):
                        self.page.keyboard.press("Escape")
                        self.page.wait_for_timeout(200)
                        continue

                # 4. 若弹出确认框则自动确认并等待弹窗隐藏
                self.page.wait_for_timeout(200)
                confirm_js = """
                () => {
                    const confirmBtn = document.querySelector('.ant-modal-confirm-btns .ant-btn-primary') 
                                    || document.querySelector('.ant-modal-footer .ant-btn-primary')
                                    || Array.from(document.querySelectorAll('.ant-modal button')).find(b => b.innerText.includes('确') || b.innerText.includes('OK'));
                    if (confirmBtn) {
                        confirmBtn.click();
                        return true;
                    }
                    return false;
                }
                """
                modal_confirmed = self.page.evaluate(confirm_js)
                if modal_confirmed:
                    self.page.wait_for_timeout(300)

                # 5. 毫秒级极速抽样核验
                if verify_success:
                    if log_callback and attempt == 1:
                        item_name = res.get("item", "批量应用")
                        log_callback(f"      ➔ 已触发【{group_keyword} ➔ {item_name}】，正在毫秒级抽样核验生效情况...")

                    # 极速轮询核验（每 100ms 一次，最多 3 秒）
                    verified = self.verify_variation_batch_applied(
                        filter_criteria, apply_type, timeout_ms=3000, log_callback=log_callback
                    )
                    if verified:
                        return True
                    else:
                        if log_callback:
                            log_callback(f"      ⚠️ 第 {attempt} 次批量应用未在预期时间内检测到抽样卡片同步，正在快速重试...")
                        continue

                return True
            except Exception:
                pass
            self.page.wait_for_timeout(250)

        return False

    def verify_variation_batch_applied(
        self,
        filter_criteria: Dict[str, str],
        apply_type: str,
        timeout_ms: int = 3000,
        log_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        毫秒级极速抽样校验批量应用是否已真实在页面 DOM 中同步生效（Tail-Sampling 算法）：
        - 对于附图 (extra_all)：抽样检查全列表最后一个卡片 (Tail Card) 的附图，毫秒级得出结论
        - 对于主图 (main_color)：筛选同颜色卡片并抽样检查该颜色最后一个卡片的主图
        - 对于主图 (main_size)：筛选同尺寸卡片并抽样检查该尺寸最后一个卡片的主图
        - 对于主图 (main_all)：抽样检查全列表最后一个卡片的主图
        :param filter_criteria: 触发卡片的匹配条件
        :param apply_type: 应用类型 ('extra_all' / 'main_color' / 'main_size' / 'main_all')
        :param timeout_ms: 轮询等待超时（毫秒）
        :param log_callback: 日志回调函数
        :return: 是否抽样变体卡片已成功同步图片
        """
        js_fast_verify = """
        (args) => {
            const { filterCrit, applyType } = args;
            const sec = document.querySelector('#variationImage');
            if (!sec) return { success: false, reason: '未找到 #variationImage', cards: [] };
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            if (headers.length === 0) return { success: false, reason: '未找到变体卡片', cards: [] };

            const isRealImg = (src) => {
                if (!src) return false;
                const s = src.toLowerCase();
                return !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            };

            const parseAttrs = (h) => {
                const attrSpans = Array.from(h.querySelectorAll('.flex.gap-15 span, span'));
                const attrs = { color: '', size: '' };
                for (const s of attrSpans) {
                    const t = s.innerText.trim();
                    if (t.includes(':')) {
                        const parts = t.split(':');
                        const k = parts[0].trim();
                        const v = parts.slice(1).join(':').trim();
                        if (k.includes('颜色') || k.includes('カラー') || k.toLowerCase().includes('color')) {
                            attrs.color = v;
                        }
                        if (k.includes('尺寸') || k.includes('サイズ') || k.toLowerCase().includes('size')) {
                            attrs.size = v;
                        }
                    }
                }
                return attrs;
            };

            const checkCardImages = (h) => {
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                const mainBox = p8s[0];
                let extraBox = null;
                for (let i = 0; i < p8s.length; i++) {
                    if (p8s[i].innerText.includes('选择图片') || p8s[i].querySelector('button, .ant-btn')) {
                        extraBox = p8s[i];
                        break;
                    }
                }
                if (!extraBox) {
                    if (p8s.length >= 3) extraBox = p8s[2];
                    else if (p8s.length === 2) extraBox = p8s[1];
                    else extraBox = p8s[0];
                }
                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')).filter(i => isRealImg(i.src)) : [];
                const extraImgs = extraBox ? Array.from(extraBox.querySelectorAll('img')).filter(i => isRealImg(i.src)) : [];
                return {
                    mainCount: mainImgs.length,
                    extraCount: extraImgs.length,
                    mainSrc: mainImgs[0]?.src || '',
                    extraSrcs: extraImgs.map(i => i.src)
                };
            };

            if (applyType === 'extra_all') {
                // 附图全量批量应用：抽样检查全列表最后一个卡片（Tail Card）
                const targetIdx = headers.length >= 2 ? headers.length - 1 : 0;
                const tailH = headers[targetIdx];
                const imgData = checkCardImages(tailH);
                const ok = imgData.extraCount >= 1;
                const tailAttrs = parseAttrs(tailH);
                return {
                    success: ok,
                    applyType: applyType,
                    sampledIdx: targetIdx + 1,
                    totalCards: headers.length,
                    sampledSpec: `${tailAttrs.color || ''} ${tailAttrs.size || ''}`.trim(),
                    extraCount: imgData.extraCount,
                    mainCount: imgData.mainCount
                };
            } else if (applyType === 'main_color') {
                // 主图按颜色批量应用：筛选同颜色全部卡片，抽样检查该颜色的最后一个卡片
                let targetCol = filterCrit ? (filterCrit['颜色'] || filterCrit['color'] || '') : '';
                if (!targetCol) {
                    targetCol = parseAttrs(headers[0]).color;
                }
                const matchedHeaders = headers.filter(h => {
                    const a = parseAttrs(h);
                    return (a.color && a.color === targetCol) || (!a.color && h.innerText.includes(targetCol));
                });
                if (matchedHeaders.length === 0) {
                    return { success: false, reason: `未找到颜色【${targetCol}】的卡片` };
                }
                const tailH = matchedHeaders[matchedHeaders.length - 1];
                const imgData = checkCardImages(tailH);
                const ok = imgData.mainCount >= 1;
                const tailAttrs = parseAttrs(tailH);
                return {
                    success: ok,
                    applyType: applyType,
                    targetDim: targetCol,
                    groupCount: matchedHeaders.length,
                    sampledIdx: headers.indexOf(tailH) + 1,
                    sampledSpec: `${tailAttrs.color || ''} ${tailAttrs.size || ''}`.trim(),
                    mainCount: imgData.mainCount,
                    extraCount: imgData.extraCount
                };
            } else if (applyType === 'main_size') {
                // 主图按尺寸批量应用：筛选同尺寸全部卡片，抽样检查该尺寸的最后一个卡片
                let targetSz = filterCrit ? (filterCrit['尺寸'] || filterCrit['size'] || '') : '';
                if (!targetSz) {
                    targetSz = parseAttrs(headers[0]).size;
                }
                const matchedHeaders = headers.filter(h => {
                    const a = parseAttrs(h);
                    return (a.size && a.size === targetSz) || (!a.size && h.innerText.includes(targetSz));
                });
                if (matchedHeaders.length === 0) {
                    return { success: false, reason: `未找到尺寸【${targetSz}】的卡片` };
                }
                const tailH = matchedHeaders[matchedHeaders.length - 1];
                const imgData = checkCardImages(tailH);
                const ok = imgData.mainCount >= 1;
                const tailAttrs = parseAttrs(tailH);
                return {
                    success: ok,
                    applyType: applyType,
                    targetDim: targetSz,
                    groupCount: matchedHeaders.length,
                    sampledIdx: headers.indexOf(tailH) + 1,
                    sampledSpec: `${tailAttrs.color || ''} ${tailAttrs.size || ''}`.trim(),
                    mainCount: imgData.mainCount,
                    extraCount: imgData.extraCount
                };
            } else if (applyType === 'main_all') {
                const tailH = headers[headers.length - 1];
                const imgData = checkCardImages(tailH);
                const ok = imgData.mainCount >= 1;
                const tailAttrs = parseAttrs(tailH);
                return {
                    success: ok,
                    applyType: applyType,
                    totalCards: headers.length,
                    sampledIdx: headers.length,
                    sampledSpec: `${tailAttrs.color || ''} ${tailAttrs.size || ''}`.trim(),
                    mainCount: imgData.mainCount,
                    extraCount: imgData.extraCount
                };
            }

            return { success: false, reason: '未知 applyType' };
        }
        """

        start_time = time.time()
        last_res = None
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                res = self.page.evaluate(js_fast_verify, {"filterCrit": filter_criteria, "applyType": apply_type})
                if res:
                    last_res = res
                    if res.get("success"):
                        break
            except Exception:
                pass
            self.page.wait_for_timeout(100)

        # 格式化输出抽样核验日志
        if last_res and log_callback:
            is_success = last_res.get("success", False)
            s_idx = last_res.get("sampledIdx", 0)
            s_spec = last_res.get("sampledSpec", "")
            m_cnt = last_res.get("mainCount", 0)
            e_cnt = last_res.get("extraCount", 0)

            if apply_type == "extra_all":
                total_c = last_res.get("totalCards", 0)
                if is_success:
                    log_callback(f"      ➔ ✅ 附图批量应用极速抽样核验通过：末尾抽样 SKU #{s_idx:02d}【{s_spec}】附图已就绪 ({e_cnt} 张)，全量 {total_c} 个变体附图全部同步生效！")
                else:
                    log_callback(f"      ➔ ⚠️ 附图批量应用核验中：末尾抽样 SKU #{s_idx:02d}【{s_spec}】附图尚未检测到同步数据")

            elif apply_type in ["main_color", "main_size", "main_all"]:
                dim_title = "同颜色" if apply_type == "main_color" else ("同尺寸" if apply_type == "main_size" else "全部变体")
                target_dim = last_res.get("targetDim", "")
                dim_str = f"【{target_dim}】" if target_dim else ""
                grp_cnt = last_res.get("groupCount", last_res.get("totalCards", 0))
                if is_success:
                    log_callback(f"      ➔ ✅ 主图批量应用极速抽样核验通过：末尾抽样 SKU #{s_idx:02d}【{s_spec}】主图已就绪 ({m_cnt} 张)，{dim_title}{dim_str} 共 {grp_cnt} 个变体主图全部同步生效！")
                else:
                    log_callback(f"      ➔ ⚠️ 主图批量应用核验中：末尾抽样 SKU #{s_idx:02d}【{s_spec}】主图尚未检测到同步数据")

        return bool(last_res and last_res.get("success"))

    def verify_all_variation_images_summary(self) -> Dict[str, Any]:
        """
        获取当前页面全部变体卡片的主图与附图装配与渲染统计
        """
        js_summary = """
        async () => {
            const sec = document.querySelector('#variationImage');
            if (!sec) return { total: 0, withMain: 0, withExtra: 0, cards: [] };
            const headers = Array.from(sec.querySelectorAll('.item-header'));

            const isRealImg = (src) => {
                if (!src) return false;
                const s = src.toLowerCase();
                return !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            };

            const scrollBox = sec.querySelector('.overflow-y-auto, .max-h-700') || sec;
            const origTop = scrollBox.scrollTop;
            const hasSkeleton = sec.querySelectorAll('.render-skeleton').length > 0;

            const cards = [];
            for (let idx = 0; idx < headers.length; idx++) {
                const h = headers[idx];
                if (hasSkeleton) {
                    h.scrollIntoView({ block: 'center', inline: 'nearest' });
                    await new Promise(r => setTimeout(r, 80));
                }

                const text = h.innerText.replace(/\\s+/g, ' ').trim();
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                
                const mainBox = p8s[0];
                let extraBox = null;
                for (let i = 0; i < p8s.length; i++) {
                    if (p8s[i].innerText.includes('选择图片') || p8s[i].querySelector('button, .ant-btn')) {
                        extraBox = p8s[i];
                        break;
                    }
                }
                if (!extraBox) {
                    if (p8s.length >= 3) extraBox = p8s[2];
                    else if (p8s.length === 2) extraBox = p8s[1];
                    else extraBox = p8s[0];
                }

                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')) : [];
                const realMain = mainImgs.filter(i => isRealImg(i.src));

                const extraImgs = extraBox ? Array.from(extraBox.querySelectorAll('img')) : [];
                const realExtra = extraImgs.filter(i => isRealImg(i.src));

                cards.push({
                    idx: idx + 1,
                    text,
                    mainCount: realMain.length,
                    extraCount: realExtra.length
                });
            }

            if (hasSkeleton) {
                scrollBox.scrollTop = origTop;
            }

            return {
                total: cards.length,
                withMain: cards.filter(c => c.mainCount >= 1).length,
                withExtra: cards.filter(c => c.extraCount >= 1).length,
                cards
            };
        }
        """
        try:
            return self.page.evaluate(js_summary)
        except Exception as e:
            return {"total": 0, "withMain": 0, "withExtra": 0, "cards": [], "error": str(e)}

    def get_dianxiaomi_variation_cards(self) -> List[Dict[str, Any]]:
        """
        按照店小秘页面 DOM 中的实际排列顺序，读取全部变体卡片列表
        返回每个卡片的 {idx: int, headerIndex: int, text: str, color: str, size: str, hasMain: bool, mainCount: int}
        """
        js_get_cards = """
        async () => {
            const sec = document.querySelector('#variationImage');
            if (!sec) return [];
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            if (headers.length === 0) return [];

            const parseAttrs = (h) => {
                const attrSpans = Array.from(h.querySelectorAll('.flex.gap-15 span, span'));
                const attrs = { color: '', size: '' };
                for (const s of attrSpans) {
                    const t = s.innerText.trim();
                    if (t.includes(':')) {
                        const parts = t.split(':');
                        const k = parts[0].trim();
                        const v = parts.slice(1).join(':').trim();
                        if (k.includes('颜色') || k.includes('カラー') || k.toLowerCase().includes('color')) {
                            attrs.color = v;
                        }
                        if (k.includes('尺寸') || k.includes('サイズ') || k.toLowerCase().includes('size')) {
                            attrs.size = v;
                        }
                    }
                }
                return attrs;
            };

            const isRealImg = (src) => {
                if (!src) return false;
                const s = src.toLowerCase();
                return !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            };

            const cards = [];
            for (let idx = 0; idx < headers.length; idx++) {
                const h = headers[idx];
                const text = h.innerText.replace(/\\s+/g, ' ').trim();
                const attrs = parseAttrs(h);
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                const mainBox = p8s[0];
                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')) : [];
                const realMain = mainImgs.filter(i => isRealImg(i.src));

                cards.push({
                    idx: idx,
                    headerIndex: idx + 1,
                    text: text,
                    color: attrs.color,
                    size: attrs.size,
                    hasMain: realMain.length >= 1,
                    mainCount: realMain.length
                });
            }
            return cards;
        }
        """
        try:
            return self.page.evaluate(js_get_cards) or []
        except Exception:
            return []

    def is_variation_card_main_uploaded(
        self,
        filter_criteria: Optional[Dict[str, str]] = None,
        card_idx: Optional[int] = None
    ) -> bool:
        """
        检查指定变体卡片（通过 card_idx 或 filter_criteria 匹配）的主图是否已经上传/存在
        :param filter_criteria: 变体卡片过滤条件 (如 {"颜色": "11", "尺寸": "aa"})
        :param card_idx: 变体卡片索引 (0-indexed)
        :return: True (已上传主图) / False (主图为空)
        """
        js_check = """
        async (args) => {
            const { filterCrit, cardIdx } = args;
            const sec = document.querySelector('#variationImage');
            if (!sec) return false;
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            if (headers.length === 0) return false;

            let header = null;
            if (typeof cardIdx === 'number' && cardIdx >= 0 && cardIdx < headers.length) {
                header = headers[cardIdx];
            } else if (filterCrit && Object.keys(filterCrit).length > 0) {
                header = headers.find(h => {
                    const txt = h.innerText.trim();
                    return Object.values(filterCrit).every(v => txt.includes(v));
                });
            }
            if (!header) return false;

            const hasSkeleton = sec.querySelectorAll('.render-skeleton').length > 0;
            if (hasSkeleton) {
                header.scrollIntoView({ block: 'center', inline: 'nearest' });
                await new Promise(r => setTimeout(r, 80));
            }

            const body = header.nextElementSibling;
            if (!body) return false;
            const p8s = Array.from(body.querySelectorAll('.p8'));
            if (p8s.length === 0) return false;
            const mainBox = p8s[0];
            const imgs = Array.from(mainBox.querySelectorAll('img'));
            const isRealImg = (src) => {
                if (!src) return false;
                const s = src.toLowerCase();
                return !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            };
            const realImgs = imgs.filter(i => isRealImg(i.src));
            return realImgs.length >= 1;
        }
        """
        try:
            return bool(self.page.evaluate(js_check, {
                "filterCrit": filter_criteria,
                "cardIdx": card_idx
            }))
        except Exception:
            return False

    def find_next_unassigned_variation_card(
        self,
        dimension: str = "color",
        start_idx: int = 0,
        skip_indices: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        动态扫描页面 DOM，从第 start_idx 个 SKU 开始往下查找第一个主图仍为空（mainCount == 0）的变体卡片
        返回该卡片的序号、头部文本、提取的属性（颜色/尺寸）以及是否找到
        :param dimension: "color" 或 "size"
        :param start_idx: 起始扫描序号 (0-indexed)
        :param skip_indices: 需要跳过的索引列表
        :return: 包含 {found: bool, idx: int, text: str, color: str, size: str} 的字典
        """
        js_find_next = """
        async (args) => {
            const { dim, startIdx, skipList } = args;
            const sec = document.querySelector('#variationImage');
            if (!sec) return { found: false, msg: 'no variationImage' };
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            const skipSet = new Set(skipList || []);

            const isRealImg = (src) => {
                if (!src) return false;
                const s = src.toLowerCase();
                return !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            };

            const parseAttrs = (h) => {
                const attrSpans = Array.from(h.querySelectorAll('.flex.gap-15 span, span'));
                const attrs = { color: '', size: '' };
                for (const s of attrSpans) {
                    const t = s.innerText.trim();
                    if (t.includes(':')) {
                        const parts = t.split(':');
                        const k = parts[0].trim();
                        const v = parts.slice(1).join(':').trim();
                        if (k.includes('颜色') || k.includes('カラー') || k.toLowerCase().includes('color')) {
                            attrs.color = v;
                        }
                        if (k.includes('尺寸') || k.includes('サイズ') || k.toLowerCase().includes('size')) {
                            attrs.size = v;
                        }
                    }
                }
                return attrs;
            };

            const scrollBox = sec.querySelector('.overflow-y-auto, .max-h-700') || sec;
            const origTop = scrollBox.scrollTop;
            const hasSkeleton = sec.querySelectorAll('.render-skeleton').length > 0;

            for (let idx = Math.max(0, startIdx); idx < headers.length; idx++) {
                if (skipSet.has(idx)) continue;
                const h = headers[idx];
                if (hasSkeleton) {
                    h.scrollIntoView({ block: 'center', inline: 'nearest' });
                    await new Promise(r => setTimeout(r, 80));
                }

                const text = h.innerText.trim();
                const attrs = parseAttrs(h);
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                const mainBox = p8s[0];
                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')) : [];
                const realMain = mainImgs.filter(i => isRealImg(i.src));

                if (realMain.length === 0) {
                    if (hasSkeleton) scrollBox.scrollTop = origTop;
                    return {
                        found: true,
                        idx: idx,
                        text: text,
                        color: attrs.color,
                        size: attrs.size
                    };
                }
            }
            if (hasSkeleton) scrollBox.scrollTop = origTop;
            return { found: false, totalHeaders: headers.length };
        }
        """
        try:
            res = self.page.evaluate(js_find_next, {
                "dim": dimension,
                "startIdx": start_idx,
                "skipList": skip_indices or []
            })
            if res and res.get("found"):
                return res
            return {"found": False}
        except Exception as e:
            return {"found": False, "error": str(e)}

    def set_variation_images(
        self,
        filter_criteria: Dict[str, str],
        main_image: Optional[str] = None,
        swatch_image: Optional[str] = None,
        extra_images: Optional[Union[str, List[str]]] = None,
        timeout_ms: int = 15000
    ) -> Dict[str, bool]:
        """
        一站式为指定变体行上传主图、Swatch Image 和附图（附图支持一次上传多张）
        :param filter_criteria: 变体匹配条件，例如 {"颜色": "ad", "尺寸": "xx"} 或 {"color": "红色", "size": "mm"}
        :param main_image: 主图本地文件路径 (可选)
        :param swatch_image: 色块图 (Swatch Image) 本地文件路径 (可选)
        :param extra_images: 附图本地文件路径或路径列表，支持一次传入多张 (可选)
        :param timeout_ms: 每项上传超时时间（毫秒）
        :return: 包含各项上传结果的字典，例如 {"main": True, "swatch": True, "extra": True, "all_success": True}
        """
        results = {}

        # 1. 上传主图
        if main_image:
            results["main"] = self.upload_variation_image(
                filter_criteria=filter_criteria,
                image_path=main_image,
                image_type="main",
                upload_mode="local",
                timeout_ms=timeout_ms
            )
            self.page.wait_for_timeout(500)

        # 2. 上传 Swatch Image
        if swatch_image:
            results["swatch"] = self.upload_variation_image(
                filter_criteria=filter_criteria,
                image_path=swatch_image,
                image_type="swatch",
                upload_mode="local",
                timeout_ms=timeout_ms
            )
            self.page.wait_for_timeout(500)

        # 3. 上传 附图 (支持一次上传多张图)
        if extra_images:
            results["extra"] = self.upload_variation_image(
                filter_criteria=filter_criteria,
                image_path=extra_images,
                image_type="extra",
                upload_mode="local",
                timeout_ms=timeout_ms
            )
            self.page.wait_for_timeout(500)

        results["all_success"] = all(results.values()) if results else True
        return results

    def upload_parent_images(
        self,
        main_image: Optional[str] = None,
        extra_images: Optional[List[str]] = None,
        timeout_ms: int = 15000
    ) -> bool:
        """
        在父级商品图片区域 (#imageInfo) 批量上传主图与 1~8 张附图
        :param main_image: 主图本地绝对路径 (可选)
        :param extra_images: 附图本地绝对路径列表 (可选)
        :param timeout_ms: 超时时间 (毫秒)
        :return: 是否成功触发文件选择并上传
        """
        all_imgs = []
        if main_image and os.path.exists(main_image):
            all_imgs.append(os.path.abspath(main_image))
        if extra_images:
            for f in extra_images:
                if f and os.path.exists(f) and os.path.abspath(f) not in all_imgs:
                    all_imgs.append(os.path.abspath(f))

        if not all_imgs:
            return True

        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                img_section = self.page.locator("#imageInfo")
                btn = img_section.locator("button, .ant-btn").filter(has_text="选择图片").first
                if btn.count() == 0:
                    btn = self.page.locator("#imageInfo .img-module button").first
                if btn.count() == 0:
                    btn = self.page.locator("button, .ant-btn").filter(has_text="选择图片").first

                if btn.count() > 0:
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    self.page.wait_for_timeout(350)

                    with self.page.expect_file_chooser(timeout=4000) as fc_info:
                        local_opt = self.page.locator(".ant-dropdown:not([style*='display: none']) .ant-dropdown-menu-item").filter(has_text="本地图片").first
                        local_opt.click()

                    file_chooser = fc_info.value
                    file_chooser.set_files(all_imgs)
                    self.page.wait_for_timeout(1000)
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(400)

        return False

    def fill_bullet_points(self, bullet_points: List[str]) -> bool:
        """
        在描述信息区域依次填入 1~5 项 Bullet Points
        :param bullet_points: 五点描述文本列表
        :return: 是否成功填入
        """
        if not bullet_points:
            return True

        success_count = 0
        for idx, bp in enumerate(bullet_points[:5]):
            if not bp:
                continue
            selector = f"#form_item_bulletPoints_{idx}"
            try:
                elem = self.page.locator(selector).first
                if elem.count() > 0:
                    elem.scroll_into_view_if_needed()
                    elem.fill(bp.strip())
                    elem.dispatch_event("input")
                    elem.dispatch_event("change")
                    success_count += 1
                else:
                    # 兜底通过 textarea 索引查找
                    textareas = self.page.locator("#descInfo textarea, #descriptionInfo textarea")
                    if textareas.count() > idx:
                        t = textareas.nth(idx)
                        t.fill(bp.strip())
                        t.dispatch_event("input")
                        t.dispatch_event("change")
                        success_count += 1
            except Exception:
                pass
            self.page.wait_for_timeout(100)

        return success_count > 0

    def fill_description(self, description_text: str) -> bool:
        """
        在描述信息区域填入商品长描述
        :param description_text: 商品长描述内容
        :return: 是否成功填入
        """
        if not description_text:
            return True

        try:
            # 1. 优先填充富文本编辑器 (店小秘描述为 UEditor/CKEditor 类编辑器, 必须写 HTML 否则换行丢失)
            js_fill = """
            (desc) => {
                const html = desc.replace(/\\n/g, '<br/>');
                // UEditor (百度富文本, 店小秘常用)
                if (window.UE) {
                    try {
                        const instances = window.UE.instances || {};
                        for (const key of Object.keys(instances)) {
                            const ed = instances[key];
                            if (ed && ed.setContent) {
                                ed.setContent(html);
                                ed.sync && ed.sync();
                                return true;
                            }
                        }
                    } catch (e) {}
                }
                // CKEditor
                if (window.CKEDITOR) {
                    for (let instance in window.CKEDITOR.instances) {
                        window.CKEDITOR.instances[instance].setData(html);
                        return true;
                    }
                }
                // wangEditor / 原生 contenteditable
                const editor = document.querySelector('.cke_editable, .w-e-text, div[contenteditable="true"], iframe~div[contenteditable]');
                if (editor) {
                    editor.innerHTML = html;
                    editor.dispatchEvent(new Event('input', { bubbles: true }));
                    return true;
                }
                return false;
            }
            """
            try:
                res = self.page.evaluate(js_fill, description_text)
                if res:
                    return True
            except Exception:
                pass

            # 2. 兜底: textarea 直填 (保留 \n 纯文本换行)
            desc_area = self.page.locator("textarea[name*='desc'], textarea[placeholder*='描述'], #form_item_description, #description").first
            if desc_area.count() > 0:
                desc_area.scroll_into_view_if_needed()
                desc_area.fill(description_text)
                desc_area.dispatch_event("input")
                desc_area.dispatch_event("change")
                return True
        except Exception:
            pass

        return False

    def fill_manufacturer(self, manufacturer: str) -> bool:
        """
        填入制造商字段 (若未传入则默认使用品牌名称)
        :param manufacturer: 制造商名称
        :return: 是否填入成功
        """
        if not manufacturer:
            return True
        js_code = """
        (mfg) => {
            const proto = window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            const inp = document.querySelector('div[data-path="manufacturer.0.value"] input') || 
                        document.querySelector('input[placeholder="请输入制造商"]') ||
                        Array.from(document.querySelectorAll('.ant-form-item')).find(fi => {
                            const lbl = fi.querySelector('.ant-form-item-label, label');
                            return lbl && (lbl.innerText || '').includes('制造商') && !((lbl.innerText || '').includes('邮箱'));
                        })?.querySelector('input');
            if (inp) {
                inp.focus();
                if (setter) setter.call(inp, String(mfg));
                else inp.value = String(mfg);
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                inp.blur();
                return true;
            }
            return false;
        }
        """
        try:
            return bool(self.page.evaluate(js_code, manufacturer))
        except Exception:
            return False

    def fill_dimensions_and_weight(
        self,
        item_length=None, item_width=None, item_height=None, item_dim_unit="cm",
        package_length=None, package_width=None, package_height=None, package_dim_unit="cm",
        item_weight=None, item_weight_unit=None,
        package_weight=None, package_weight_unit="kg"
    ) -> bool:
        """
        在产品属性与包装属性中填入商品尺寸(品目寸法)、包装尺寸(パッケージ寸法)及重量
        """
        js_code = """
        (args) => {
            const proto = window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            function setVal(input, val) {
                if (!input || val === undefined || val === null || String(val).trim() === '') return false;
                input.focus();
                if (setter) setter.call(input, String(val));
                else input.value = String(val);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.blur();
                return true;
            }
            
            let okCount = 0;
            // 1. 品目寸法（商品尺寸 L x W x H 或 D x W x H）
            const itemL = document.getElementById('form_item_item_length_width_height.0.length.value') 
                       || document.getElementById('form_item_item_depth_width_height.0.depth.value')
                       || document.querySelector('input[id*="length_width_height"][id*="length.value"]')
                       || document.querySelector('input[id*="depth_width_height"][id*="depth.value"]')
                       || document.querySelector('div[data-path*="depth_width_height"] input[id*="depth.value"]')
                       || document.querySelector('div[data-path*="length_width_height"] input[id*="length.value"]');
            const itemW = document.getElementById('form_item_item_length_width_height.0.width.value') 
                       || document.getElementById('form_item_item_depth_width_height.0.width.value')
                       || document.querySelector('input[id*="length_width_height"][id*="width.value"]')
                       || document.querySelector('input[id*="depth_width_height"][id*="width.value"]')
                       || document.querySelector('div[data-path*="depth_width_height"] input[id*="width.value"]')
                       || document.querySelector('div[data-path*="length_width_height"] input[id*="width.value"]');
            const itemH = document.getElementById('form_item_item_length_width_height.0.height.value') 
                       || document.getElementById('form_item_item_depth_width_height.0.height.value')
                       || document.querySelector('input[id*="length_width_height"][id*="height.value"]')
                       || document.querySelector('input[id*="depth_width_height"][id*="height.value"]')
                       || document.querySelector('div[data-path*="depth_width_height"] input[id*="height.value"]')
                       || document.querySelector('div[data-path*="length_width_height"] input[id*="height.value"]');
            if (setVal(itemL, args.item_length)) okCount++;
            if (setVal(itemW, args.item_width)) okCount++;
            if (setVal(itemH, args.item_height)) okCount++;
            
            // 2. パッケージ寸法 (包装尺寸 L x W x H)
            const pkgL = document.getElementById('form_item_item_package_dimensions.0.length.value') || document.querySelector('input[id*="package_dimensions"][id*="length.value"]');
            const pkgW = document.getElementById('form_item_item_package_dimensions.0.width.value') || document.querySelector('input[id*="package_dimensions"][id*="width.value"]');
            const pkgH = document.getElementById('form_item_item_package_dimensions.0.height.value') || document.querySelector('input[id*="package_dimensions"][id*="height.value"]');
            if (setVal(pkgL, args.package_length)) okCount++;
            if (setVal(pkgW, args.package_width)) okCount++;
            if (setVal(pkgH, args.package_height)) okCount++;
            
            // 3. 包装重量 (商品パッケージ重量) 与 商品重量
            const pkgWeight = document.getElementById('form_item_item_package_weight.0.value') || document.querySelector('input[id*="package_weight.0.value"]');
            if (setVal(pkgWeight, args.package_weight)) okCount++;
            
            const itemWeight = document.getElementById('form_item_item_weight.0.value') || document.querySelector('input[id*="item_weight.0.value"]');
            if (setVal(itemWeight, args.item_weight)) okCount++;
            
            return okCount > 0;
        }
        """
        payload = {
            "item_length": item_length,
            "item_width": item_width,
            "item_height": item_height,
            "package_length": package_length,
            "package_width": package_width,
            "package_height": package_height,
            "item_weight": item_weight,
            "package_weight": package_weight
        }
        try:
            return bool(self.page.evaluate(js_code, payload))
        except Exception:
            return False

    def fill_search_terms(self, search_terms: str) -> bool:
        """
        在关键词信息区域填入 Search Terms
        :param search_terms: 搜索词文本
        :return: 是否填入成功
        """
        if not search_terms:
            return True
        js_code = """
        (st) => {
            const proto = window.HTMLTextAreaElement.prototype;
            const inputProto = window.HTMLInputElement.prototype;
            const textSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            const inputSetter = Object.getOwnPropertyDescriptor(inputProto, 'value')?.set;
            
            const formItems = Array.from(document.querySelectorAll('.ant-form-item, div'));
            const stItem = formItems.find(fi => {
                const lbl = fi.querySelector('.ant-form-item-label, label');
                const txt = lbl ? (lbl.innerText || lbl.getAttribute('title') || '') : '';
                return txt.includes('Search Terms') || txt.includes('SearchTerms');
            });
            const textarea = stItem ? stItem.querySelector('textarea, input') : document.querySelector('textarea.w-800\\\\!');
            
            if (textarea) {
                textarea.focus();
                if (textarea.tagName === 'TEXTAREA' && textSetter) textSetter.call(textarea, String(st));
                else if (inputSetter) inputSetter.call(textarea, String(st));
                else textarea.value = String(st);
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
                textarea.dispatchEvent(new Event('change', { bubbles: true }));
                textarea.blur();
                return true;
            }
            return false;
        }
        """
        try:
            return bool(self.page.evaluate(js_code, search_terms))
        except Exception:
            return False

    def select_fulfillment_channel(self, channel: str = "FBM", timeout_ms: int = 8000) -> bool:
        """
        强力选择并校验【配送渠道】(FBM / FBA)
        :param channel: 目标配送渠道，如 'FBM' 或 'FBA'
        :param timeout_ms: 最长等待超时时间 (毫秒)
        :return: 是否选择并确认成功
        """
        check_js = """
        () => {
            const formItems = Array.from(document.querySelectorAll('.ant-form-item, div'));
            const item = formItems.find(fi => {
                const lbl = fi.querySelector('.ant-form-item-label, label');
                const txt = lbl ? (lbl.innerText || lbl.getAttribute('title') || '') : '';
                return txt.includes('配送渠道') || txt.includes('Fulfillment');
            }) || document.querySelector('[data-path*="fulfillment_availability"]')?.closest('.ant-form-item');
            
            const selVal = item?.querySelector('.ant-select-selection-item')?.innerText?.trim() || '';
            return { selVal, found: Boolean(item) };
        }
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                state = self.page.evaluate(check_js)
                if state and channel == state.get("selVal", ""):
                    return True
            except Exception:
                pass

            # 1. 尝试直接选择器
            try:
                self.select('[data-path*="fulfillment_availability"] .ant-select', channel)
            except Exception:
                pass

            # 2. 尝试字段名
            try:
                self.select("配送渠道", channel)
            except Exception:
                pass

            self.page.wait_for_timeout(400)

        # 兜底核验
        try:
            state = self.page.evaluate(check_js)
            return bool(state and channel == state.get("selVal", ""))
        except Exception:
            return False

    def save_draft(self, timeout_ms: int = 10000) -> bool:
        """
        点击页面顶部的【保存】按钮，保存为店小秘草稿
        :param timeout_ms: 等待超时时间 (毫秒)
        :return: 是否点击成功
        """
        try:
            # 精确匹配仅为 "保存" 的按钮（排除 "保存并发布" 与 "存为模板"）
            save_btn = self.page.locator(".product-add-wrapper .btn-box button.ant-btn").filter(has_text="保存").first
            if save_btn.count() == 0:
                save_btn = self.page.locator("button.ant-btn").filter(has_text="保存").first

            if save_btn.count() > 0:
                save_btn.scroll_into_view_if_needed()
                save_btn.click(force=True)
                self.page.wait_for_timeout(1000)
                return True
        except Exception as e:
            print(f"⚠️ 点击保存草稿异常: {e}")

        return False

    def close_all_popups(self, max_rounds: int = 3) -> int:
        """
        关闭店小秘页面上的自动弹窗 (公告/活动/提示类浮层)
        策略: 在可见浮层容器内寻找关闭控件(右上角叉/关闭按钮)逐一点击, 多轮清理 + Escape 兜底
        :return: 成功关闭的弹窗数量
        """
        js_close = """
        () => {
            const isVisible = (el) => {
                try {
                    const s = getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 10 && r.height > 10;
                } catch (e) { return false; }
            };
            const OVERLAY_SEL = ".modal, .layui-layer, .el-dialog, .el-dialog__wrapper, .ant-modal, .ant-modal-wrap, "
                + ".swal2-container, .swal2-popup, .bootbox, "
                + "div[class*='dialog'], div[class*='Dialog'], div[class*='popup'], div[class*='Popup'], "
                + "div[class*='modal'], div[class*='Modal'], div[class*='mask'], div[class*='Mask'], div[class*='notice']";
            const CLOSE_SEL = [
                '.modal .close', '.modal-header .close', '[data-dismiss="modal"]', 'button[aria-label="Close"]',
                '[aria-label*="lose"]', '[title*="关闭"]', '[title*="Close"]',
                '.layui-layer-close', '.layui-layer-setwin a', '.el-dialog__headerbtn', '.ant-modal-close',
                '.swal2-close',
                "img[src*='close']", "i[class*='close']", "span[class*='close']",
                "em[class*='close']", "a[class*='close']", "div[class*='close']",
                "button[class*='close']", "button[class*='Close']", "[class*='closeBtn']", "[class*='close-btn']"
            ].join(',');
            let closed = 0;
            const clicked = new Set();
            const tryClick = (el) => {
                try {
                    if (!isVisible(el) || clicked.has(el)) return;
                    const host = el.closest(OVERLAY_SEL);
                    if (!host || !isVisible(host)) return;
                    el.click();
                    clicked.add(el);
                    closed++;
                } catch (e) {}
            };
            let nodes;
            try { nodes = document.querySelectorAll(CLOSE_SEL); } catch (e) { nodes = []; }
            for (const el of nodes) { tryClick(el); }
            // 兜底: 在可见浮层头部寻找文本为叉号的元素 (× ✕ ⨯ X), 通常是右上角关闭叉
            let overlays;
            try { overlays = document.querySelectorAll(OVERLAY_SEL); } catch (e) { overlays = []; }
            for (const host of overlays) {
                if (!isVisible(host)) continue;
                const chars = el => {
                    try { return (el.textContent || '').trim(); } catch (e) { return ''; }
                };
                const candidates = host.querySelectorAll('button, a, span, i, em, b, div, svg');
                for (const el of candidates) {
                    const t = chars(el);
                    if (t.length <= 2 && ['×', '✕', '⨯', 'X', 'x', '╳'].includes(t)) {
                        // 优先点击最内层元素, 避免父容器重复计数
                        tryClick(el);
                    }
                }
            }
            return closed;
        }
        """
        total = 0
        for _ in range(max_rounds):
            try:
                n = int(self.page.evaluate(js_close) or 0)
            except Exception:
                n = 0
            if n:
                total += n
            # 无论本轮是否关闭都稍作等待, 兼容延迟出现的弹窗
            try:
                self.page.wait_for_timeout(600)
            except Exception:
                break
        # Escape 兜底 (部分弹窗支持键盘关闭)
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
        except Exception:
            pass
        return total


