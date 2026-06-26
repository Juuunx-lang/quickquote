import json
import logging
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.services.extract_service import extract_service
from app.workflow.graph import valuation_workflow

logger = logging.getLogger(__name__)


def validate_file_size(file_size: int) -> None:
    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_size:
        raise BusinessError(f"文件超过大小限制（{settings.MAX_FILE_SIZE_MB}MB）")


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n"


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def parse_bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on", "开启", "开"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off", "关闭", "关", ""}:
        return False
    return False


async def prepare_chat_payload(
    input_text: str = "",
    excel_rows: str = "",
    enable_fuzzy_code_match: Any = False,
    images: list[UploadFile] | None = None,
    raw_files: list[UploadFile] | None = None,
) -> dict[str, Any]:
    normalized_images: list[dict[str, bytes | str]] = []
    for upload in images or []:
        content = await upload.read()
        validate_file_size(len(content))
        normalized_images.append({"file_name": upload.filename or "unknown", "file_content": content})

    normalized_raw_files: list[dict[str, bytes | str]] = []
    for upload in raw_files or []:
        content = await upload.read()
        validate_file_size(len(content))
        normalized_raw_files.append({"file_name": upload.filename or "unknown", "file_content": content})

    return {
        "input_text": input_text,
        "excel_rows": extract_service.parse_excel_rows(excel_rows),
        "enable_fuzzy_code_match": parse_bool_flag(enable_fuzzy_code_match),
        "images": normalized_images,
        "raw_files": normalized_raw_files,
    }


async def build_chat_stream_response(
    session: AsyncSession,
    input_text: str = "",
    excel_rows: str = "",
    enable_fuzzy_code_match: Any = False,
    images: list[UploadFile] | None = None,
    raw_files: list[UploadFile] | None = None,
) -> StreamingResponse:
    payload = await prepare_chat_payload(
        input_text=input_text,
        excel_rows=excel_rows,
        enable_fuzzy_code_match=enable_fuzzy_code_match,
        images=images,
        raw_files=raw_files,
    )

    async def event_stream():
        try:
            async for event in valuation_workflow.stream_multimodal_events(
                session=session,
                input_text=payload["input_text"],
                excel_rows=payload["excel_rows"],
                enable_fuzzy_code_match=payload["enable_fuzzy_code_match"],
                images=payload["images"],
                raw_files=payload["raw_files"],
            ):
                yield sse_event(event["event"], event["data"])
        except Exception as exc:
            detail = str(exc).strip() or repr(exc)
            logger.error("chat/stream failed detail=%s", detail, exc_info=exc)
            yield sse_event("error", {"message": f"流程执行失败: {detail}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
