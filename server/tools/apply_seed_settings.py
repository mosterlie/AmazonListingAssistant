"""生产铺底: 将种子配置文件写入 system_settings (system_settings_seed.json → DB)

用法: python3 server/tools/apply_seed_settings.py server/seed/system_settings_seed.json
覆盖策略: 文件中的键直接覆盖 (ON CONFLICT UPDATE), 未包含的键保持现状
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from server.database import set_setting  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python3 server/tools/apply_seed_settings.py <seed.json>")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    settings = doc.get("settings") or {}
    if not isinstance(settings, dict) or not settings:
        print("种子文件无 settings 内容, 退出")
        sys.exit(1)
    for key, value in settings.items():
        set_setting(key, value)
    print(f"铺底完成: {len(settings)} 个键已写入 system_settings")


if __name__ == "__main__":
    main()
