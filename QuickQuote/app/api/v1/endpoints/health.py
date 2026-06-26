from fastapi import APIRouter

from app.schemas.common import ApiResponse

router = APIRouter()


@router.get("/health", response_model=ApiResponse)
async def health() -> ApiResponse:
    return ApiResponse(code=200, msg="服务正常", data=None)
