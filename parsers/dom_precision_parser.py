"""
高精度 DOM 嗅探与表单字段结构化解析引擎
"""
import json
from typing import Dict, Any, List, Optional
from playwright.sync_api import Page

try:
    from .base_parser import BasePageParser
except (ImportError, ValueError):
    from base_parser import BasePageParser


class DOMPrecisionParser(BasePageParser):
    """
    高精度 DOM 嗅探与元素解析器：
    利用多层级视觉与结构融合算法，将页面中的输入框、下拉框、单复选框、按钮、文件上传点等交互元素，
    精准还原为带视觉 Label、Placeholder、定位器与当前值的结构化字典。
    """

    def is_match(self) -> bool:
        return True

    def extract(self) -> Dict[str, Any]:
        """对当前页面进行高精度全量 DOM 扫描并返回结构化数据"""
        return self.scan_page()

    def scan_page(self) -> Dict[str, Any]:
        """
        深度遍历当前页面 DOM 树，提取所有结构化交互字段
        """
        js_code = """
        () => {
            // 辅助函数：提取元素的最佳视觉文字标签 (Label)
            function findVisualLabel(el) {
                // 1. 标准 <label for="...">
                if (el.id) {
                    try {
                        const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        if (label && (label.innerText || label.textContent).trim()) {
                            return (label.innerText || label.textContent).trim().replace(/^[*\\s:]+|[:\\s]+$/g, '');
                        }
                    } catch(e) {}
                }

                // 2. 包裹当前元素的父级 <label>
                const parentLabel = el.closest('label');
                if (parentLabel && (parentLabel.innerText || parentLabel.textContent).trim()) {
                    const fullTxt = (parentLabel.innerText || parentLabel.textContent).trim();
                    const selfVal = el.value || '';
                    return fullTxt.replace(selfVal, '').trim().replace(/^[*\\s:]+|[:\\s]+$/g, '');
                }

                // 3. 向上遍历祖先节点，寻找真实的表单项容器 (支持 AntDesign, ElementUI, Arco, TDesign, Bootstrap)
                let curr = el.parentElement;
                while (curr && curr !== document.body) {
                    const cls = typeof curr.className === 'string' ? curr.className : '';
                    if (
                        curr.classList.contains('ant-form-item') ||
                        curr.classList.contains('el-form-item') ||
                        curr.classList.contains('arco-form-item') ||
                        curr.classList.contains('t-form__item') ||
                        curr.classList.contains('form-group') ||
                        curr.classList.contains('form-item') ||
                        curr.classList.contains('formItem') ||
                        (cls.includes('form-item') && !cls.includes('in-form-item')) ||
                        (cls.includes('formItem') && !cls.includes('inFormItem')) ||
                        (cls.includes('form-group'))
                    ) {
                        const labelEl = curr.querySelector('.ant-form-item-label, .el-form-item__label, .arco-form-item-label, .t-form__label, label, .form-label, .label, [class*="form-item-label"], [class*="formItemLabel"]');
                        if (labelEl) {
                            const txt = (labelEl.getAttribute('title') || labelEl.innerText || labelEl.textContent || '').trim();
                            if (txt) {
                                return txt.replace(/^[*\\s:]+|[:\\s]+$/g, '');
                            }
                        }
                    }
                    curr = curr.parentElement;
                }

                // 4. aria-label / aria-labelledby / title
                if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
                if (el.getAttribute('title')) return el.getAttribute('title').trim();
                if (el.getAttribute('aria-labelledby')) {
                    const ref = document.getElementById(el.getAttribute('aria-labelledby'));
                    if (ref && (ref.innerText || ref.textContent).trim()) {
                        return (ref.innerText || ref.textContent).trim().replace(/^[*\\s:]+|[:\\s]+$/g, '');
                    }
                }

                // 5. 左侧或上方邻近的文字兄弟节点 / 父级前置兄弟节点 (Table/Grid 键值对)
                let prev = el.previousElementSibling;
                while (prev) {
                    const txt = (prev.innerText || prev.textContent || '').trim();
                    if (txt && txt.length <= 30) {
                        return txt.replace(/^[*\\s:]+|[:\\s]+$/g, '');
                    }
                    prev = prev.previousElementSibling;
                }
                if (el.parentElement && el.parentElement.previousElementSibling) {
                    const prevSibling = el.parentElement.previousElementSibling;
                    const txt = (prevSibling.innerText || prevSibling.textContent || '').trim();
                    if (txt && txt.length <= 30) {
                        return txt.replace(/^[*\\s:]+|[:\\s]+$/g, '');
                    }
                }

                // 6. 兜底使用 placeholder 或 name
                return el.placeholder || el.name || el.title || '';
            }

            // 辅助函数：生成稳定唯一的 CSS 选择器
            function generateCssSelector(el) {
                if (el.id && !/\\d{4,}/.test(el.id)) {
                    return `#${CSS.escape(el.id)}`;
                }
                if (el.name) {
                    return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
                }
                if (el.placeholder) {
                    return `${el.tagName.toLowerCase()}[placeholder="${CSS.escape(el.placeholder)}"]`;
                }

                const path = [];
                let curr = el;
                while (curr && curr.nodeType === Node.ELEMENT_NODE && curr !== document.body) {
                    let selector = curr.tagName.toLowerCase();
                    if (curr.id && !/\\d{4,}/.test(curr.id)) {
                        selector = `#${CSS.escape(curr.id)}`;
                        path.unshift(selector);
                        break;
                    } else if (curr.className && typeof curr.className === 'string') {
                        const classes = curr.className.split(/\\s+/)
                            .filter(c => c && !c.includes(':') && !/^[0-9_]/.test(c) && !c.startsWith('is-') && !c.startsWith('active'))
                            .slice(0, 2);
                        if (classes.length > 0) {
                            selector += '.' + classes.map(c => CSS.escape(c)).join('.');
                        }
                    }
                    
                    let siblingIndex = 1;
                    let sibling = curr.previousElementSibling;
                    while (sibling) {
                        if (sibling.tagName === curr.tagName) siblingIndex++;
                        sibling = sibling.previousElementSibling;
                    }
                    selector += `:nth-of-type(${siblingIndex})`;
                    path.unshift(selector);
                    curr = curr.parentElement;
                }
                return path.join(' > ');
            }

            // 辅助函数：生成 Playwright 最佳视觉定位器代码
            function generateVisualLocator(el, label, placeholder) {
                if (placeholder) {
                    return `get_by_placeholder("${placeholder.replace(/"/g, '\\\\"')}")`;
                }
                if (label && !label.startsWith('未命名字段')) {
                    return `get_by_label("${label.replace(/"/g, '\\\\"')}")`;
                }
                if (el.innerText && el.innerText.trim()) {
                    return `get_by_text("${el.innerText.trim().slice(0, 25).replace(/"/g, '\\\\"')}")`;
                }
                return `locator("${generateCssSelector(el).replace(/"/g, '\\\\"')}")`;
            }

            const result = {
                page_info: {
                    title: document.title,
                    url: location.href,
                    timestamp: new Date().toISOString()
                },
                fields: [],
                buttons: [],
                uploaders: [],
                sections: []
            };

            // 1. 扫描所有表单输入控件与自定义选择组件 (input, textarea, select, 自定义分类/级联选择框, 开关, 富文本等)
            const inputSelector = 'input:not([type="hidden"]):not([type="file"]), textarea, select, .categories-select, .ant-cascader-picker, .ant-picker:not(:has(input)), .el-cascader:not(:has(input)), [class*="categories-select"], [role="combobox"]:not(input):not(select), [role="switch"]:not(input), [contenteditable="true"]';
            const inputs = document.querySelectorAll(inputSelector);
            let validIndex = 0;
            inputs.forEach((el) => {
                const isCustom = !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
                // 如果自定义容器内部已经包含了 input/textarea/select，则由内部原生 input 处理，避免重复
                if (isCustom && el.querySelector('input:not([type="hidden"]), textarea, select')) {
                    return;
                }

                // 忽略不可见元素 (但保留 opacity:0 的自定义下拉框原生 input)
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || (rect.width === 0 && rect.height === 0)) {
                    return;
                }

                validIndex++;
                const label = findVisualLabel(el);
                let placeholder = el.placeholder || '';
                
                // 智能嗅探 AntDesign / ElementUI / 自定义分类选择框 placeholder
                if (!placeholder) {
                    const selectParent = el.closest('.ant-select, .el-select, .arco-select, .t-select, .categories-select');
                    if (selectParent) {
                        const plEl = selectParent.querySelector('.ant-select-selection-placeholder, .el-select__placeholder, .arco-select-view-placeholder, .no-new-line, [class*="placeholder"]');
                        if (plEl && (plEl.innerText || plEl.textContent).trim()) {
                            placeholder = (plEl.innerText || plEl.textContent).trim();
                        }
                    } else if (isCustom) {
                        const innerPl = el.querySelector('.no-new-line, [class*="placeholder"], [class*="title"], span');
                        if (innerPl && (innerPl.innerText || innerPl.textContent).trim()) {
                            placeholder = (innerPl.innerText || innerPl.textContent).trim();
                        }
                    }
                }

                let currentValue = el.value || '';
                // 智能嗅探 AntDesign / ElementUI 下拉框当前已选值
                if (!currentValue) {
                    const selectParent = el.closest('.ant-select, .el-select, .arco-select, .t-select, .categories-select');
                    if (selectParent) {
                        const itemEl = selectParent.querySelector('.ant-select-selection-item, .el-select__selected-item, .arco-select-view-value, .no-new-line');
                        if (itemEl && (itemEl.innerText || itemEl.textContent).trim()) {
                            currentValue = (itemEl.innerText || itemEl.textContent).trim();
                        }
                    } else if (isCustom) {
                        currentValue = (el.innerText || el.textContent || '').trim();
                    }
                }

                let fieldType = 'text';
                if (el.tagName.toLowerCase() === 'textarea') {
                    fieldType = 'textarea';
                } else if (el.tagName.toLowerCase() === 'select') {
                    fieldType = 'select';
                } else if (isCustom) {
                    fieldType = el.getAttribute('role') === 'switch' ? 'switch' : 'custom_select';
                } else {
                    fieldType = el.type || 'text';
                }

                let options = [];
                if (el.tagName.toLowerCase() === 'select') {
                    options = Array.from(el.options).map(o => ({ text: o.text.trim(), value: o.value }));
                }

                // 智能识别必填项 (包括父级带有 ant-form-item-required / is-required 的情况)
                const formItemParent = el.closest('.ant-form-item, .el-form-item, .form-group, .form-item');
                const hasRequiredClass = formItemParent ? !!formItemParent.querySelector('.ant-form-item-required, .is-required, [class*="required"]') : false;
                const isRequired = el.required || el.getAttribute('aria-required') === 'true' || hasRequiredClass;

                result.fields.push({
                    index: validIndex,
                    label: label || `未命名字段_${validIndex}`,
                    placeholder: placeholder,
                    type: fieldType,
                    current_value: currentValue,
                    is_checked: el.checked || false,
                    is_disabled: el.disabled || false,
                    is_required: isRequired,
                    locator_visual: generateVisualLocator(el, label, placeholder),
                    locator_css: generateCssSelector(el),
                    name_attr: el.name || '',
                    id_attr: el.id || ''
                });
            });

            // 2. 扫描所有操作按钮
            const buttons = document.querySelectorAll('button, input[type="button"], input[type="submit"], a.btn, a[role="button"], [class*="btn"]:not(input):not(select)');
            buttons.forEach((el, index) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || (rect.width === 0 && rect.height === 0)) {
                    return;
                }

                const text = el.innerText ? el.innerText.trim() : (el.value || el.title || el.getAttribute('aria-label') || '');
                if (!text && !el.querySelector('svg, img, i')) return;

                result.buttons.push({
                    index: index + 1,
                    text: text || '图标按钮',
                    type: el.type || 'button',
                    is_disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
                    locator_visual: text ? `get_by_role("button", name="${text.slice(0, 20).replace(/"/g, '\\\\"')}")` : `locator("${generateCssSelector(el)}")`,
                    locator_css: generateCssSelector(el)
                });
            });

            // 3. 扫描文件上传组件
            const fileInputs = document.querySelectorAll('input[type="file"], [class*="upload"], [class*="dropzone"]');
            fileInputs.forEach((el, index) => {
                const isRealFileInput = el.tagName.toLowerCase() === 'input' && el.type === 'file';
                const parentLabel = el.closest('[class*="upload"], .form-item, .form-group');
                const label = parentLabel ? (parentLabel.innerText || '').split('\\n')[0].trim() : '文件上传';

                result.uploaders.push({
                    index: index + 1,
                    label: label.slice(0, 30),
                    accept: el.accept || '',
                    is_multiple: el.multiple || false,
                    locator_css: isRealFileInput ? generateCssSelector(el) : `${generateCssSelector(el)} input[type="file"]`
                });
            });

            return result;
        }
        """
        raw_data = self.page.evaluate(js_code)
        return raw_data

    def export_to_json(self, output_path: str) -> None:
        """扫描当前页面并将高精度结构化 DOM 导出为 JSON 文件"""
        data = self.scan_page()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
