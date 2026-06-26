import json
import re
from typing import Any

from app.core.config import settings
from app.services.llm_service import llm_service
from app.services.parser_service import parser_service


class ExtractService:
    async def extract_items(
        self,
        input_text: str,
        excel_rows: list[str],
        input_files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        merged_input_text = self._merge_text(input_text=input_text, excel_rows=excel_rows)
        parsed_payload = parser_service.parse_inputs(input_text=merged_input_text, input_files=input_files)

        fallback_used = False
        items: list[dict[str, str]] = []
        try:
            requirements = await llm_service.analyze_multimodal_requirements(parsed_payload)
            items = self._normalize_extracted_items(requirements.get("items", []))
        except Exception:
            items = []
            fallback_used = True

        if not items:
            fallback_used = True
            items = self._fallback_extract_items(input_text=input_text, excel_rows=excel_rows)

        if not items:
            fallback_used = True
            items = [{"input_text": merged_input_text[:200], "product_name": "", "product_model": ""}]

        items = self._dedupe_items(items)
        return {
            "items": items[: max(1, settings.MAX_INPUT_ITEMS)],
            "extract_failed_fallback_used": fallback_used,
            "parsed_payload": parsed_payload,
        }

    @staticmethod
    def parse_excel_rows(raw: str) -> list[str]:
        text = (raw or "").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        rows: list[str] = []
        for item in payload:
            if item is None:
                continue
            value = str(item).strip()
            if value:
                rows.append(value)
        return rows

    @staticmethod
    def _merge_text(input_text: str, excel_rows: list[str]) -> str:
        parts: list[str] = []
        if (input_text or "").strip():
            parts.append(input_text.strip())
        if excel_rows:
            parts.append("Excel拆分行：\n" + "\n".join(excel_rows[: settings.MAX_INPUT_ITEMS]))
        return "\n\n".join(parts).strip()

    @staticmethod
    def _normalize_extracted_items(raw_items: Any) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if not isinstance(raw_items, list):
            return items
        for row in raw_items[: settings.MAX_INPUT_ITEMS]:
            if not isinstance(row, dict):
                continue
            product_name = str(row.get("product_name", "")).strip()
            product_model = str(row.get("product_model", row.get("purchase_model", ""))).strip()
            if product_name.lower() in {"未知", "unknown", "null", "none"}:
                product_name = ""
            if product_model.lower() in {"未知", "unknown", "null", "none"}:
                product_model = ""
            if not product_name and not product_model:
                continue
            items.append(
                {
                    "input_text": f"{product_name} {product_model}".strip(),
                    "product_name": product_name,
                    "product_model": product_model,
                }
            )
        return items

    def _fallback_extract_items(self, input_text: str, excel_rows: list[str]) -> list[dict[str, str]]:
        rows = [*excel_rows]
        if (input_text or "").strip():
            rows.extend([line.strip() for line in re.split(r"[\n\r]+", input_text) if line.strip()])
        if not rows and (input_text or "").strip():
            rows = [input_text.strip()]
        items: list[dict[str, str]] = []
        for row in rows[: settings.MAX_INPUT_ITEMS]:
            product_name, product_model = self._extract_name_model_from_text(row)
            if not product_name and not product_model:
                continue
            items.append({"input_text": row, "product_name": product_name, "product_model": product_model})
        return items

    @staticmethod
    def _dedupe_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            key = (
                str(item.get("product_name", "")).strip().lower(),
                str(item.get("product_model", "")).strip().lower(),
                str(item.get("input_text", "")).strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _extract_name_model_from_text(text: str) -> tuple[str, str]:
        normalized = (text or "").strip()
        if not normalized:
            return "", ""
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-_/.]{1,79}", normalized):
            return "", normalized
        name_match = re.search(r"(?:商品名称|名称|品名)[:：]\s*([^\n,，;；]+)", normalized)
        model_match = re.search(r"(?:型号|规格型号|model)[:：]?\s*([A-Za-z0-9\-_/\.]+)", normalized, flags=re.I)
        product_name = name_match.group(1).strip() if name_match else ""
        product_model = model_match.group(1).strip() if model_match else ""
        if not product_name:
            if product_model:
                product_name = re.sub(r"[A-Za-z0-9\-_/.]+", "", normalized).strip(" -:：,，;；")
            else:
                product_name = normalized.split(" ")[0][:100].strip()
        return product_name, product_model


extract_service = ExtractService()
