"""
广告分析 REST API 路由
- 导入: 在线产品/广告活动/广告组 三份 Excel (xlsx)
- 数据关联: 活动→产品 ASIN 匹配, 标记是否开通自动广告
- 清空: 一键删除全部已导入及已处理的数据
- 视图: 产品(子) 分页 / 产品(父) 聚合 / 广告研判 广告组汇总 (时间范围+标记筛选+排序+分页)
- 统计结果: 参数组合ASIN汇总 + 未投广父SKU代表ASIN + 重复ASIN
- 人工标记: 广告研判新每日预算/新默认竞价 (单条/批量/清除)
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from typing import Dict, Any

from server.dependencies import get_current_user
from server.services.ads_service import AdsService

router = APIRouter(prefix="/api/ads-analysis", tags=["Ads Analysis"])

_XLSX_EXTS = (".xlsx", ".xlsm")


def _check_xlsx(file: UploadFile, content: bytes):
    name = (file.filename or "").lower()
    if not name.endswith(_XLSX_EXTS):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 格式的 Excel 文件")
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 30MB 上限")


async def _import(file: UploadFile, fn) -> Dict[str, Any]:
    """通用导入: 读取内容 → 校验 → 交给 service 解析"""
    content = await file.read()
    _check_xlsx(file, content)
    try:
        return fn(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {e}")


# ─────────────────────────── 导入 ───────────────────────────

@router.post("/import/products", summary="导入在线产品 Excel (全量替换)")
async def import_products(file: UploadFile = File(...),
                          current_user: Dict[str, Any] = Depends(get_current_user)):
    result = await _import(file, AdsService.import_products)
    return {"code": 0, "msg": f"在线产品导入成功，共 {result['count']} 条", "data": result}


@router.post("/import/campaigns", summary="导入广告活动 Excel (按日期+活动名幂等)")
async def import_campaigns(file: UploadFile = File(...),
                           current_user: Dict[str, Any] = Depends(get_current_user)):
    result = await _import(file, AdsService.import_campaigns)
    return {"code": 0, "msg": f"广告活动导入成功，共 {result['count']} 条", "data": result}


@router.post("/import/groups", summary="导入广告组 Excel (按日期+组名+活动幂等)")
async def import_groups(file: UploadFile = File(...),
                        current_user: Dict[str, Any] = Depends(get_current_user)):
    result = await _import(file, AdsService.import_groups)
    return {"code": 0, "msg": f"广告组导入成功，共 {result['count']} 条", "data": result}


# ─────────────────────────── 关联 / 状态 / 清空 ───────────────────────────

@router.post("/link", summary="数据关联: 活动↔产品↔广告组 全量重算")
async def link_data(current_user: Dict[str, Any] = Depends(get_current_user)):
    stats = AdsService.link_data()
    msg = (f"关联完成：{stats['campaigns_linked']}/{stats['campaigns_total']} 个广告活动已关联产品，"
           f"{stats['products_with_ad']} 个产品开通自动广告")
    if stats["unmatched_asins"]:
        msg += f"；{len(stats['unmatched_asins'])} 个活动ASIN未匹配到产品"
    return {"code": 0, "msg": msg, "data": stats}


@router.post("/clear", summary="清空所有已导入及已处理的数据")
async def clear_data(current_user: Dict[str, Any] = Depends(get_current_user)):
    cleared = AdsService.clear_all()
    msg = (f"已清空全部数据：在线产品 {cleared['products']} 条、广告活动 {cleared['campaigns']} 条、"
           f"广告组 {cleared['groups']} 条、人工标记 {cleared.get('marks', 0)} 条")
    return {"code": 0, "msg": msg, "data": cleared}


@router.get("/status", summary="导入状态概览")
async def import_status(current_user: Dict[str, Any] = Depends(get_current_user)):
    return {"code": 0, "data": AdsService.get_status()}


# ─────────────────────────── 三视图 ───────────────────────────

@router.get("/products", summary="在线产品-子 列表 (筛选/排序/分页)")
async def list_products(auto_ad: str = "", keyword: str = "", sort: str = "", order: str = "desc",
                        page: int = 1, page_size: int = 50,
                        current_user: Dict[str, Any] = Depends(get_current_user)):
    return {"code": 0, "data": AdsService.get_products(
        auto_ad=auto_ad, keyword=keyword, sort=sort, order=order,
        page=page, page_size=page_size)}


@router.get("/parents", summary="在线产品-父 列表 (父SKU聚合, 筛选/排序)")
async def list_parents(keyword: str = "", has_ad: str = "", sort: str = "", order: str = "desc",
                       current_user: Dict[str, Any] = Depends(get_current_user)):
    return {"code": 0, "data": AdsService.get_parents(
        keyword=keyword, has_ad=has_ad, sort=sort, order=order)}


@router.get("/research", summary="广告研判 列表 (一条=一个广告组, 跨日期汇总, 支持排序分页)")
async def list_research(keyword: str = "", days: str = "", marked: str = "",
                        sort: str = "", order: str = "desc",
                        page: int = 1, page_size: int = 20,
                        current_user: Dict[str, Any] = Depends(get_current_user)):
    return {"code": 0, "data": AdsService.get_research(
        keyword=keyword, days=days, marked=marked, sort=sort, order=order,
        page=page, page_size=page_size)}


@router.get("/stats", summary="统计结果: 参数组合ASIN汇总 + 未投广ASIN集合")
async def get_stats(current_user: Dict[str, Any] = Depends(get_current_user)):
    return {"code": 0, "data": AdsService.get_stats()}


# ─────────────────────────── 广告研判: 人工标记 ───────────────────────────

@router.post("/marks/clear", summary="清除全部人工标记的内容")
async def clear_marks(current_user: Dict[str, Any] = Depends(get_current_user)):
    data = AdsService.clear_group_marks()
    return {"code": 0, "msg": f"已清除 {data['cleared']} 条标记", "data": data}


@router.post("/marks/batch", summary="批量设置选中行的新每日预算/新默认竞价")
async def save_marks_batch(payload: Dict[str, Any],
                           current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        data = AdsService.save_group_marks(payload.get("group_names") or [],
                                           payload.get("new_budget", ""),
                                           payload.get("new_bid", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 0, "msg": f"已批量设置 {data['updated']} 条", "data": data}


@router.post("/marks", summary="保存广告研判人工录入的新每日预算/新默认竞价")
async def save_mark(payload: Dict[str, str],
                    current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        data = AdsService.save_group_mark(payload.get("group_name", ""),
                                          payload.get("new_budget", ""),
                                          payload.get("new_bid", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    msg = "已保存并标记" if data["marked"] else "已取消标记"
    return {"code": 0, "msg": msg, "data": data}
