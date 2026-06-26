import asyncio
import json
import logging
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class QuoteArchiveService:
    def __init__(self) -> None:
        self._root_dir = Path(settings.QUOTE_ARCHIVE_DIR)

    async def save_quote_record(
        self,
        *,
        request_id: str,
        context_id: str,
        input_text: str,
        excel_rows: list[str],
        images: list[dict[str, Any]],
        raw_files: list[dict[str, Any]],
        extracted_items: list[dict[str, Any]],
        system_output: dict[str, Any],
    ) -> None:
        timestamp = datetime.now().replace(microsecond=0)
        record = {
            "record_type": "quote",
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "request_id": request_id,
            "context_id": context_id,
            "user_question": {
                "input_text": input_text or "",
                "excel_rows": excel_rows or [],
                "images": self._file_metadata(images),
                "raw_files": self._file_metadata(raw_files),
            },
            "quoted_items": extracted_items or [],
            "system_answer": system_output.get("query_summary", ""),
            "system_output": system_output,
        }
        await self._save_record(record_type="quote", timestamp=timestamp, record=record, stem_id=request_id)

    async def save_followup_record(
        self,
        *,
        context_id: str,
        question: str,
        answer: str,
    ) -> None:
        timestamp = datetime.now().replace(microsecond=0)
        record = {
            "record_type": "followup",
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "context_id": context_id,
            "user_question": question or "",
            "system_answer": answer or "",
        }
        await self._save_record(record_type="followup", timestamp=timestamp, record=record, stem_id=context_id)

    async def _save_record(
        self,
        *,
        record_type: str,
        timestamp: datetime,
        record: dict[str, Any],
        stem_id: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._write_record,
                record_type=record_type,
                timestamp=timestamp,
                record=record,
                stem_id=stem_id,
            )
        except Exception as exc:
            logger.warning("quote archive write failed detail=%s", str(exc).strip() or repr(exc))

    def _write_record(
        self,
        *,
        record_type: str,
        timestamp: datetime,
        record: dict[str, Any],
        stem_id: str,
    ) -> None:
        day_dir = self._root_dir / timestamp.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        file_name = (
            f"{record_type}_{timestamp.strftime('%H%M%S')}_"
            f"{self._safe_filename_part(stem_id) or uuid.uuid4().hex[:12]}.json"
        )
        target = day_dir / file_name
        if target.exists():
            target = day_dir / (
                f"{record_type}_{timestamp.strftime('%H%M%S')}_"
                f"{self._safe_filename_part(stem_id) or uuid.uuid4().hex[:12]}_{uuid.uuid4().hex[:8]}.json"
            )
        target.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=self._json_default),
            encoding="utf-8",
        )

    @staticmethod
    def _file_metadata(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        metadata: list[dict[str, Any]] = []
        for item in files or []:
            if not isinstance(item, dict):
                continue
            content = item.get("file_content")
            size = len(content) if isinstance(content, (bytes, bytearray)) else None
            metadata.append(
                {
                    "file_name": str(item.get("file_name", "") or ""),
                    "size_bytes": size,
                }
            )
        return metadata

    @staticmethod
    def _safe_filename_part(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
        return safe[:64].strip("_")

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, (bytes, bytearray)):
            return f"<bytes:{len(value)}>"
        return str(value)


quote_archive_service = QuoteArchiveService()
