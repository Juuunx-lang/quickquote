from typing import Any

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    code: int = Field(default=200)
    msg: str = Field(default="success")
    data: Any = Field(default=None)


def success_response(data: Any) -> ApiResponse:
    return ApiResponse(code=200, msg="success", data=data)
