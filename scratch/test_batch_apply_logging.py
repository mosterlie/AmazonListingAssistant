import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.form_operator import FormOperator


class TestBatchApplyLogging(unittest.TestCase):
    def test_verify_variation_batch_applied_extra_all_success(self):
        mock_page = MagicMock()
        mock_cards = [
            {"idx": 1, "text": "カラー: 11 / サイズ: S", "mainCount": 1, "extraCount": 6},
            {"idx": 2, "text": "カラー: 11 / サイズ: M", "mainCount": 0, "extraCount": 6},
            {"idx": 3, "text": "カラー: 22 / サイズ: S", "mainCount": 0, "extraCount": 6},
            {"idx": 4, "text": "カラー: 22 / サイズ: M", "mainCount": 0, "extraCount": 6},
        ]
        mock_res = {
            "success": True,
            "totalCards": 4,
            "syncedCount": 4,
            "expectedExtra": 6,
            "cards": mock_cards
        }
        mock_page.evaluate.return_value = mock_res
        
        logs = []
        op = FormOperator(mock_page)
        res = op.verify_variation_batch_applied(
            filter_criteria={"颜色": "11"},
            apply_type="extra_all",
            timeout_ms=500,
            log_callback=logs.append
        )

        self.assertTrue(res)
        joined_logs = "\n".join(logs)
        self.assertIn("SKU #01【カラー: 11 / サイズ: S】: 附图 6 张", joined_logs)
        self.assertIn("SKU #02【カラー: 11 / サイズ: M】: 附图 6 张", joined_logs)
        self.assertIn("✅ 达标", joined_logs)
        self.assertIn("全量变体附图已全部批量同步成功", joined_logs)

    def test_verify_variation_batch_applied_main_color(self):
        mock_page = MagicMock()
        mock_cards = [
            {"idx": 1, "text": "カラー: 11 / サイズ: S", "mainCount": 1, "extraCount": 6},
            {"idx": 2, "text": "カラー: 11 / サイズ: M", "mainCount": 1, "extraCount": 6},
        ]
        mock_res = {
            "success": True,
            "totalCards": 2,
            "syncedCount": 2,
            "targetDim": "11",
            "cards": mock_cards
        }
        mock_page.evaluate.return_value = mock_res

        logs = []
        op = FormOperator(mock_page)
        res = op.verify_variation_batch_applied(
            filter_criteria={"颜色": "11"},
            apply_type="main_color",
            timeout_ms=500,
            log_callback=logs.append
        )

        self.assertTrue(res)
        joined_logs = "\n".join(logs)
        self.assertIn("【主图批量应用核验】同颜色【11】", joined_logs)
        self.assertIn("✅ 已装配主图", joined_logs)
        self.assertIn("所有变体主图已全部批量同步成功", joined_logs)


if __name__ == "__main__":
    unittest.main()
