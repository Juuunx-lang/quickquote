import io
import base64
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import UploadFile
from openpyxl import load_workbook
from pypdf import PdfReader

from app.core.exceptions import BusinessError


class ParserService:
    def __init__(self) -> None:
        pass

    async def parse_upload_file(self, file: UploadFile) -> str:
        ext = Path(file.filename or "").suffix.lower()
        raw = await file.read()
        return self.parse_file_bytes(file_name=file.filename or "", raw=raw, ext=ext)

    def parse_inputs(
        self, input_text: str, input_files: list[dict[str, Any]]
    ) -> dict[str, Any]:
        source_payloads: list[dict[str, Any]] = []
        image_assets: list[dict[str, str]] = []
        if input_text.strip():
            source_payloads.append(
                {"source_type": "text", "text": input_text.strip(), "chunks": self._split_chunks(input_text.strip())}
            )

        for item in input_files:
            file_name = str(item.get("file_name", ""))
            raw = item.get("file_content", b"")
            if not isinstance(raw, (bytes, bytearray)):
                continue
            parsed = self._parse_file_payload(file_name=file_name, raw=bytes(raw))
            source_payloads.append(parsed)
            image_assets.extend(parsed.get("image_assets", []))

        all_texts: list[str] = []
        all_chunks: list[str] = []
        for payload in source_payloads:
            text = payload.get("text", "")
            chunks = payload.get("chunks", [])
            if text:
                all_texts.append(text)
            if chunks:
                all_chunks.extend(chunks)

        normalized_text = "\n".join([text for text in all_texts if text]).strip()
        return {
            "user_question": input_text.strip(),
            "normalized_text": normalized_text,
            "ocr_text": "",
            "chunks": all_chunks[:120],
            "sources": source_payloads,
            "image_assets": image_assets[:12],
        }

    def parse_file_bytes(self, file_name: str, raw: bytes, ext: str | None = None) -> str:
        ext = (ext or Path(file_name).suffix).lower()
        if not raw:
            raise BusinessError("文件为空，无法解析")

        if ext == ".txt":
            return raw.decode("utf-8", errors="ignore").strip()
        if ext == ".pdf":
            return self._parse_pdf(raw)
        if ext in {".xlsx", ".xls"}:
            return self._parse_excel(raw)["text"]
        if ext in {".jpg", ".jpeg", ".png"}:
            return "图片文件（待多模态模型解析）"
        raise BusinessError(f"不支持的文件格式: {ext}")

    def _parse_file_payload(self, file_name: str, raw: bytes) -> dict[str, Any]:
        ext = Path(file_name).suffix.lower()
        if not raw:
            raise BusinessError("文件为空，无法解析")
        if ext == ".txt":
            text = raw.decode("utf-8", errors="ignore").strip()
            return {"source_type": "txt", "file_name": file_name, "text": text, "chunks": self._split_chunks(text)}
        if ext == ".pdf":
            text = self._parse_pdf(raw)
            return {"source_type": "pdf", "file_name": file_name, "text": text, "chunks": self._split_chunks(text)}
        if ext in {".xlsx", ".xls"}:
            excel_payload = self._parse_excel(raw)
            excel_payload["file_name"] = file_name
            return excel_payload
        if ext in {".jpg", ".jpeg", ".png"}:
            return {
                "source_type": "image",
                "file_name": file_name,
                "text": "图片文件（待多模态模型解析）",
                "chunks": [],
                "image_assets": [
                    {
                        "file_name": file_name,
                        "mime_type": self._guess_mime_type(file_name),
                        "base64": base64.b64encode(raw).decode("utf-8"),
                    }
                ],
            }
        raise BusinessError(f"不支持的文件格式: {ext}")

    @staticmethod
    def _parse_pdf(raw: bytes) -> str:
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if not text:
            raise BusinessError("PDF 解析失败或无可提取文本")
        return text

    def _parse_excel(self, raw: bytes) -> dict[str, Any]:
        excel_file = io.BytesIO(raw)
        xls = pd.ExcelFile(excel_file)
        text_blocks: list[str] = []
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            if df.empty:
                continue
            rows = df.fillna("").astype(str).head(500).to_dict(orient="records")
            lines = []
            for row in rows:
                row_text = "；".join([f"{k}:{v}" for k, v in row.items() if str(v).strip()])
                if row_text:
                    lines.append(row_text)
            if lines:
                text_blocks.append(f"[Sheet:{sheet_name}]\n" + "\n".join(lines))

        image_assets = self._extract_excel_images(raw)
        if image_assets:
            text_blocks.append(f"[ExcelImages] 共{len(image_assets)}张图片，待多模态模型解析")

        merged_text = "\n".join(text_blocks).strip()
        if not merged_text:
            raise BusinessError("Excel 文件无有效文本或图片内容")
        return {
            "source_type": "excel",
            "text": merged_text,
            "chunks": self._split_chunks(merged_text),
            "image_assets": image_assets,
        }

    def _extract_excel_images(self, raw: bytes) -> list[dict[str, str]]:
        wb = load_workbook(io.BytesIO(raw))
        images: list[dict[str, str]] = []
        for ws in wb.worksheets:
            for image in getattr(ws, "_images", []):
                try:
                    image_raw = image._data()
                except Exception:
                    continue
                images.append(
                    {
                        "file_name": f"{ws.title}_image",
                        "mime_type": "image/png",
                        "base64": base64.b64encode(image_raw).decode("utf-8"),
                    }
                )
        return images[:10]

    @staticmethod
    def _split_chunks(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
        normalized = (text or "").strip()
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + chunk_size)
            chunks.append(normalized[start:end])
            if end == len(normalized):
                break
            start = max(0, end - overlap)
        return chunks

    @staticmethod
    def _guess_mime_type(file_name: str) -> str:
        ext = Path(file_name).suffix.lower()
        if ext in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if ext == ".png":
            return "image/png"
        return "application/octet-stream"


parser_service = ParserService()
