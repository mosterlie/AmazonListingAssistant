from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field
from server.services.erp_bridge import ERPBridgeService
from server.services.deepseek_service import DeepSeekService

router = APIRouter(prefix="/api/automation", tags=["店小秘自动化上件与 AI 辅助"])


class DeepSeekPromptSchema(BaseModel):
    prompt: str = Field(..., description="待发送至 DeepSeek 的提示词")
    target_url: Optional[str] = Field(None, description="指定 DeepSeek 会话链接")


@router.post("/publish/{product_id}", summary="触发商品全自动上件到店小秘 ERP")
async def publish_product(product_id: int):
    """根据商品 ID，调起真实浏览器执行自动化上件"""
    res = ERPBridgeService.publish_product_to_erp(product_id)
    return {"code": 0 if res.get("success") else 1, "msg": res.get("msg"), "data": res}


@router.post("/deepseek-generate", summary="自动跳转 DeepSeek 填入提示词、提交、点击复制并回填")
async def generate_deepseek_prompt(data: DeepSeekPromptSchema):
    """调起 Chrome 浏览器打开 DeepSeek 目标会话，自动填入提示词、点击发送并在完成后点击复制"""
    res = DeepSeekService.send_prompt_to_deepseek(prompt=data.prompt, target_url=data.target_url)
    return {"code": 0 if res.get("success") else 1, "msg": res.get("msg"), "data": res.get("data", {})}

