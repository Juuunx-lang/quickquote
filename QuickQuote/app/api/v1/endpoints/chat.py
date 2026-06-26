from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db_session
from app.schemas.common import ApiResponse, success_response
from app.schemas.valuation import AskRequest
from app.services.chat_job_service import chat_job_service
from app.services.chat_stream_service import build_chat_stream_response, prepare_chat_payload
from app.workflow.graph import valuation_workflow

router = APIRouter()


@router.post("/chat/ask", response_model=ApiResponse)
async def ask_followup(
    request: AskRequest, session: AsyncSession = Depends(get_db_session)
) -> ApiResponse:
    answer = await valuation_workflow.answer_followup(
        session=session, context_id=request.context_id, question=request.question
    )
    return success_response({"context_id": request.context_id, "answer": answer})


@router.post("/chat/stream")
async def chat_stream(
    input_text: str = Form(default=""),
    excel_rows: str = Form(default=""),
    enable_fuzzy_code_match: bool = Form(default=False),
    images: list[UploadFile] = File(default=[]),
    raw_files: list[UploadFile] = File(default=[]),
    product_info: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    # 向后兼容旧协议：product_info/files
    normalized_input_text = (input_text or "").strip() or (product_info or "").strip()
    normalized_images = images or []
    normalized_raw_files = raw_files or files or []
    return await build_chat_stream_response(
        session=session,
        input_text=normalized_input_text,
        excel_rows=excel_rows,
        enable_fuzzy_code_match=enable_fuzzy_code_match,
        images=normalized_images,
        raw_files=normalized_raw_files,
    )


@router.post("/chat/jobs", response_model=ApiResponse)
async def create_chat_job(
    input_text: str = Form(default=""),
    excel_rows: str = Form(default=""),
    enable_fuzzy_code_match: bool = Form(default=False),
    images: list[UploadFile] = File(default=[]),
    raw_files: list[UploadFile] = File(default=[]),
    product_info: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
) -> ApiResponse:
    normalized_input_text = (input_text or "").strip() or (product_info or "").strip()
    normalized_images = images or []
    normalized_raw_files = raw_files or files or []
    payload = await prepare_chat_payload(
        input_text=normalized_input_text,
        excel_rows=excel_rows,
        enable_fuzzy_code_match=enable_fuzzy_code_match,
        images=normalized_images,
        raw_files=normalized_raw_files,
    )
    job_id = await chat_job_service.create_job(payload)
    return success_response(
        {
            "job_id": job_id,
            "status": "queued",
            "threshold": settings.JOB_INPUT_THRESHOLD,
        }
    )


@router.get("/chat/jobs/{job_id}/stream")
async def stream_chat_job(job_id: str) -> StreamingResponse:
    return StreamingResponse(chat_job_service.stream_job(job_id), media_type="text/event-stream")
