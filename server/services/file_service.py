"""
本地图片与文件管理服务
"""
import os
import re
import shutil
from typing import List, Dict, Any
from fastapi import UploadFile
from server.config import UPLOADS_DIR


class FileService:
    """负责商品图片的本地安全保存、查询与绝对路径解析"""

    @staticmethod
    def save_upload_file(upload_file: UploadFile) -> Dict[str, Any]:
        """
        保存单个上传的文件到本地 uploads 目录，保持原文件名不变
        :param upload_file: FastAPI UploadFile 对象
        :return: 包含文件名、相对 URL 与绝对本地物理路径的字典
        """
        raw_name = os.path.basename(upload_file.filename) if upload_file.filename else "image.jpg"
        # 清理文件名中的非法文件系统字符，保留原文件名
        clean_name = re.sub(r'[\\/*?:"<>|]', '_', raw_name).strip() or "image.jpg"
        target_path = os.path.join(UPLOADS_DIR, clean_name)

        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)

        return {
            "original_name": upload_file.filename,
            "saved_name": clean_name,
            "relative_url": f"/uploads/{clean_name}",
            "absolute_path": os.path.abspath(target_path),
            "size_bytes": os.path.getsize(target_path)
        }

    @staticmethod
    def save_multiple_upload_files(upload_files: List[UploadFile]) -> List[Dict[str, Any]]:
        """批量保存多个文件，保持原文件名不变"""
        results = []
        for file in upload_files:
            if file.filename:
                results.append(FileService.save_upload_file(file))
        return results

    @staticmethod
    def resolve_image_path(path: str) -> str:
        """
        根据相对路径、文件名或绝对路径，在系统已配置的存储根目录及 uploads 目录中精准解析出本地物理绝对路径
        """
        if not path or not isinstance(path, str) or not path.strip():
            return ""

        clean_p = path.strip()

        # 1. 尝试直接作为绝对路径查找
        if os.path.isabs(clean_p) and os.path.exists(clean_p) and os.path.isfile(clean_p):
            return os.path.abspath(clean_p)

        # 2. 如果以 /uploads/ 开头，剥离前缀在 UPLOADS_DIR 查找
        if clean_p.startswith("/uploads/"):
            rel_upload = clean_p[len("/uploads/"):].lstrip("/\\")
            p = os.path.join(UPLOADS_DIR, rel_upload)
            if os.path.exists(p) and os.path.isfile(p):
                return os.path.abspath(p)

        # 3. 在用户配置的本地产品存储根目录下查找
        try:
            import platform
            from server.database import get_setting
            is_win = (platform.system().lower() == "windows")
            default_base = "D:\\products" if is_win else "/Users/gx/Desktop/products"
            setting_key = "storage_path_win" if is_win else "storage_path_mac"
            base_dir = get_setting(setting_key, default_base)
        except Exception:
            base_dir = "/Users/gx/Desktop/products"

        target_in_storage = os.path.join(base_dir, clean_p)
        if os.path.exists(target_in_storage) and os.path.isfile(target_in_storage):
            return os.path.abspath(target_in_storage)

        # 4. 在 UPLOADS_DIR 下以纯文件名查找
        filename = os.path.basename(clean_p.replace("\\", "/"))
        target_in_uploads = os.path.join(UPLOADS_DIR, filename)
        if os.path.exists(target_in_uploads) and os.path.isfile(target_in_uploads):
            return os.path.abspath(target_in_uploads)

        # 5. 在 base_dir 下递归查找匹配文件名的文件
        if os.path.exists(base_dir):
            for root, dirs, files in os.walk(base_dir):
                if filename in files:
                    matched = os.path.join(root, filename)
                    if os.path.isfile(matched):
                        return os.path.abspath(matched)

        return ""
