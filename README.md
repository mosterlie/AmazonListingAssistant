# Browser Toolkit - 浏览器接管与高精度 DOM 结构化解析引擎

基于 Python + Playwright 原生 CDP（Chrome DevTools Protocol）协议开发的独立浏览器自动化与页面解析工具包。

无需复杂配置，免安装扩展插件，**可对任意指定的网页进行 100% 精准、无死角的表单、按钮、表格与结构化数据解析**。


启动调试chrmoe
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\ChromeDebugUser"

项目启动
cd D:\myCoding\AmazonListingAssistant
python -m server.app

---

## 🌟 核心特性

1. **原生 CDP 调试接管**：
   - 跨平台（macOS / Windows）自动探测并调起 Chrome 或 Edge 浏览器；
   - 自动接管并保持持久化登录态（Cookie / Session）；
   - 内置单原生线程调度模型，彻底避免 Playwright 跨线程 greenlet 异常。
2. **高精度 DOM 嗅探与字段识别（`dom_precision_parser.py`）**：
   - **视觉 Label 智能关联**：自动通过 `label[for]`、父级 `.form-item`、邻近文本、`aria-label` 还原人类看到的字段名；
   - **自动提取输入框状态**：提取 Placeholder、当前值、字段类型、必填状态；
   - **生成三合一最稳健定位器**：同时输出 `visual_locator`（视觉定位）、`css`（选择器）、`xpath`。
3. **表格与 SKU 矩阵结构化解析（`table_parser.py`）**：
   - 自动对齐复杂表头与数据行，将表格解析为 `[{"列名": "值", ...}]` 的字典列表。
4. **隐藏数据与多媒体嗅探（`data_sniffer.py`）**：
   - 自动提取 `<script type="application/ld+json">`、Meta 开放图谱标签；
   - 自动嗅探挂载在 `window` 上的全局商品数据对象（如 `__INIT_DATA__`, `runParams` 等）；
   - 提取全页高清图片素材列表。

---

## 📁 目录结构

```
browser_toolkit/
├── README.md                      # 本说明文档
├── requirements.txt               # Python 依赖清单
├── config.py                      # 全局配置 (CDP 端口、超时、浏览器路径)
├── browser_engine.py              # 高层统一门面类 (BrowserEngine SDK)
│
├── core/                          # 核心驱动与操作层
│   ├── browser_manager.py         # 浏览器生命周期管理与线程安全调度器
│   ├── tab_matcher.py             # 标签页元数据模型与匹配器
│   └── form_operator.py           # 表单自动化填写与交互操作引擎
│
├── parsers/                       # 解析引擎层
│   ├── base_parser.py             # 解析器抽象基类
│   ├── dom_precision_parser.py    # 表单与交互元素高精度嗅探器
│   ├── table_parser.py            # 数据表格与矩阵列表提取器
│   └── data_sniffer.py            # 隐藏全局数据与多媒体提取器
│
└── examples/                      # 快速上手实战脚本
    ├── 01_quick_start.py          # 启动接管并列出所有标签页
    ├── 02_parse_active_page.py    # 一键精准解析当前浏览器正在看的页面
    ├── 03_parse_specified_url.py  # 指定目标网址直达并解析 DOM
    ├── 04_highlight_and_verify.py # DOM 视觉透视核验工具（浏览器页面实时高亮）
    └── 05_auto_fill_form.py       # 页面表单自动化逐步填写实战脚本
```

---

## 🚀 快速上手

### 1. 安装依赖

```bash
cd browser_toolkit
python3 -m pip install -r requirements.txt
```

### 2. 三行代码极速调用

```python
from browser_engine import BrowserEngine

# 1. 初始化引擎并连接/启动浏览器
engine = BrowserEngine()
engine.launch_browser("https://www.baidu.com")

# 2. 一键解析当前页面 DOM
dom_data = engine.parse_page()

# 3. 控制台打印美观的解析摘要报告
engine.print_dom_summary(dom_data)
```

---

## 💻 实战脚本使用场景

### 场景 A：解析你在浏览器中打开的任意目标页面
在接管的 Chrome 中打开任何你想要解析的网页（如妙手发布页、1688商品页等），然后在终端运行：

```bash
python3 examples/02_parse_active_page.py
```
> 程序会自动锁定当前前台标签页，将所有输入框、按钮、表格与元数据精准提取，并在当前目录生成 `output_active_page_dom.json`。

### 场景 B：指定 URL 自动导航并提取
```bash
python3 examples/03_parse_specified_url.py "https://example.com/product/101"
```

---

## 📊 导出的 JSON 结构说明

导出的 `output_xxx_dom.json` 包含以下完整结构：

```json
{
  "page_info": {
    "title": "页面标题",
    "url": "页面网址",
    "timestamp": "2026-08-28T22:00:00"
  },
  "summary": {
    "total_fields": 12,
    "total_buttons": 4,
    "total_tables": 1,
    "total_images": 8
  },
  "form_fields": [
    {
      "index": 1,
      "label": "商品名称",
      "placeholder": "请输入商品名称",
      "type": "text",
      "current_value": "示例商品",
      "is_required": true,
      "locator_visual": "get_by_placeholder(\"请输入商品名称\")",
      "locator_css": "input[name=\"title\"]"
    }
  ],
  "buttons": [
    {
      "index": 1,
      "text": "保存草稿",
      "locator_visual": "get_by_role(\"button\", name=\"保存草稿\")",
      "locator_css": "button.btn-save"
    }
  ],
  "tables": [
    {
      "table_index": 1,
      "headers": ["颜色", "尺码", "价格", "库存"],
      "total_rows": 2,
      "rows": [
        {
          "row_index": 1,
          "data_map": { "颜色": "黑色", "尺码": "M", "价格": "99", "库存": "100" }
        }
      ]
    }
  ]
}
```
