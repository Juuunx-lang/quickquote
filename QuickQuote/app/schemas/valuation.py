from typing import Any

from pydantic import BaseModel, Field


class TextValuationRequest(BaseModel):
    product_info: str = Field(..., description="商品信息文本")


class AskRequest(BaseModel):
    context_id: str = Field(..., description="上下文ID")
    question: str = Field(..., description="追问内容")


class ValuationPayload(BaseModel):
    request_id: str = ""
    items: list[dict[str, Any]]
    errors: list[dict[str, Any]] = []
    query_summary: str
    extract_failed_fallback_used: bool = False
    context_id: str
