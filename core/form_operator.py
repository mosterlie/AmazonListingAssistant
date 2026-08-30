"""
表单高精度自动化填充与交互操作引擎 (FormOperator)
支持标准表单控件以及 AntDesign, ElementUI, Arco, Bootstrap 等现代前端组件库的智能交互。
"""
import os
import time
from typing import Dict, Any, List, Optional, Union
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

    def wait_for_value(self, field_label_or_selector: str, expected_text: str, timeout_ms: int = 10000) -> bool:
        """
        等待表单项、标签或组件加载出指定数值（例如等待选择店铺后，站点选择自动变为'日本'）
        :param field_label_or_selector: 字段名称（如 '站点选择'）或选择器
        :param expected_text: 期望包含的数值文本（如 '日本'）
        :param timeout_ms: 超时时间（毫秒）
        :return: 是否在超时前成功出现
        """
        js_code = """
        (args) => {
            const { identifier, expected } = args;
            
            // 查找字段容器
            const formItems = Array.from(document.querySelectorAll('.ant-form-item, .el-form-item, .arco-form-item, .form-group, .flex, div'));
            for (const fi of formItems) {
                const txt = (fi.innerText || fi.textContent || '').trim();
                if (txt.includes(identifier)) {
                    if (txt.includes(expected)) return { match: true, currentText: txt };
                    // 检查输入框值
                    const inp = fi.querySelector('input, textarea');
                    if (inp && (inp.value || '').includes(expected)) return { match: true, currentText: inp.value };
                }
            }
            return { match: false };
        }
        """
        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            try:
                res = self.page.evaluate(js_code, {"identifier": field_label_or_selector, "expected": expected_text})
                if res and res.get("match"):
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(300)

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
                if any(k in attr_lower for k in ["尺寸", "サイズ", "size"]):
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
            
            const trs = Array.from(table.querySelectorAll("tbody tr, .ant-table-tbody tr.ant-table-row"));
            const targetTr = trs.find(tr => {
                const tds = Array.from(tr.querySelectorAll("td"));
                const cellTexts = tds.map(td => td.innerText.replace(/\\s+/g, " ").trim());
                
                // 检查所有过滤条件
                for (const [k, v] of Object.entries(filters)) {
                    const matchAny = cellTexts.some(txt => txt.includes(v) || v.includes(txt));
                    if (!matchAny) return false;
                }
                return true;
            });
            
            if (!targetTr) return { success: false, msg: "target row not found" };
            
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
                    setVal(tds[2]?.querySelector("input"), fieldVal);
                } else if (fk === "ean" || fk === "upc" || fk === "gtin") {
                    setVal(tds[3]?.querySelector("input"), fieldVal);
                } else if (fk.includes("描述") || fk === "description") {
                    setVal(tds[5]?.querySelector("input, textarea"), fieldVal);
                } else if (fk.includes("价") || fk === "price") {
                    setVal(tds[6]?.querySelector("input"), fieldVal);
                } else if (fk.includes("数") || fk === "quantity" || fk === "stock" || fk === "qty") {
                    setVal(tds[7]?.querySelector("input"), fieldVal);
                } else if (fk.includes("促销价") || fk === "sale_price") {
                    setVal(tds[8]?.querySelector("input"), fieldVal);
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
        timeout_ms: int = 10000
    ) -> bool:
        """
        为指定变体图片区域（如 {'颜色': 'dd', '尺寸': 'tt'}）上传单张或多张图片（主图/Swatch/附图）
        :param filter_criteria: 变体匹配条件，如 {"颜色": "dd", "尺寸": "tt"}
        :param image_path: 本地图片文件的绝对路径（或路径列表）
        :param image_type: 图片类型: 'main' (主图), 'swatch' (色块图), 'extra' (附图)
        :param upload_mode: 上传模式: 'local' (本地图片)
        :param timeout_ms: 超时时间（毫秒）
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

                target_box = body_block.locator(".p8").nth(type_idx)
                if target_box.count() == 0:
                    self.page.wait_for_timeout(300)
                    continue

                # 4. 点击上传触发区域 (主图/Swatch 点 .img-out，附图点 '选择图片' 按钮)
                if type_idx == 2:
                    trigger = target_box.locator("button, .ant-btn").filter(has_text="选择图片").first
                else:
                    trigger = target_box.locator(".img-out, .single-image, img").first
                
                if trigger.count() == 0:
                    trigger = target_box

                trigger.click()
                self.page.wait_for_timeout(300)

                # 5. 监听文件选择器并点击下拉菜单中的【本地图片】
                with self.page.expect_file_chooser(timeout=4000) as fc_info:
                    local_opt = self.page.locator(".ant-dropdown:not([style*='display: none']) .ant-dropdown-menu-item").filter(has_text="本地图片").first
                    local_opt.click()

                file_chooser = fc_info.value
                file_chooser.set_files(abs_files)

                # 6. 严格回显校验与错误侦测（双重保障机制：DOM状态回显 + 错误Toast侦测 + 轮询等待）
                verify_start = time.time()
                verify_timeout = 10.0  # 等待网络上传与服务端返回，最长 10 秒
                
                while (time.time() - verify_start) < verify_timeout:
                    # 检查是否有错误提示 Toast（如网络异常、图片过大等）
                    error_msg_el = self.page.locator(".ant-message-error, .ant-notification-notice-error")
                    if error_msg_el.count() > 0:
                        error_text = error_msg_el.first.inner_text()
                        print(f"⚠️ [上传失败侦测] 检测到页面报错信息: {error_text}")
                        return False

                    # 检查主图 / Swatch 的云端上传回显
                    if type_idx in [0, 1]:
                        img_el = target_box.locator(".img-out img, img.img-css")
                        no_status_el = target_box.locator(".no-img-status")
                        
                        if img_el.count() > 0 and no_status_el.count() == 0:
                            img_src = img_el.first.get_attribute("src") or ""
                            # 判定标准：包含有效的 http/https 链接，且不是默认占位图 (addImg/kong)
                            if "http" in img_src and not any(p in img_src for p in ["addImg", "kong"]):
                                return True
                    else:
                        # 检查附图的云端上传回显（计数与真实图片条目）
                        imgs = target_box.locator(".img-out img, img.img-css, .flex-wrap img")
                        if imgs.count() >= len(abs_files):
                            valid_imgs = 0
                            for k in range(imgs.count()):
                                s = imgs.nth(k).get_attribute("src") or ""
                                if "http" in s and not any(p in s for p in ["addImg", "kong"]):
                                    valid_imgs += 1
                            if valid_imgs >= len(abs_files):
                                return True

                    self.page.wait_for_timeout(300)

                # 轮询超时后仍未检测到云端图片回显，视为网络超时或上传失败
                print(f"❌ [上传超时] 在 {verify_timeout}s 内未检测到云端图片成功回显，判定上传失败！")
                return False
            except Exception as e:
                pass
            self.page.wait_for_timeout(300)

        return False

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
