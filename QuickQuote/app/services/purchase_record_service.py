import re
import unicodedata
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


PURCHASE_RECORD_TABLE = "purchase_records"


class PurchaseRecordService:
    async def query_candidates_by_items(
        self,
        session: AsyncSession,
        items: list[dict[str, Any]],
        limit: int | None = None,
        enable_fuzzy_code_match: bool = False,
    ) -> list[dict[str, Any]]:
        safe_limit = self._safe_limit(limit)
        normalized_items = [item or {} for item in items or []]
        groups = [
            {"idx": idx, "item": item, "candidates": [], "provider_error": ""}
            for idx, item in enumerate(normalized_items, start=1)
        ]
        if not normalized_items:
            return groups

        batch_size = max(1, min(int(getattr(settings, "DB_CANDIDATE_BATCH_SIZE", 25) or 25), 100))
        for start in range(0, len(normalized_items), batch_size):
            indexed_items = [
                (idx, item)
                for idx, item in enumerate(
                    normalized_items[start : start + batch_size],
                    start=start + 1,
                )
            ]
            rows = await self._query_candidate_rows_for_chunk(
                session=session,
                indexed_items=indexed_items,
                per_item_limit=safe_limit,
                enable_fuzzy_code_match=bool(enable_fuzzy_code_match),
            )
            assigned = self._assign_rows_to_items(
                indexed_items=indexed_items,
                rows=rows,
                limit=safe_limit,
                enable_fuzzy_code_match=bool(enable_fuzzy_code_match),
            )
            for idx, candidates in assigned.items():
                groups[idx - 1]["candidates"] = candidates
        return groups

    async def query_external_latest(
        self,
        session: AsyncSession,
        sku_id: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        normalized_sku = (sku_id or "").strip()
        if not normalized_sku:
            return {"latest": None, "history_records": []}

        sql = text(
            """
            SELECT
                id,
                bill_quantity,
                final_purchase_price,
                selling_price,
                settlement_unit_price,
                settlement_amount,
                gross_profit_margin,
                tax_included,
                order_no,
                invoice_type,
                tax_rate,
                product_link,
                supplier_name,
                shop_name,
                unit,
                date
            FROM purchase_records
            WHERE purchase_model = :sku_id
            ORDER BY
                CASE WHEN final_purchase_price IS NOT NULL THEN 0 ELSE 1 END,
                CASE WHEN selling_price IS NOT NULL THEN 0 ELSE 1 END,
                date DESC,
                id DESC
            LIMIT :limit
            """
        )
        safe_limit = max(1, min(int(limit or settings.QUERY_CANDIDATE_LIMIT), settings.QUERY_CANDIDATE_LIMIT))
        rows = (await session.execute(sql, {"sku_id": normalized_sku, "limit": safe_limit})).mappings().all()
        history = [self._map_row(dict(row)) for row in rows]
        latest = history[0] if history else None
        return {"latest": latest, "history_records": history}

    async def query_external_latest_by_skus(
        self,
        session: AsyncSession,
        sku_ids: list[str],
        limit: int | None = None,
    ) -> dict[str, dict[str, Any]]:
        normalized_skus = list(dict.fromkeys(str(sku or "").strip() for sku in sku_ids if str(sku or "").strip()))
        if not normalized_skus:
            return {}

        safe_limit = max(1, min(int(limit or settings.QUERY_CANDIDATE_LIMIT), settings.QUERY_CANDIDATE_LIMIT))
        sql = (
            text(
                """
                SELECT
                    id,
                    purchase_model,
                    bill_quantity,
                    final_purchase_price,
                    selling_price,
                    settlement_unit_price,
                    settlement_amount,
                    gross_profit_margin,
                    tax_included,
                    order_no,
                    invoice_type,
                    tax_rate,
                    product_link,
                    supplier_name,
                    shop_name,
                    unit,
                    date
                FROM (
                    SELECT
                        id,
                        purchase_model,
                        bill_quantity,
                        final_purchase_price,
                        selling_price,
                        settlement_unit_price,
                        settlement_amount,
                        gross_profit_margin,
                        tax_included,
                        order_no,
                        invoice_type,
                        tax_rate,
                        product_link,
                        supplier_name,
                        shop_name,
                        unit,
                        date,
                        ROW_NUMBER() OVER (
                            PARTITION BY purchase_model
                            ORDER BY
                                CASE WHEN final_purchase_price IS NOT NULL THEN 0 ELSE 1 END,
                                CASE WHEN selling_price IS NOT NULL THEN 0 ELSE 1 END,
                                date DESC,
                                id DESC
                        ) AS rn
                    FROM purchase_records
                    WHERE purchase_model IN :sku_ids
                ) ranked
                WHERE rn <= :limit
                ORDER BY purchase_model, date DESC
                """
            )
            .bindparams(bindparam("sku_ids", expanding=True))
        )

        try:
            rows = (
                await session.execute(sql, {"sku_ids": normalized_skus, "limit": safe_limit})
            ).mappings().all()
        except Exception:
            await session.rollback()
            result: dict[str, dict[str, Any]] = {}
            for sku_id in normalized_skus:
                result[sku_id] = await self.query_external_latest(session=session, sku_id=sku_id, limit=safe_limit)
            return result

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            record = dict(row)
            sku_id = str(record.pop("purchase_model", "")).strip()
            if not sku_id:
                continue
            grouped.setdefault(sku_id, []).append(self._map_row(record))

        return {
            sku_id: {"latest": history[0] if history else None, "history_records": history}
            for sku_id, history in grouped.items()
        }

    async def query_sku_ids_by_fuzzy_code(
        self,
        session: AsyncSession,
        item: dict[str, Any],
        limit: int = 50,
    ) -> list[str]:
        terms = self._fuzzy_code_terms_for_item(item)
        if not terms:
            return []

        conditions: list[str] = []
        params: dict[str, Any] = {}
        purchase_model_expr = self._sql_normalized_expr("purchase_model")
        for idx, term in enumerate(terms):
            param_name = f"kw_{idx}"
            params[param_name] = f"%{term}%"
            conditions.append(f"{purchase_model_expr} LIKE :{param_name}")
        params["limit"] = max(1, min(int(limit or 50), 100))

        sql = text(
            f"""
            SELECT
                purchase_model,
                MAX(date) AS latest_date,
                MAX(id) AS latest_id,
                MAX(CASE WHEN final_purchase_price IS NOT NULL THEN 1 ELSE 0 END) AS has_purchase_price,
                MAX(CASE WHEN selling_price IS NOT NULL THEN 1 ELSE 0 END) AS has_selling_price
            FROM purchase_records
            WHERE purchase_model IS NOT NULL
              AND TRIM(purchase_model) <> ''
              AND ({" OR ".join(conditions)})
            GROUP BY purchase_model
            ORDER BY has_purchase_price DESC, has_selling_price DESC, latest_date DESC, latest_id DESC
            LIMIT :limit
            """
        )
        rows = (await session.execute(sql, params)).mappings().all()
        return [
            str(row.get("purchase_model", "")).strip()
            for row in rows
            if str(row.get("purchase_model", "")).strip()
        ]

    @staticmethod
    def _map_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "bill_quantity": PurchaseRecordService._to_number(row.get("bill_quantity")),
            "final_purchase_price": PurchaseRecordService._to_number(row.get("final_purchase_price")),
            "selling_price": PurchaseRecordService._to_number(row.get("selling_price")),
            "settlement_unit_price": PurchaseRecordService._to_number(row.get("settlement_unit_price")),
            "settlement_amount": PurchaseRecordService._to_number(row.get("settlement_amount")),
            "gross_profit_margin": PurchaseRecordService._to_number(row.get("gross_profit_margin")),
            "tax_included": row.get("tax_included"),
            "order_no": row.get("order_no"),
            "invoice_type": row.get("invoice_type"),
            "tax_rate": PurchaseRecordService._to_number(row.get("tax_rate")),
            "product_link": row.get("product_link"),
            "supplier_name": row.get("supplier_name"),
            "shop_name": row.get("shop_name"),
            "unit": row.get("unit"),
            "date": row.get("date"),
        }

    async def _query_candidate_rows_for_chunk(
        self,
        session: AsyncSession,
        indexed_items: list[tuple[int, dict[str, Any]]],
        per_item_limit: int,
        enable_fuzzy_code_match: bool,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: dict[str, Any] = {}
        product_name_expr = self._sql_normalized_expr("product_name")
        purchase_model_expr = self._sql_normalized_expr("purchase_model")
        purchase_spec_expr = self._sql_normalized_expr("purchase_spec")
        brand_expr = self._sql_normalized_expr("brand")
        for item_idx, item in indexed_items:
            item_conditions: list[str] = []
            for term_idx, exact_term in enumerate(self._exact_terms_for_item(item)):
                param_name = f"exact_{item_idx}_{term_idx}"
                params[param_name] = exact_term
                item_conditions.append(
                    "("
                    f"{purchase_model_expr} = :{param_name} "
                    f"OR {product_name_expr} = :{param_name} "
                    f"OR {purchase_spec_expr} = :{param_name} "
                    f"OR {brand_expr} = :{param_name}"
                    ")"
                )
            for term_idx, term in enumerate(self._default_text_terms_for_item(item)):
                param_name = f"text_{item_idx}_{term_idx}"
                params[param_name] = f"%{term}%"
                item_conditions.append(
                    "("
                    f"{product_name_expr} LIKE :{param_name} "
                    f"OR {purchase_spec_expr} LIKE :{param_name} "
                    f"OR {brand_expr} LIKE :{param_name}"
                    ")"
                )
            if enable_fuzzy_code_match:
                for term_idx, term in enumerate(self._query_terms_for_item(item)):
                    param_name = f"kw_{item_idx}_{term_idx}"
                    params[param_name] = f"%{term}%"
                    item_conditions.append(
                        "("
                        f"{product_name_expr} LIKE :{param_name} "
                        f"OR {purchase_model_expr} LIKE :{param_name} "
                        f"OR {purchase_spec_expr} LIKE :{param_name} "
                        f"OR {brand_expr} LIKE :{param_name}"
                        ")"
                    )
            if item_conditions:
                conditions.append("(" + " OR ".join(item_conditions) + ")")
        if not conditions:
            return []

        scan_limit = max(
            per_item_limit,
            int(getattr(settings, "PURCHASE_CANDIDATE_SCAN_LIMIT", per_item_limit * 20) or per_item_limit * 20),
        )
        params["limit"] = max(per_item_limit, min(len(indexed_items) * scan_limit, 3000))
        sql = text(
            f"""
            SELECT
                id,
                product_name,
                brand,
                purchase_model,
                purchase_spec,
                supplier_name,
                shop_name,
                unit,
                bill_quantity,
                final_purchase_price,
                selling_price,
                settlement_unit_price,
                settlement_amount,
                gross_profit_margin,
                tax_included,
                order_no,
                invoice_type,
                tax_rate,
                product_link,
                date
            FROM purchase_records
            WHERE purchase_model IS NOT NULL
              AND TRIM(purchase_model) <> ''
              AND ({" OR ".join(conditions)})
            ORDER BY
                CASE WHEN final_purchase_price IS NOT NULL THEN 0 ELSE 1 END,
                CASE WHEN selling_price IS NOT NULL THEN 0 ELSE 1 END,
                CASE WHEN bill_quantity IS NOT NULL AND bill_quantity > 0 THEN 0 ELSE 1 END,
                date DESC,
                id DESC
            LIMIT :limit
            """
        )
        rows = (await session.execute(sql, params)).mappings().all()
        return [dict(row) for row in rows]

    def _assign_rows_to_items(
        self,
        indexed_items: list[tuple[int, dict[str, Any]]],
        rows: list[dict[str, Any]],
        limit: int,
        enable_fuzzy_code_match: bool,
    ) -> dict[int, list[dict[str, Any]]]:
        buckets: dict[int, list[dict[str, Any]]] = {idx: [] for idx, _ in indexed_items}
        for row in rows:
            for idx, item in indexed_items:
                score, reasons = self._score_row_for_item(
                    row=row,
                    item=item,
                    enable_fuzzy_code_match=enable_fuzzy_code_match,
                )
                if score <= 0:
                    continue
                candidate = self._map_candidate_row(row=row, item=item)
                candidate["match_score"] = score
                candidate["match_reason"] = reasons
                buckets[idx].append(candidate)

        result: dict[int, list[dict[str, Any]]] = {}
        for idx, candidates in buckets.items():
            candidates.sort(
                key=lambda row: (
                    -int(row.get("match_score") or 0),
                    -self._quote_value_score(row),
                )
            )
            result[idx] = self._dedupe_candidates(candidates, limit=limit)
        return result

    @staticmethod
    def _map_candidate_row(row: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        purchase_model = str(row.get("purchase_model", "")).strip()
        history_record = PurchaseRecordService._map_row(row)
        return {
            "item_type": "external",
            "sku_id": purchase_model,
            "sku_code": purchase_model,
            "product_name": str(row.get("product_name", "")).strip(),
            "brand": str(row.get("brand", "")).strip(),
            "purchase_model": purchase_model,
            "purchase_spec": str(row.get("purchase_spec", "")).strip(),
            "supplier_name": str(row.get("supplier_name", "")).strip(),
            "shop_name": str(row.get("shop_name", "")).strip(),
            "unit": str(row.get("unit", "")).strip(),
            "input_product_name": str(item.get("product_name", "")).strip(),
            "input_product_model": str(item.get("product_model", "")).strip(),
            "bill_quantity": PurchaseRecordService._to_number(row.get("bill_quantity")),
            "final_purchase_price": PurchaseRecordService._to_number(row.get("final_purchase_price")),
            "selling_price": PurchaseRecordService._to_number(row.get("selling_price")),
            "settlement_unit_price": PurchaseRecordService._to_number(row.get("settlement_unit_price")),
            "settlement_amount": PurchaseRecordService._to_number(row.get("settlement_amount")),
            "gross_profit_margin": PurchaseRecordService._to_number(row.get("gross_profit_margin")),
            "tax_included": row.get("tax_included"),
            "order_no": row.get("order_no"),
            "invoice_type": row.get("invoice_type"),
            "tax_rate": PurchaseRecordService._to_number(row.get("tax_rate")),
            "product_link": row.get("product_link"),
            "history_records": [history_record],
            "date": row.get("date"),
            "provider_error": "",
            "source": "database",
            "matched_source": "purchase_records",
            "matched_sources": ["database", "purchase_records"],
        }

    @staticmethod
    def _query_terms_for_item(item: dict[str, Any]) -> list[str]:
        values = [
            item.get("sku", ""),
            item.get("product_code", ""),
            item.get("product_model", ""),
            item.get("purchase_model", ""),
            item.get("product_name", ""),
        ]
        terms: list[str] = []
        for value in values:
            text_value = PurchaseRecordService._normalize_match_text(value)
            if len(text_value) < 2:
                continue
            terms.append(text_value[:80])
        return list(dict.fromkeys(terms))

    @staticmethod
    def _exact_terms_for_item(item: dict[str, Any]) -> list[str]:
        values = [
            item.get("sku", ""),
            item.get("product_code", ""),
            item.get("product_model", ""),
            item.get("purchase_model", ""),
            item.get("product_name", ""),
        ]
        terms = [PurchaseRecordService._normalize_match_text(value) for value in values]
        return [term for term in dict.fromkeys(terms) if len(term) >= 2]

    @staticmethod
    def _default_text_terms_for_item(item: dict[str, Any]) -> list[str]:
        values = [item.get("product_name", "")]
        terms: list[str] = []
        for value in values:
            text_value = PurchaseRecordService._normalize_match_text(value)
            if len(text_value) < 2:
                continue
            terms.append(text_value[:80])
        return list(dict.fromkeys(terms))

    @staticmethod
    def _fuzzy_code_terms_for_item(item: dict[str, Any]) -> list[str]:
        values = [
            item.get("sku", ""),
            item.get("product_code", ""),
            item.get("product_model", ""),
            item.get("purchase_model", ""),
            item.get("product_name", ""),
        ]
        terms: list[str] = []
        for value in values:
            text_value = PurchaseRecordService._normalize_match_text(value).rstrip("*")
            if len(text_value) < 2 or re.search(r"[\u4e00-\u9fff]", text_value):
                continue
            if not re.fullmatch(r"[a-z0-9]+", text_value):
                continue
            terms.append(text_value[:80])
        return list(dict.fromkeys(terms))

    @staticmethod
    def _score_row_for_item(
        row: dict[str, Any],
        item: dict[str, Any],
        enable_fuzzy_code_match: bool = False,
    ) -> tuple[int, list[str]]:
        purchase_model = PurchaseRecordService._normalize_match_text(row.get("purchase_model"))
        product_name = PurchaseRecordService._normalize_match_text(row.get("product_name"))
        purchase_spec = PurchaseRecordService._normalize_match_text(row.get("purchase_spec"))
        brand = PurchaseRecordService._normalize_match_text(row.get("brand"))
        supplier_name = PurchaseRecordService._normalize_match_text(row.get("supplier_name"))
        shop_name = PurchaseRecordService._normalize_match_text(row.get("shop_name"))
        haystack = f"{purchase_model} {product_name} {purchase_spec} {brand} {supplier_name} {shop_name}"
        score = 0
        reasons: list[str] = []

        for key, reason in (("sku", "sku_exact"), ("product_code", "product_code_exact")):
            value = PurchaseRecordService._normalize_match_text(item.get(key))
            if not value:
                continue
            if value == purchase_model:
                score += 100
                reasons.append(reason)
            elif enable_fuzzy_code_match and value in haystack:
                score += 70
                reasons.append(reason.replace("_exact", "_contains"))

        model = PurchaseRecordService._normalize_match_text(
            item.get("product_model") or item.get("purchase_model") or ""
        )
        if model:
            if model == purchase_model:
                score += 90
                reasons.append("model_exact")
            elif enable_fuzzy_code_match and model in purchase_model:
                score += 70
                reasons.append("model_contains")
            elif enable_fuzzy_code_match and (model in product_name or model in purchase_spec):
                score += 60
                reasons.append("model_text_contains")

        input_name = PurchaseRecordService._normalize_match_text(item.get("product_name"))
        name_score = 0
        if input_name:
            if input_name == purchase_model:
                name_score += 90
                reasons.append("name_model_exact")
            elif input_name == product_name:
                name_score += 60
                reasons.append("name_exact")
            elif (enable_fuzzy_code_match or not PurchaseRecordService._looks_like_code(input_name)) and input_name in product_name:
                name_score += 45
                reasons.append("name_contains")
            elif (enable_fuzzy_code_match or not PurchaseRecordService._looks_like_code(input_name)) and input_name in purchase_spec:
                name_score += 42
                reasons.append("spec_contains")
            elif (enable_fuzzy_code_match or not PurchaseRecordService._looks_like_code(input_name)) and input_name in brand:
                name_score += 35
                reasons.append("brand_contains")
            elif enable_fuzzy_code_match and (input_name in supplier_name or input_name in shop_name):
                name_score += 24
                reasons.append("source_contains")
            elif enable_fuzzy_code_match or not PurchaseRecordService._looks_like_code(input_name):
                token_hits = 0
                for token in PurchaseRecordService._tokens(input_name):
                    if token in haystack:
                        token_hits += 1
                if token_hits:
                    name_score += min(30, token_hits * 8)
                    reasons.append("name_token_hits")
        score += name_score

        if not reasons:
            return 0, []
        strong_reasons = {
            "sku_exact",
            "product_code_exact",
            "model_exact",
            "model_contains",
            "model_text_contains",
            "name_model_exact",
            "name_exact",
            "name_contains",
            "spec_contains",
            "brand_contains",
        }
        if not any(reason in strong_reasons for reason in reasons) and score < 24:
            return 0, []
        return score, reasons

    @staticmethod
    def _quote_value_score(row: dict[str, Any]) -> int:
        score = 0
        if row.get("final_purchase_price") is not None:
            score += 30
        if row.get("selling_price") is not None:
            score += 18
        if row.get("settlement_unit_price") is not None:
            score += 10
        if row.get("settlement_amount") is not None:
            score += 8
        if row.get("bill_quantity") not in (None, "", 0):
            score += 8
        if str(row.get("supplier_name") or "").strip():
            score += 4
        if str(row.get("shop_name") or "").strip():
            score += 4
        if str(row.get("product_link") or "").strip():
            score += 3
        return score

    @staticmethod
    def _to_number(value: Any) -> float | int | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if number.is_integer():
            return int(number)
        return number

    @staticmethod
    def _dedupe_candidates(candidates: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_items = max(1, int(limit or settings.QUERY_CANDIDATE_LIMIT))
        for row in candidates:
            key = str(row.get("sku_id", "") or row.get("product_name", "")).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(row)
            if len(deduped) >= max_items:
                break
        return deduped

    @staticmethod
    def _tokens(value: str) -> list[str]:
        raw_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-./]*|[\u4e00-\u9fff]{2,}", value or "")
        return [token.lower() for token in raw_tokens if len(token.strip()) >= 2]

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
    def _looks_like_code(value: Any) -> bool:
        text = PurchaseRecordService._normalize_match_text(value)
        if len(text) < 4:
            return False
        return bool(re.search(r"[a-zA-Z]", text) and re.search(r"\d", text))

    @staticmethod
    def _sql_normalized_expr(field: str) -> str:
        expr = f"LOWER(COALESCE({field}, ''))"
        for old in (" ", "\t", "\r", "\n", "_", "-", ".", "/", "－", "–", "—", "‒"):
            expr = f"REPLACE({expr}, '{old}', '')"
        return expr

    @staticmethod
    def _safe_limit(limit: int | None = None) -> int:
        requested = int(limit or settings.QUERY_CANDIDATE_LIMIT)
        max_limit = max(
            int(settings.QUERY_CANDIDATE_LIMIT or 5),
            min(int(getattr(settings, "PURCHASE_CANDIDATE_SCAN_LIMIT", 100) or 100), 100),
        )
        return max(1, min(requested, max_limit))


purchase_record_service = PurchaseRecordService()
