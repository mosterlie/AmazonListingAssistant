import sys
import os
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def main():
    engine = BrowserEngine(port=9222)
    engine.connect(activate=False)
    page = engine.manager._get_active_page_impl()
    
    def test_auto_cat():
        print("1. 正在查找【自动识别产品类型】按钮...")
        btn = page.locator("button, .ant-btn").filter(has_text="自动识别产品类型").first
        if btn.count() == 0:
            print("❌ 未找到【自动识别产品类型】按钮！")
            return False
            
        btn.scroll_into_view_if_needed()
        btn.click()
        print("✅ 点击【自动识别产品类型】按钮成功，等待弹窗...")
        
        # 等待弹窗
        modal_found = False
        start_t = time.time()
        while time.time() - start_t < 15:
            modal = page.locator(".ant-modal-content:visible, .ant-modal:visible").first
            if modal.count() > 0 and ("推荐" in modal.inner_text() or "确定" in modal.inner_text() or "分类" in modal.inner_text()):
                print(f"✅ 弹窗已出现！弹窗内容摘要: {modal.inner_text()[:100]}...")
                modal_found = True
                
                # 点击确定
                ok_btn = modal.locator("button, .ant-btn").filter(has_text="确定").first
                if ok_btn.count() > 0:
                    ok_btn.click()
                    print("✅ 已点击弹窗【确定】按钮！")
                else:
                    modal.locator(".ant-btn-primary").first.click()
                    print("✅ 已点击弹窗 primary 按钮！")
                break
            page.wait_for_timeout(400)
            
        if not modal_found:
            print("❌ 等待类目推荐弹窗超时！")
            return False
            
        # 等待分类从 "未选择分类" 变成具体分类
        print("⏳ 正在等待分类从【未选择分类】变为具体分类...")
        cat_start = time.time()
        while time.time() - cat_start < 15:
            cat_info = page.evaluate(r"""() => {
                const catList = document.querySelector('.category-list')?.innerText?.trim() || '';
                const selItem = document.querySelector('.ant-form-item:has(#form_item_category) .ant-select-selection-item')?.innerText?.trim() || '';
                const placeholder = document.querySelector('.ant-form-item:has(#form_item_category) .ant-select-selection-placeholder')?.innerText?.trim() || '';
                return { catList, selItem, placeholder };
            }""")
            
            cat_list_text = cat_info.get("catList", "")
            sel_text = cat_info.get("selItem", "")
            print(f"   当前分类探测: category-list='{cat_list_text}', select-item='{sel_text}'")
            
            # 判断是否已变成具体分类
            is_valid_cat = False
            if cat_list_text and cat_list_text != "未选择分类" and len(cat_list_text) > 2:
                is_valid_cat = True
            if sel_text and sel_text != "---- 请选择分类 ----" and len(sel_text) > 2:
                is_valid_cat = True
                
            if is_valid_cat:
                print(f"🎉 分类已成功变为具体分类: 【{sel_text or cat_list_text}】！")
                page.wait_for_timeout(1000)
                return True
                
            page.wait_for_timeout(500)
            
        print("❌ 等待具体分类渲染超时！")
        return False

    res = engine.manager.run_on_browser_thread(test_auto_cat)
    print("Test auto cat result:", res)

if __name__ == "__main__":
    main()
