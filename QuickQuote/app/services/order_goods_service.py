import re
import unicodedata
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


class OrderGoodsService:
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
            {
                "idx": idx,
                "item": item,
                "candidates": [],
                "provider_error": "",
            }
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

    async def query_candidates_by_item(
        self,
        session: AsyncSession,
        item: dict[str, Any],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        product_name = str(item.get("product_name", "")).strip()
        if not product_name:
            return []
        sql = text(
            """
            SELECT
                sku_id,
                name,
                outer_oi_id,
                produced_date
            FROM bf_jushuitan_order_goods
            WHERE name LIKE :product_name_keyword
              AND sku_id IS NOT NULL
              AND TRIM(sku_id) <> ''
            ORDER BY produced_date DESC, id DESC
            LIMIT :limit
            """
        )
        rows = (
            await session.execute(
                sql,
                {
                    "product_name_keyword": f"%{product_name}%",
                    "limit": self._safe_limit(limit),
                },
            )
        ).mappings().all()
        candidates = [self._map_row(dict(row), item=item) for row in rows]
        reranked = self._rerank_by_model(candidates=candidates, product_model=str(item.get("product_model", "")).strip())
        return self._dedupe_by_sku_id(reranked)

    async def query_latest_order_by_sku(self, session: AsyncSession, sku_id: str) -> dict[str, Any] | None:
        normalized_sku = str(sku_id or "").strip()
        if not normalized_sku:
            return None
        sql = text(
            """
            SELECT
                sku_id,
                name,
                raw_so_id,
                produced_date
            FROM bf_jushuitan_order_goods
            WHERE sku_id = :sku_id
            ORDER BY produced_date DESC, id DESC
            LIMIT 1
            """
        )
        row = (await session.execute(sql, {"sku_id": normalized_sku})).mappings().first()
        if not row:
            return None
        record = dict(row)
        return {
            "sku_id": str(record.get("sku_id", "")).strip(),
            "product_name": str(record.get("name", "")).strip(),
            "raw_so_id": str(record.get("raw_so_id", "")).strip(),
            "produced_date": record.get("produced_date"),
        }

    async def query_latest_orders_by_skus(
        self, session: AsyncSession, sku_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        normalized_skus = list(dict.fromkeys(str(sku or "").strip() for sku in sku_ids if str(sku or "").strip()))
        if not normalized_skus:
            return {}
        sql = (
            text(
                """
                SELECT
                    og.sku_id,
                    og.name,
                    og.raw_so_id,
                    og.produced_date
                FROM bf_jushuitan_order_goods og
                JOIN (
                    SELECT sku_id, MAX(id) AS max_id
                    FROM bf_jushuitan_order_goods
                    WHERE sku_id IN :sku_ids
                    GROUP BY sku_id
                ) latest ON og.sku_id = latest.sku_id AND og.id = latest.max_id
                """
            )
            .bindparams(bindparam("sku_ids", expanding=True))
        )
        rows = (await session.execute(sql, {"sku_ids": normalized_skus})).mappings().all()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            record = dict(row)
            sku_id = str(record.get("sku_id", "")).strip()
            if not sku_id:
                continue
            result[sku_id] = {
                "sku_id": sku_id,
                "product_name": str(record.get("name", "")).strip(),
                "raw_so_id": str(record.get("raw_so_id", "")).strip(),
                "produced_date": record.get("produced_date"),
            }
        return result

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
        sku_expr = self._sql_normalized_expr("sku_id")
        for idx, term in enumerate(terms):
            param_name = f"kw_{idx}"
            params[param_name] = f"%{term}%"
            conditions.append(f"{sku_expr} LIKE :{param_name}")
        params["limit"] = max(1, min(int(limit or 50), 100))

        sql = text(
            f"""
            SELECT
                sku_id,
                MAX(produced_date) AS latest_produced_date,
                MAX(id) AS latest_id
            FROM bf_jushuitan_order_goods
            WHERE sku_id IS NOT NULL
              AND TRIM(sku_id) <> ''
              AND ({" OR ".join(conditions)})
            GROUP BY sku_id
            ORDER BY latest_produced_date DESC, latest_id DESC
            LIMIT :limit
            """
        )
        rows = (await session.execute(sql, params)).mappings().all()
        return [str(row.get("sku_id", "")).strip() for row in rows if str(row.get("sku_id", "")).strip()]

    @staticmethod
    def _map_row(row: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        return {
            "item_type": "internal",
            "sku_id": str(row.get("sku_id", "")).strip(),
            "sku_code": str(row.get("sku_id", "")).strip(),
            "product_name": str(row.get("name", "")).strip(),
            "outer_oi_id": str(row.get("outer_oi_id", "")).strip(),
            "produced_date": row.get("produced_date"),
            "source_table": "bf_jushuitan_order_goods",
            "input_product_name": str(item.get("product_name", "")).strip(),
            "input_product_model": str(item.get("product_model", "")).strip(),
            "stock_qty": None,
            "cost_price": None,
            "provider_error": "",
            "source": "database",
            "matched_source": "bf_jushuitan_order_goods",
            "matched_sources": ["database"],
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
        name_expr = self._sql_normalized_expr("name")
        sku_expr = self._sql_normalized_expr("sku_id")
        for item_idx, item in indexed_items:
            item_conditions: list[str] = []
            for term_idx, exact_term in enumerate(self._exact_terms_for_item(item)):
                param_name = f"exact_{item_idx}_{term_idx}"
                params[param_name] = exact_term
                item_conditions.append(f"({sku_expr} = :{param_name} OR {name_expr} = :{param_name})")
            for term_idx, term in enumerate(self._default_text_terms_for_item(item)):
                param_name = f"text_{item_idx}_{term_idx}"
                params[param_name] = f"%{term}%"
                item_conditions.append(f"{name_expr} LIKE :{param_name}")
            if enable_fuzzy_code_match:
                for term_idx, term in enumerate(self._query_terms_for_item(item)):
                    param_name = f"kw_{item_idx}_{term_idx}"
                    params[param_name] = f"%{term}%"
                    item_conditions.append(f"({name_expr} LIKE :{param_name} OR {sku_expr} LIKE :{param_name})")
            if item_conditions:
                conditions.append("(" + " OR ".join(item_conditions) + ")")
        if not conditions:
            return []

        multiplier = max(1, int(getattr(settings, "DB_CANDIDATE_LIMIT_MULTIPLIER", 4) or 4))
        params["limit"] = max(per_item_limit, min(len(indexed_items) * per_item_limit * multiplier, 1000))
        sql = text(
            f"""
            SELECT
                sku_id,
                name,
                outer_oi_id,
                produced_date
            FROM bf_jushuitan_order_goods
            WHERE sku_id IS NOT NULL
              AND TRIM(sku_id) <> ''
              AND ({" OR ".join(conditions)})
            ORDER BY produced_date DESC, id DESC
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
                candidate = self._map_row(row=row, item=item)
                candidate["match_score"] = score
                candidate["match_reason"] = reasons
                buckets[idx].append(candidate)

        result: dict[int, list[dict[str, Any]]] = {}
        for idx, candidates in buckets.items():
            candidates.sort(key=lambda row: -int(row.get("match_score") or 0))
            result[idx] = self._dedupe_by_sku_id(candidates, limit=limit)
        return result

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
            text_value = OrderGoodsService._normalize_match_text(value)
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
        terms = [OrderGoodsService._normalize_match_text(value) for value in values]
        return [term for term in dict.fromkeys(terms) if len(term) >= 2]

    @staticmethod
    def _default_text_terms_for_item(item: dict[str, Any]) -> list[str]:
        values = [item.get("product_name", "")]
        terms: list[str] = []
        for value in values:
            text_value = OrderGoodsService._normalize_match_text(value)
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
            text_value = OrderGoodsService._normalize_match_text(value).rstrip("*")
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
        return OrderGoodsService._score_row_for_item_with_mode(
            row=row,
            item=item,
            enable_fuzzy_code_match=enable_fuzzy_code_match,
        )

    @staticmethod
    def _score_row_for_item_with_mode(
        row: dict[str, Any],
        item: dict[str, Any],
        enable_fuzzy_code_match: bool,
    ) -> tuple[int, list[str]]:
        sku_id = OrderGoodsService._normalize_match_text(row.get("sku_id"))
        name = OrderGoodsService._normalize_match_text(row.get("name"))
        haystack = f"{sku_id} {name}"
        score = 0
        reasons: list[str] = []

        for key, reason in (("sku", "sku_exact"), ("product_code", "product_code_exact")):
            value = OrderGoodsService._normalize_match_text(item.get(key))
            if not value:
                continue
            if value == sku_id:
                score += 100
                reasons.append(reason)
            elif enable_fuzzy_code_match and value in haystack:
                score += 70
                reasons.append(reason.replace("_exact", "_contains"))

        model = OrderGoodsService._normalize_match_text(
            item.get("product_model") or item.get("purchase_model") or ""
        )
        if model:
            if model == sku_id:
                score += 90
                reasons.append("model_sku_exact")
            elif enable_fuzzy_code_match and model in sku_id:
                score += 70
                reasons.append("model_sku_contains")
            elif enable_fuzzy_code_match and model in name:
                score += 60
                reasons.append("model_name_contains")

        product_name = OrderGoodsService._normalize_match_text(item.get("product_name"))
        name_score = 0
        if product_name:
            if product_name == sku_id:
                name_score += 90
                reasons.append("name_sku_exact")
            elif product_name == name:
                name_score += 60
                reasons.append("name_exact")
            elif (enable_fuzzy_code_match or not OrderGoodsService._looks_like_code(product_name)) and product_name in name:
                name_score += 45
                reasons.append("name_contains")
            elif enable_fuzzy_code_match or not OrderGoodsService._looks_like_code(product_name):
                token_hits = 0
                for token in OrderGoodsService._tokens(product_name):
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
            "model_sku_exact",
            "model_sku_contains",
            "model_name_contains",
            "name_sku_exact",
            "name_exact",
            "name_contains",
        }
        if not any(reason in strong_reasons for reason in reasons) and score < 24:
            return 0, []
        return score, reasons

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
        text = OrderGoodsService._normalize_match_text(value)
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

    @staticmethod
    def _rerank_by_model(candidates: list[dict[str, Any]], product_model: str) -> list[dict[str, Any]]:
        model = product_model.strip().lower()
        if not model:
            return candidates
        with_model = []
        without_model = []
        for row in candidates:
            haystack = f"{row.get('product_name', '')} {row.get('sku_id', '')}".lower()
            if model in haystack:
                with_model.append(row)
            else:
                without_model.append(row)
        return [*with_model, *without_model][: settings.QUERY_CANDIDATE_LIMIT]

    @staticmethod
    def _dedupe_by_sku_id(candidates: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_items = max(1, int(limit or settings.QUERY_CANDIDATE_LIMIT))
        for row in candidates:
            sku_id = str(row.get("sku_id", "")).strip()
            if not sku_id:
                continue
            if sku_id in seen:
                continue
            seen.add(sku_id)
            deduped.append(row)
            if len(deduped) >= max_items:
                break
        return deduped


order_goods_service = OrderGoodsService()
