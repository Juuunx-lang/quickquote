import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas.common import ApiResponse

logger = logging.getLogger(__name__)


class BusinessError(Exception):
    def __init__(self, message: str, code: int = 500) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessError)
    async def handle_business_error(_: Request, exc: BusinessError) -> JSONResponse:
        logger.warning("BusinessError: %s", exc.message)
        response = ApiResponse(code=exc.code, msg=exc.message, data=None)
        return JSONResponse(status_code=200, content=response.model_dump())

    @app.exception_handler(Exception)
    async def handle_unknown_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", exc_info=exc)
        response = ApiResponse(code=500, msg=f"系统异常: {exc}", data=None)
        return JSONResponse(status_code=200, content=response.model_dump())
