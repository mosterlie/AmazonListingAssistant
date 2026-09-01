import sys
import os

# Set output encoding to utf-8
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from browser_engine import BrowserEngine
from core.form_operator import FormOperator

def run_test():
    print("=== 开始测试优化后的批量应用与检查逻辑 ===")
    engine = BrowserEngine()
    ok, msg = engine.connect()
    print(f"连接浏览器状态: ok={ok}, msg={msg}")
    
    def test_on_dxm():
        dxm_p = None
        for p in engine.manager.context.pages:
            if "amazon/add" in p.url or "dianxiaomi" in p.url:
                dxm_p = p
                break
        if not dxm_p:
            print("❌ 未找到店小秘页面！")
            return

        dxm_p.bring_to_front()
        op = FormOperator(dxm_p)
        print(f"✅ 成功定位到店小秘页面: {dxm_p.url} ({dxm_p.title()})")

        first_crit = {"颜色": "白色烧烤炉", "尺寸": "31*31*13.5cm"}
        
        # 1. 检查附图批量应用检查函数 (优化1: 仅需检查第2个SKU)
        print("\n[测试 1] 校验附图批量应用核验函数 (优化1: 只检查第2个SKU)...")
        extra_verified = op.verify_variation_batch_applied(
            filter_criteria=first_crit,
            apply_type="extra_all",
            timeout_ms=3000,
            log_callback=print
        )
        print(f"附图核验结果: {extra_verified}")

        # 2. 对当前页面的第1个SKU主图执行一键批量应用 (优化2: 修复菜单定位，应用到同カラー变种)
        print("\n[测试 2] 对第1个SKU执行主图一键应用到【主图 ➔ 同カラー(颜色)的变种】...")
        main_applied = op.apply_variation_image(
            filter_criteria=first_crit,
            apply_type="main_color",
            timeout_ms=15000,
            verify_success=True,
            log_callback=print
        )
        print(f"主图批量应用与核验结果: {main_applied}")

        # 3. 获取全页面变体图片的汇总体检报告
        print("\n[测试 3] 全页面变体卡片主图与附图装配统计报告:")
        summary = op.verify_all_variation_images_summary()
        print(f"总变体卡片数: {summary.get('total')}")
        print(f"已装配主图变体数: {summary.get('withMain')}")
        print(f"已装配附图变体数: {summary.get('withExtra')}")
        print("\n逐个卡片详情:")
        for c in summary.get('cards', []):
            c_spec = c.get('text', '').replace('变种属性:', '').replace('图片应用到', '').strip()
            print(f"  • SKU #{c.get('idx', 0):02d}【{c_spec}】: 主图 {c.get('mainCount', 0)} 张 | 附图 {c.get('extraCount', 0)} 张")

        # 4. 测试查找下一个未装配主图的卡片
        print("\n[测试 4] 扫描下一个未装配主图的卡片:")
        next_card = op.find_next_unassigned_variation_card("color")
        print(f"扫描结果: {next_card}")

    engine.manager.run_on_browser_thread(test_on_dxm)

if __name__ == "__main__":
    run_test()
