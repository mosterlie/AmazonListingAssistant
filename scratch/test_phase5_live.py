import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine
from server.services.product_service import ProductService
from server.services.file_service import FileService

CONV_ID = "d012c055-fb36-493d-b989-7e2ebf98f314"
ARTIFACT_DIR = f"/Users/gx/.gemini/antigravity-ide/brain/{CONV_ID}"

def test_phase5():
    product_id = 56
    product = ProductService.get_product_by_id(product_id)
    print(f"Product #{product_id}: {product.get('title')[:30]}", flush=True)
    
    engine = BrowserEngine(port=9222)
    engine.connect()
    engine.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    print("Activated Dianxiaomi page!", flush=True)
    
    # 准备图片配置
    img_dimension = product.get("variant_image_dimension") or "color"
    dim_images_map = product.get("variant_dimension_images") or {}
    parent_extras = product.get("extra_images") or []
    
    parent_extra_abs_files = [
        FileService.resolve_image_path(p) 
        for p in parent_extras 
        if p and FileService.resolve_image_path(p) and os.path.exists(FileService.resolve_image_path(p))
    ]
    print(f"parent_extra_abs_files ({len(parent_extra_abs_files)}): {parent_extra_abs_files}", flush=True)
    
    has_dim_images = bool(dim_images_map)
    applied_dim_values = set()
    extra_applied = False
    dim_label = "カラー(颜色)" if img_dimension == "color" else "サイズ(尺寸)"
    main_apply_type = "main_color" if img_dimension == "color" else "main_size"
    
    for var in product.get("variations", []):
        col = var.get("color", "")
        sz = var.get("size", "")
        
        filter_crit = {}
        if col: filter_crit["颜色"] = col
        if sz: filter_crit["尺寸"] = sz
        if not filter_crit: continue
        
        dim_val = col if img_dimension == "color" else sz
        covered = has_dim_images and dim_val in applied_dim_values
        if covered:
            print(f"Skipping {col}/{sz}, already covered in dim {dim_val}", flush=True)
            continue
            
        v_main_img_path = dim_images_map.get(dim_val, "")
        abs_main = FileService.resolve_image_path(v_main_img_path) if v_main_img_path else ""
        
        print(f"\n--- Processing Variation: {col} / {sz} ---", flush=True)
        print(f"  abs_main: {abs_main}", flush=True)
        
        # 1. Main image
        if abs_main and os.path.exists(abs_main):
            print(f"  Uploading main image: {abs_main}...", flush=True)
            main_ok = engine.upload_variation_image(filter_criteria=filter_crit, image_path=abs_main, image_type="main", timeout_ms=30000)
            print(f"  Main image upload result: {main_ok}", flush=True)
        else:
            main_ok = False
            
        # 2. Extra images
        if not extra_applied and parent_extra_abs_files:
            print(f"  Uploading extra images ({len(parent_extra_abs_files)} images)...", flush=True)
            extra_ok = engine.upload_variation_image(filter_criteria=filter_crit, image_path=parent_extra_abs_files, image_type="extra", timeout_ms=60000)
            print(f"  Extra images upload result: {extra_ok}", flush=True)
            
            print(f"  Applying extra images to all variations (extra_all)...", flush=True)
            extra_apply_ok = False
            for attempt in range(3):
                print(f"    Attempt {attempt+1} to apply extra_all...", flush=True)
                if engine.apply_variation_image(filter_criteria=filter_crit, apply_type="extra_all", timeout_ms=15000):
                    extra_apply_ok = True
                    print("    ✅ apply_variation_image(extra_all) SUCCESS!", flush=True)
                    break
                time.sleep(1.0)
            if extra_ok and extra_apply_ok:
                extra_applied = True
                print("  🎉 Extra images successfully applied to all variations!", flush=True)
            else:
                print(f"  ❌ Extra images apply failed! extra_ok={extra_ok}, extra_apply_ok={extra_apply_ok}", flush=True)
                
        # 3. Main image apply to dimension
        if main_ok and has_dim_images and dim_val:
            print(f"  Applying main image to same {dim_label}...", flush=True)
            main_apply_ok = False
            for attempt in range(3):
                print(f"    Attempt {attempt+1} to apply {main_apply_type}...", flush=True)
                if engine.apply_variation_image(filter_criteria=filter_crit, apply_type=main_apply_type, timeout_ms=15000):
                    main_apply_ok = True
                    print(f"    ✅ apply_variation_image({main_apply_type}) SUCCESS!", flush=True)
                    break
                time.sleep(1.0)
            if main_apply_ok:
                applied_dim_values.add(dim_val)

if __name__ == "__main__":
    test_phase5()
