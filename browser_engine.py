"""
Browser Toolkit - 统一门面引擎 (BrowserEngine)
提供极简、直观的一站式 Python SDK，用于启动/接管浏览器、获取活动页面与高精度解析 DOM。
"""
import os
import json
from typing import Dict, Any, List, Optional, Tuple, Union, Callable
from playwright.sync_api import Page

try:
    from . import config
    from .core.browser_manager import BrowserManager
    from .core.tab_matcher import TabInfo
    from .core.form_operator import FormOperator
    from .parsers.dom_precision_parser import DOMPrecisionParser
    from .parsers.table_parser import TableParser
    from .parsers.data_sniffer import DataSniffer
except (ImportError, ValueError):
    import config
    from core.browser_manager import BrowserManager
    from core.tab_matcher import TabInfo
    from core.form_operator import FormOperator
    from parsers.dom_precision_parser import DOMPrecisionParser
    from parsers.table_parser import TableParser
    from parsers.data_sniffer import DataSniffer


class BrowserEngine:
    """
    浏览器自动化与高精度 DOM 解析统一引擎
    """

    def __init__(self, port: int = config.DEFAULT_CDP_PORT, user_data_dir: str = config.USER_DATA_DIR):
        self.port = port
        self.user_data_dir = user_data_dir
        self.manager = BrowserManager(port=self.port, user_data_dir=self.user_data_dir)

    def launch_browser(self, target_url: str = "about:blank") -> Tuple[bool, str]:
        """以 CDP 调试模式启动或唤起 Chrome 浏览器"""
        return self.manager.launch_browser(target_url)

    def connect(self, activate: bool = True) -> Tuple[bool, str]:
        """连接并接管已开启调试端口的 Chrome 浏览器"""
        return self.manager.connect(activate)

    def is_running(self) -> bool:
        """检查 CDP 端口是否处于活跃状态"""
        return self.manager.is_port_open()

    def get_tabs(self) -> List[TabInfo]:
        """获取浏览器当前所有打开的标签页"""
        return self.manager.get_tabs()

    def get_active_page(self) -> Optional[Page]:
        """获取当前正在前台显示的活动标签页"""
        return self.manager.get_active_page()

    def get_active_tab_info(self) -> Optional[TabInfo]:
        """获取当前正在前台显示的活动标签页信息对象（包含 title, url, index 等）"""
        tabs = self.get_tabs()
        for t in tabs:
            if t.is_active:
                return t
        return tabs[0] if tabs else None

    def open_or_focus_url(self, target_url: str) -> Optional[Page]:
        """打开目标网址或激活已有相同域名的标签页"""
        return self.manager.open_or_focus_url(target_url)

    def parse_page(self, page: Optional[Page] = None) -> Dict[str, Any]:
        """
        核心方法：对指定页面执行 100% 全量高精度 DOM 解析
        如果未传 page，则自动使用当前前台活动标签页。
        内部自动调度至 Playwright 专属常驻线程，彻底杜绝 greenlet 跨线程异常。
        """
        return self.manager.run_on_browser_thread(self._parse_page_impl, page)

    def _parse_page_impl(self, page: Optional[Page] = None) -> Dict[str, Any]:
        target_page = page or self.manager._get_active_page_impl()
        if not target_page:
            raise RuntimeError("未能找到可解析的目标页面，请确保浏览器已打开！")

        # 1. 字段与交互控件高精度解析
        dom_parser = DOMPrecisionParser(target_page)
        dom_result = dom_parser.scan_page()

        # 2. 表格与 SKU 矩阵解析
        tbl_parser = TableParser(target_page)
        tables_result = tbl_parser.scan_tables()

        # 3. 隐藏数据与多媒体嗅探
        sniffer = DataSniffer(target_page)
        sniffer_result = sniffer.extract()

        # 合并为完整结构化大字典
        full_result = {
            "page_info": dom_result.get("page_info", {}),
            "summary": {
                "total_fields": len(dom_result.get("fields", [])),
                "total_buttons": len(dom_result.get("buttons", [])),
                "total_uploaders": len(dom_result.get("uploaders", [])),
                "total_tables": len(tables_result),
                "total_images": len(sniffer_result.get("images", [])),
                "has_json_ld": len(sniffer_result.get("json_ld", [])) > 0,
                "window_globals_found": list(sniffer_result.get("window_globals", {}).keys())
            },
            "form_fields": dom_result.get("fields", []),
            "buttons": dom_result.get("buttons", []),
            "uploaders": dom_result.get("uploaders", []),
            "tables": tables_result,
            "hidden_data": {
                "json_ld": sniffer_result.get("json_ld", []),
                "meta_tags": sniffer_result.get("meta_tags", {}),
                "window_globals": sniffer_result.get("window_globals", {})
            },
            "images": sniffer_result.get("images", [])
        }

        return full_result

    def execute_js(self, script: str, arg: Any = None, page: Optional[Page] = None) -> Any:
        """在页面上下文中安全执行自定义 JS 脚本"""
        return self.manager.run_on_browser_thread(
            lambda: (page or self.manager._get_active_page_impl()).evaluate(script, arg)
        )

    def select(self, field_label_or_selector: str, option_text: str, page: Optional[Page] = None) -> bool:
        """
        在当前页面（或指定页面）的下拉框中选择目标选项
        :param field_label_or_selector: 字段名称（如 '店铺账号'）或选择器（如 '#rc_select_0'）
        :param option_text: 目标选项文本（如 '金梧汇辰'）
        """
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).select(field_label_or_selector, option_text)
        )

    def fill(self, field_label_or_selector: str, text_value: str, clear_first: bool = True, page: Optional[Page] = None) -> bool:
        """
        在当前页面（或指定页面）的输入框中填入文本
        :param field_label_or_selector: 字段名称（如 '产品标题'）或选择器
        :param text_value: 要填入的内容
        """
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).fill(field_label_or_selector, text_value, clear_first)
        )

    def click_radio(self, label_text: str, page: Optional[Page] = None) -> bool:
        """根据文字标签点击单选框或复选框（如 '单品', '多变种', '是', '否'）"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).click_radio_or_checkbox(label_text)
        )

    def click_button(self, button_text_or_selector: str, page: Optional[Page] = None) -> bool:
        """点击指定按钮（如 '保存', '一键翻译', '存为模板', '自动识别产品类型'）"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).click_button(button_text_or_selector)
        )

    def confirm_modal(self, button_text: str = "确定", wait_timeout_ms: int = 5000, page: Optional[Page] = None) -> bool:
        """在弹出的模态对话框中点击确认按钮（如 '确定', '确认'）"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).confirm_modal(button_text, wait_timeout_ms)
        )

    def select_store_account(self, store_account: str = "金梧汇辰", expected_site: str = "日本", timeout_ms: int = 15000, page: Optional[Page] = None) -> bool:
        """强力选择【店铺账号】，并严格循环重试与校验直到选中并联动站点"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).select_store_account(store_account, expected_site, timeout_ms)
        )

    def add_variation_option(self, attribute_name: str, option_value: str, timeout_ms: int = 5000, page: Optional[Page] = None) -> bool:
        """在变体属性区域（如 'カラー(颜色)' 或 'サイズ(尺寸)'）的'其它'输入框中输入自定义选项并点击'添加'"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).add_variation_option(attribute_name, option_value, timeout_ms)
        )

    def fill_variation_row(self, filter_criteria: Dict[str, str], row_data: Dict[str, Any], timeout_ms: int = 5000, page: Optional[Page] = None) -> bool:
        """根据指定属性条件（如 {'颜色': 'dd', '尺寸': 'tt'}）定位变体表格行并填入数值"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).fill_variation_row(filter_criteria, row_data, timeout_ms)
        )

    def upload_variation_image(
        self,
        filter_criteria: Dict[str, str],
        image_path: Union[str, List[str]],
        image_type: str = "main",
        upload_mode: str = "local",
        timeout_ms: int = 10000,
        skip_if_exists: bool = False,
        page: Optional[Page] = None
    ) -> bool:
        """为指定变体（如 {'颜色': 'dd', '尺寸': 'tt'}）上传单张或多张图片（主图/Swatch/附图）"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).upload_variation_image(
                filter_criteria, image_path, image_type, upload_mode, timeout_ms, skip_if_exists
            )
        )

    def set_variation_images(
        self,
        filter_criteria: Dict[str, str],
        main_image: Optional[str] = None,
        swatch_image: Optional[str] = None,
        extra_images: Optional[Union[str, List[str]]] = None,
        timeout_ms: int = 15000,
        page: Optional[Page] = None
    ) -> Dict[str, bool]:
        """一站式为指定变体行上传主图、Swatch Image 和多张附图"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).set_variation_images(
                filter_criteria, main_image, swatch_image, extra_images, timeout_ms
            )
        )

    def apply_variation_image(
        self,
        filter_criteria: Dict[str, str],
        apply_type: str,
        timeout_ms: int = 12000,
        verify_success: bool = True,
        log_callback: Optional[Callable[[str], None]] = None,
        page: Optional[Page] = None
    ) -> bool:
        """点击指定变体卡片的「图片应用到」并批量应用图片，自动校验成功后返回
        :param apply_type: 'extra_all'(附图-所有变体) / 'main_color'(主图-同カラー的变种) / 'main_size'(主图-同サイズ的变种)
        :param verify_success: 是否在点击应用后校验页面所有目标卡片是否同步成功
        :param log_callback: 日志回调函数
        """
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).apply_variation_image(
                filter_criteria, apply_type, timeout_ms, verify_success, log_callback
            )
        )

    def verify_variation_batch_applied(
        self,
        filter_criteria: Dict[str, str],
        apply_type: str,
        timeout_ms: int = 6000,
        log_callback: Optional[Callable[[str], None]] = None,
        page: Optional[Page] = None
    ) -> bool:
        """深度校验批量应用是否已真实在页面 DOM 中同步生效，逐个 SKU 检查附图与主图数据并登记日志"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).verify_variation_batch_applied(
                filter_criteria, apply_type, timeout_ms, log_callback
            )
        )

    def verify_variation_image_uploaded(
        self,
        filter_criteria: Dict[str, str],
        image_type: str = "main",
        min_count: int = 1,
        timeout_ms: int = 4000,
        page: Optional[Page] = None
    ) -> bool:
        """深度校验指定变体卡片的图片是否已真实上传并渲染"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).verify_variation_image_uploaded(
                filter_criteria, image_type, min_count, timeout_ms
            )
        )

    def verify_all_variation_images_summary(
        self,
        page: Optional[Page] = None
    ) -> Dict[str, Any]:
        """获取当前页面全部变体卡片的主图与附图装配统计"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).verify_all_variation_images_summary()
        )

    def get_dianxiaomi_variation_cards(
        self,
        page: Optional[Page] = None
    ) -> List[Dict[str, Any]]:
        """按照店小秘页面 DOM 中的实际排列顺序，读取全部变体卡片列表"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).get_dianxiaomi_variation_cards()
        )

    def is_variation_card_main_uploaded(
        self,
        filter_criteria: Optional[Dict[str, str]] = None,
        card_idx: Optional[int] = None,
        page: Optional[Page] = None
    ) -> bool:
        """检查指定变体卡片的主图是否已经上传/存在"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).is_variation_card_main_uploaded(
                filter_criteria, card_idx
            )
        )

    def find_next_unassigned_variation_card(
        self,
        dimension: str = "color",
        start_idx: int = 0,
        skip_indices: Optional[List[int]] = None,
        page: Optional[Page] = None
    ) -> Dict[str, Any]:
        """动态扫描页面 DOM，从上往下查找第一个主图仍为空的变体卡片"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).find_next_unassigned_variation_card(
                dimension, start_idx, skip_indices
            )
        )

    def upload_parent_images(
        self,
        main_image: Optional[str] = None,
        extra_images: Optional[List[str]] = None,
        timeout_ms: int = 15000,
        page: Optional[Page] = None
    ) -> bool:
        """在父级商品图片区域 (#imageInfo) 批量上传主图与 1~8 张附图"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).upload_parent_images(
                main_image, extra_images, timeout_ms
            )
        )

    def fill_bullet_points(self, bullet_points: List[str], page: Optional[Page] = None) -> bool:
        """在描述信息区域依次填入 1~5 项 Bullet Points"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).fill_bullet_points(bullet_points)
        )

    def fill_description(self, description_text: str, page: Optional[Page] = None) -> bool:
        """在描述信息区域填入商品长描述"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).fill_description(description_text)
        )

    def fill_manufacturer(self, manufacturer: str, page: Optional[Page] = None) -> bool:
        """填入制造商字段 (若未传入则默认使用品牌名称)"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).fill_manufacturer(manufacturer)
        )

    def fill_dimensions_and_weight(
        self,
        item_length=None, item_width=None, item_height=None, item_dim_unit="cm",
        package_length=None, package_width=None, package_height=None, package_dim_unit="cm",
        item_weight=None, item_weight_unit=None,
        package_weight=None, package_weight_unit="kg",
        page: Optional[Page] = None
    ) -> bool:
        """在产品属性与包装属性中填入商品尺寸(品目寸法)、包装尺寸(パッケージ寸法)及重量"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).fill_dimensions_and_weight(
                item_length, item_width, item_height, item_dim_unit,
                package_length, package_width, package_height, package_dim_unit,
                item_weight, item_weight_unit,
                package_weight, package_weight_unit
            )
        )

    def fill_search_terms(self, search_terms: str, page: Optional[Page] = None) -> bool:
        """在关键词信息区域填入 Search Terms"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).fill_search_terms(search_terms)
        )

    def select_fulfillment_channel(self, channel: str = "FBM", timeout_ms: int = 8000, page: Optional[Page] = None) -> bool:
        """强力选择并锁定【配送渠道】(FBM / FBA)"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).select_fulfillment_channel(channel, timeout_ms)
        )

    def save_draft(self, timeout_ms: int = 10000, page: Optional[Page] = None) -> bool:
        """点击页面顶部的【保存】按钮，保存为店小秘草稿"""
        return self.manager.run_on_browser_thread(
            lambda: FormOperator(page or self.manager._get_active_page_impl()).save_draft(timeout_ms)
        )

    def parse_and_export_json(self, output_path: str, page: Optional[Page] = None) -> Dict[str, Any]:
        """解析页面并导出为格式化 JSON 文件"""
        data = self.parse_page(page)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data

    @staticmethod
    def print_dom_summary(data: Dict[str, Any]) -> None:
        """在控制台打印美观易读的 DOM 解析摘要报告"""
        page_info = data.get("page_info", {})
        summary = data.get("summary", {})
        fields = data.get("form_fields", [])
        buttons = data.get("buttons", [])
        tables = data.get("tables", [])

        print("\n" + "=" * 70)
        print(f"🌐 页面标题: {page_info.get('title', '无标题')}")
        print(f"🔗 页面网址: {page_info.get('url', '无URL')}")
        print(f"📊 元素统计: 字段 [{summary.get('total_fields')}] 个 | 按钮 [{summary.get('total_buttons')}] 个 | 表格 [{summary.get('total_tables')}] 个 | 上传点 [{summary.get('total_uploaders')}] 个")
        print("=" * 70)

        if fields:
            print("\n📝 【表单输入控件列表 (前 15 个)】:")
            for f in fields[:15]:
                req_mark = " *必填*" if f.get('is_required') else ""
                val_mark = f" [值: '{f.get('current_value')}']" if f.get('current_value') else ""
                print(f"  • [序号 {f.get('index')}] 【{f.get('label')}】 ({f.get('type')}){req_mark}{val_mark}")
                print(f"    - 定位代码: page.{f.get('locator_visual')}")
                print(f"    - CSS选择器: {f.get('locator_css')}")
            if len(fields) > 15:
                print(f"    ... 以及其余 {len(fields) - 15} 个输入控件 (详见导出 JSON)")

        if buttons:
            print("\n🔘 【操作按钮列表】:")
            for b in buttons[:10]:
                print(f"  • 【{b.get('text')}】 -> page.{b.get('locator_visual')}")

        if tables:
            print("\n📋 【数据表格列表】:")
            for t in tables:
                print(f"  • 表格 #{t.get('table_index')} | 表头列: {t.get('headers')} | 行数: {t.get('total_rows')}")

        print("\n" + "=" * 70 + "\n")

    def highlight_and_verify(self, page: Optional[Page] = None) -> Dict[str, Any]:
        """
        在浏览器当前页面中为所有已解析元素实时绘制彩色高亮框与序号标签，
        并在右上角注入实时覆盖率核验看板，直观验证 100% DOM 捕获率。
        """
        js_code = """
        () => {
            const oldContainer = document.getElementById('__agy_inspector_overlay__');
            if (oldContainer) oldContainer.remove();

            const overlay = document.createElement('div');
            overlay.id = '__agy_inspector_overlay__';
            overlay.style.cssText = 'position:absolute;top:0;left:0;width:100%;min-height:100%;pointer-events:none;z-index:999999;';
            document.body.appendChild(overlay);

            function addHighlight(el, text, color, badgeBg) {
                if (!el) return;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) return;

                const box = document.createElement('div');
                box.style.cssText = `
                    position: absolute;
                    left: ${window.scrollX + rect.left}px;
                    top: ${window.scrollY + rect.top}px;
                    width: ${rect.width}px;
                    height: ${rect.height}px;
                    border: 2px solid ${color};
                    border-radius: 4px;
                    box-sizing: border-box;
                    background: rgba(16, 185, 129, 0.05);
                    pointer-events: none;
                    transition: all 0.2s ease;
                `;

                const badge = document.createElement('span');
                badge.innerText = text;
                badge.style.cssText = `
                    position: absolute;
                    top: -22px;
                    left: 0;
                    background: ${badgeBg};
                    color: #ffffff;
                    font-size: 11px;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    font-weight: 600;
                    padding: 2px 6px;
                    border-radius: 3px;
                    white-space: nowrap;
                    box-shadow: 0 2px 6px rgba(0,0,0,0.25);
                    pointer-events: none;
                `;
                box.appendChild(badge);
                overlay.appendChild(box);
            }

            const panel = document.createElement('div');
            panel.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                background: #111827;
                color: #F9FAFB;
                padding: 16px 20px;
                border-radius: 12px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
                border: 1px solid #374151;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 13px;
                z-index: 1000000;
                pointer-events: auto;
                min-width: 260px;
                backdrop-filter: blur(8px);
            `;

            let fieldCount = 0;
            const inputSelector = 'input:not([type="hidden"]):not([type="file"]), textarea, select, .categories-select, .ant-cascader-picker, .ant-picker:not(:has(input)), .el-cascader:not(:has(input)), [class*="categories-select"], [role="combobox"]:not(input):not(select), [role="switch"]:not(input), [contenteditable="true"]';
            document.querySelectorAll(inputSelector).forEach((el) => {
                const isCustom = !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
                if (isCustom && el.querySelector('input:not([type="hidden"]), textarea, select')) {
                    return;
                }
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (style.display !== 'none' && style.visibility !== 'hidden' && (rect.width > 0 || rect.height > 0)) {
                    fieldCount++;
                    const selectParent = el.closest('.ant-select, .el-select, .arco-select, .categories-select');
                    const targetEl = selectParent || el;
                    addHighlight(targetEl, `[字段 #${fieldCount}]`, '#10B981', '#059669');
                }
            });

            let btnCount = 0;
            document.querySelectorAll('button, input[type="button"], input[type="submit"], a.btn, [role="button"], .ant-btn, .el-button').forEach((el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (style.display !== 'none' && style.visibility !== 'hidden' && (rect.width > 0 || rect.height > 0)) {
                    const txt = (el.innerText || el.value || '').trim();
                    if (txt) {
                        btnCount++;
                        addHighlight(el, `[按钮: ${txt.slice(0, 10)}]`, '#3B82F6', '#2563EB');
                    }
                }
            });

            panel.innerHTML = `
                <div style="font-weight: 700; font-size: 14px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between;">
                    <span>🔍 DOM 视觉核验看板</span>
                    <span style="background: #065F46; color: #34D399; font-size: 11px; padding: 2px 6px; border-radius: 9999px;">已核验</span>
                </div>
                <div style="line-height: 1.8; color: #9CA3AF;">
                    <div>🟢 高亮输入控件: <b style="color: #10B981;">${fieldCount}</b> 个</div>
                    <div>🔵 高亮操作按钮: <b style="color: #60A5FA;">${btnCount}</b> 个</div>
                </div>
                <button id="__agy_clear_btn__" style="
                    margin-top: 12px;
                    width: 100%;
                    padding: 6px 12px;
                    background: #374151;
                    color: #E5E7EB;
                    border: none;
                    border-radius: 6px;
                    font-size: 12px;
                    cursor: pointer;
                    font-weight: 500;
                ">✕ 一键清除高亮</button>
            `;
            overlay.appendChild(panel);

            document.getElementById('__agy_clear_btn__').onclick = () => {
                overlay.remove();
            };

            return {
                highlighted_fields: fieldCount,
                highlighted_buttons: btnCount,
                status: "success"
            };
        }
        """
        return self.execute_js(js_code, page=page)

    def clear_highlights(self, page: Optional[Page] = None) -> None:
        """移除页面上的所有高亮标记与核验看板"""
        js_code = """
        () => {
            const overlay = document.getElementById('__agy_inspector_overlay__');
            if (overlay) overlay.remove();
        }
        """
        self.execute_js(js_code, page=page)

    def close(self):
        """关闭引擎与底层连接"""
        self.manager.close()
