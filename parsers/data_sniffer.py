"""
页面隐藏全局数据对象、JSON-LD 与多媒体素材嗅探器
"""
from typing import Dict, Any, List, Optional
from playwright.sync_api import Page

try:
    from .base_parser import BasePageParser
except (ImportError, ValueError):
    from base_parser import BasePageParser


class DataSniffer(BasePageParser):
    """
    负责嗅探页面中隐藏的结构化元数据：
    1. `<script type="application/ld+json">` 结构化电商/文章数据
    2. 挂载在 `window` 上的全局商品/页面 JSON 对象（如 1688/淘宝等电商平台原生数据）
    3. 全页图片多媒体资产列表（含高清大图与尺寸过滤）
    """

    def is_match(self) -> bool:
        return True

    def extract(self) -> Dict[str, Any]:
        """全量嗅探页面隐藏数据与多媒体资产"""
        js_code = """
        () => {
            const result = {
                json_ld: [],
                meta_tags: {},
                window_globals: {},
                images: []
            };

            // 1. 提取 JSON-LD 结构化数据
            const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
            ldScripts.forEach((s) => {
                try {
                    const parsed = JSON.parse(s.innerText);
                    result.json_ld.push(parsed);
                } catch (e) {}
            });

            // 2. 提取 OpenGraph 与 Meta 元标签
            const metas = document.querySelectorAll('meta[property], meta[name]');
            metas.forEach(m => {
                const key = m.getAttribute('property') || m.getAttribute('name');
                const content = m.getAttribute('content');
                if (key && content) {
                    result.meta_tags[key] = content;
                }
            });

            // 3. 嗅探常见的 window 全局商品与页面数据对象
            const candidateKeys = [
                '__INIT_DATA__', 'runParams', '__INITIAL_STATE__', 
                '_pageData', 'itemData', 'detailData', 'PAGE_CONFIG',
                'wingxViewData', 'i18nData', 'g_config'
            ];

            candidateKeys.forEach(k => {
                try {
                    if (window[k] && typeof window[k] === 'object') {
                        // 简单序列化测试，避免循环引用
                        result.window_globals[k] = JSON.parse(JSON.stringify(window[k]));
                    }
                } catch (e) {}
            });

            // 4. 提取全页高质量图片素材
            const imgElements = document.querySelectorAll('img[src]');
            const seenSrc = new Set();
            imgElements.forEach(img => {
                const src = img.currentSrc || img.src;
                if (!src || src.startsWith('data:') || seenSrc.has(src)) return;
                seenSrc.add(src);

                const width = img.naturalWidth || img.width;
                const height = img.naturalHeight || img.height;

                // 过滤微小图标 (小于 60x60)
                if (width >= 60 || height >= 60 || !width) {
                    result.images.push({
                        src: src,
                        alt: img.alt || '',
                        width: width,
                        height: height
                    });
                }
            });

            return result;
        }
        """
        return self.page.evaluate(js_code)
