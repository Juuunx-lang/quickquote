import asyncio
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

from app.core.config import settings


class SupplierQuoteService:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or str(
            Path(__file__).resolve().parents[3] / "brand_item_price" / "price.db"
        )

    async def query_candidates_by_items(
        self,
        items: list[dict[str, Any]],
        limit: int | None = None,
        enable_fuzzy_code_match: bool = False,
    ) -> list[dict[str, Any]]:
        safe_limit = self._safe_limit(limit)
        normalized_items = [item or {} for item in items or []]
        if not normalized_items:
            return []
        return await asyncio.to_thread(
            self._query_candidates_sync,
            normalized_items,
            safe_limit,
            bool(enable_fuzzy_code_match),
        )

    def _query_candidates_sync(
        self,
        items: list[dict[str, Any]],
        limit: int,
        enable_fuzzy_code_match: bool,
    ) -> list[dict[str, Any]]:
        groups = [
            {"idx": idx, "item": item, "candidates": [], "provider_error": ""}
            for idx, item in enumerate(items, start=1)
        ]
        db_file = Path(self._db_path)
        if not db_file.exists():
            return [
                {**group, "provider_error": f"supplier_quote_db_missing:{db_file}"}
                for group in groups
            ]

        with sqlite3.connect(str(db_file)) as conn:
            conn.row_factory = sqlite3.Row
            for group in groups:
                item = group.get("item", {}) or {}
                candidates = self._query_item_candidates(
                    conn=conn,
                    item=item,
                    limit=limit,
                    enable_fuzzy_code_match=enable_fuzzy_code_match,
                )
                group["candidates"] = self._dedupe_candidates(candidates, limit=limit)
        return groups

    def _query_item_candidates(
        self,
        conn: sqlite3.Connection,
        item: dict[str, Any],
        limit: int,
        enable_fuzzy_code_match: bool,
    ) -> list[dict[str, Any]]:
        input_terms = self._input_terms_for_item(item)
        if not input_terms:
            return []

        sql = """
            SELECT
                bi.id AS brand_item_id,
                bi.item_code,
                bi.item_name,
                bi.series,
                bi.item_type AS quote_item_type,
                bi.model,
                bi.factory_model,
                bi.spec,
                bi.key_features,
                bi.properties,
                bi.packing_qty,
                bi.min_order_qty,
                bi.unit,
                bi.attachment,
                bi.created_at AS item_created_at,
                b.brand_code,
                b.brand_name,
                b.status AS brand_status,
                bcp.supply_price,
                bcp.retail_price,
                bcp.discount_price,
                bcp.currency,
                bcp.sales_status,
                bcp.remark,
                bcp.updated_at AS quote_updated_at
            FROM brand_item bi
            LEFT JOIN brand b ON b.id = bi.brand_id
            LEFT JOIN brand_current_price bcp ON bcp.brand_item_id = bi.id
        """
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in conn.execute(sql).fetchall():
            row_dict = dict(row)
            score = self._match_row_score(
                row=row_dict,
                input_terms=input_terms,
                enable_fuzzy_code_match=enable_fuzzy_code_match,
            )
            if score <= 0:
                continue
            candidate = self._map_row(row_dict, item=item)
            candidate["match_score"] = score
            scored.append((score, candidate))

        scored.sort(
            key=lambda pair: (
                -pair[0],
                0 if pair[1].get("supplier_quote_price") is not None else 1,
                0 if pair[1].get("supplier_quote_sales_status") == "ON_SALE" else 1,
                str(pair[1].get("supplier_quote_updated_at") or ""),
            )
        )
        return [candidate for _, candidate in scored[:limit]]

    @staticmethod
    def _map_row(row: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        item_code = SupplierQuoteService._normalize_text(row.get("item_code"))
        model = SupplierQuoteService._normalize_text(row.get("model"))
        factory_model = SupplierQuoteService._normalize_text(row.get("factory_model"))
        sku_id = item_code or model or factory_model or str(row.get("brand_item_id") or "")
        quote_record = {
            "brand_item_id": row.get("brand_item_id"),
            "item_code": item_code,
            "item_name": SupplierQuoteService._normalize_text(row.get("item_name")),
            "model": model,
            "factory_model": factory_model,
            "spec": SupplierQuoteService._normalize_text(row.get("spec")),
            "brand_code": SupplierQuoteService._normalize_text(row.get("brand_code")),
            "brand_name": SupplierQuoteService._normalize_text(row.get("brand_name")),
            "supplier_name": SupplierQuoteService._normalize_text(row.get("brand_name")),
            "supply_price": row.get("supply_price"),
            "retail_price": row.get("retail_price"),
            "discount_price": row.get("discount_price"),
            "currency": SupplierQuoteService._normalize_text(row.get("currency")) or "CNY",
            "sales_status": SupplierQuoteService._normalize_text(row.get("sales_status")),
            "remark": SupplierQuoteService._normalize_text(row.get("remark")),
            "updated_at": row.get("quote_updated_at"),
        }
        return {
            "item_type": "supplier_quote",
            "sku_id": sku_id,
            "sku_code": item_code,
            "product_code": item_code,
            "product_name": quote_record["item_name"] or str(item.get("product_name", "")).strip(),
            "brand": quote_record["brand_name"],
            "purchase_model": model or factory_model or item_code,
            "purchase_spec": quote_record["spec"] or SupplierQuoteService._normalize_text(row.get("key_features")),
            "unit": SupplierQuoteService._normalize_text(row.get("unit")),
            "supplier_quote_supplier_name": quote_record["supplier_name"],
            "supplier_quote_brand_code": quote_record["brand_code"],
            "supplier_quote_item_code": item_code,
            "supplier_quote_model": model,
            "supplier_quote_factory_model": factory_model,
            "supplier_quote_price": row.get("supply_price"),
            "supplier_quote_retail_price": row.get("retail_price"),
            "supplier_quote_discount_price": row.get("discount_price"),
            "supplier_quote_currency": quote_record["currency"],
            "supplier_quote_sales_status": quote_record["sales_status"],
            "supplier_quote_remark": quote_record["remark"],
            "supplier_quote_updated_at": row.get("quote_updated_at"),
            "supplier_quote_records": [quote_record],
            "provider_error": "",
            "source": "supplier_quote",
            "matched_source": "supplier_quote",
            "matched_sources": ["supplier_quote"],
        }

    @staticmethod
    def _input_terms_for_item(item: dict[str, Any]) -> list[str]:
        values = [
            item.get("sku", ""),
            item.get("product_code", ""),
            item.get("product_model", ""),
            item.get("purchase_model", ""),
            item.get("product_name", ""),
            item.get("brand", ""),
            item.get("purchase_spec", ""),
        ]
        terms: list[str] = []
        for value in values:
            text_value = SupplierQuoteService._normalize_match_text(value)
            if len(text_value) < 2:
                continue
            terms.append(text_value[:80])
        return list(dict.fromkeys(terms))

    @staticmethod
    def _match_row_score(
        row: dict[str, Any],
        input_terms: list[str],
        enable_fuzzy_code_match: bool,
    ) -> int:
        code_fields = [
            SupplierQuoteService._normalize_match_text(row.get("item_code")),
            SupplierQuoteService._normalize_match_text(row.get("model")),
            SupplierQuoteService._normalize_match_text(row.get("factory_model")),
        ]
        text_fields = [
            SupplierQuoteService._normalize_match_text(row.get("item_name")),
            SupplierQuoteService._normalize_match_text(row.get("spec")),
            SupplierQuoteService._normalize_match_text(row.get("key_features")),
            SupplierQuoteService._normalize_match_text(row.get("brand_name")),
            SupplierQuoteService._normalize_match_text(row.get("brand_code")),
        ]
        all_fields = [field for field in [*code_fields, *text_fields] if field]

        score = 0
        for term in input_terms:
            if not term:
                continue
            if any(term == field for field in code_fields if field):
                score = max(score, 220)
            elif any(term == field for field in text_fields if field):
                score = max(score, 160)
            elif enable_fuzzy_code_match and any(term in field for field in code_fields if field):
                score = max(score, 120)
            elif (enable_fuzzy_code_match or not SupplierQuoteService._looks_like_code(term)) and any(
                term in field for field in text_fields if field
            ):
                score = max(score, 80)
            elif enable_fuzzy_code_match and any(term in field for field in all_fields):
                score = max(score, 80)
        return score

    @staticmethod
    def _looks_like_code(value: Any) -> bool:
        text = SupplierQuoteService._normalize_match_text(value)
        if len(text) < 4:
            return False
        return bool(re.search(r"[A-Za-z]", text) and re.search(r"\d", text))

    @staticmethod
    def _dedupe_candidates(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in candidates:
            key = str(row.get("sku_id", "") or row.get("product_name", "")).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(row)
            if len(deduped) >= limit:
                break
        return deduped

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or "").replace("\r", " ").replace("\n", " ").strip()

    @staticmethod
    def _normalize_match_text(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or ""))
        text = (
            text.replace("\r", "")
            .replace("\n", "")
            .replace("\t", "")
            .replace("－", "-")
            .replace("–", "-")
            .replace("—", "-")
            .replace("‒", "-")
        )
        text = re.sub(r"[\s_\-./]+", "", text)
        return text.strip().lower()

    @staticmethod
    def _safe_limit(limit: int | None = None) -> int:
        requested = int(limit or settings.QUERY_CANDIDATE_LIMIT)
        return max(1, min(requested, 100))


supplier_quote_service = SupplierQuoteService()
