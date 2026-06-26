import asyncio
import copy
import hashlib
import json
import logging
import os
import random
import re
import string
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_WAREHOUSES = [
    {"wms_co_id": 10666412, "name": "东莞市不凡电子有限公司"},
    {"wms_co_id": 10681565, "name": "京东北京仓（京东共享仓）"},
    {"wms_co_id": 10681566, "name": "京东上海仓（京东自营仓）"},
    {"wms_co_id": 10681567, "name": "京东武汉仓（京东共享仓）"},
    {"wms_co_id": 10681568, "name": "京东广州仓（京东自营仓）"},
    {"wms_co_id": 10681572, "name": "京东沈阳仓（京东共享仓）"},
    {"wms_co_id": 10681574, "name": "京东西安仓（京东共享仓）"},
    {"wms_co_id": 10681575, "name": "京东成都仓（京东共享仓）"},
    {"wms_co_id": 10810655, "name": "不凡代发仓"},
    {"wms_co_id": 11011935, "name": "不凡展厅仓"},
    {"wms_co_id": 11874489, "name": "不凡外购仓"},
    {"wms_co_id": 12359778, "name": "不凡样品仓"},
    {"wms_co_id": 12761313, "name": "立创仓"},
    {"wms_co_id": 13160656, "name": "不凡沃尔玛仓"},
    {"wms_co_id": 13676682, "name": "不凡抖音仓"},
    {"wms_co_id": 13832701, "name": "京东德州仓（京东共享仓）"},
]


class JushuitanService:
    def __init__(self) -> None:
        self._access_token = (settings.JUSHUITAN_ACCESS_TOKEN or "").strip()
        self._refresh_token = (settings.JUSHUITAN_REFRESH_TOKEN or "").strip()
        self._token_expire_at = 0.0
        self._token_lock = asyncio.Lock()
        self._last_auth_error = ""
        self._token_cache_file = str(settings.JUSHUITAN_TOKEN_CACHE_FILE or ".jushuitan_token_cache.json").strip()
        self._enable_token_cache = bool(settings.JUSHUITAN_ENABLE_TOKEN_CACHE)
        self._query_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._query_cache_lock = asyncio.Lock()
        self._load_token_cache()

    async def query_item(self, item: dict[str, Any]) -> dict[str, Any]:
        start_at = time.perf_counter()
        query_id = self._query_log_id(item)
        logger.info(
            "[jushuitan] QUERY START | %s",
            self._json_for_log(
                {
                    "query_id": query_id,
                    "item": item,
                }
            ),
        )
        cached = await self._get_cached_query_result(item)
        if cached is not None:
            cached["cache_hit"] = True
            cached["cost_ms"] = int((time.perf_counter() - start_at) * 1000)
            logger.info(
                "[jushuitan] QUERY CACHE HIT | %s",
                self._json_for_log(
                    {
                        "query_id": query_id,
                        "cost_ms": cached["cost_ms"],
                        "records_count": len(cached.get("records", []) or []),
                    }
                ),
            )
            return cached

        token = await self._ensure_access_token()
        if not token:
            logger.warning(
                "[jushuitan] QUERY FAILED | %s",
                self._json_for_log(
                    {
                        "query_id": query_id,
                        "reason": "no_access_token",
                        "auth_error": self._last_auth_error,
                    }
                ),
            )
            detail = f"，详情：{self._last_auth_error}" if self._last_auth_error else ""
            return self._failed_result(
                f"未获取到聚水潭 access_token，请检查授权配置{detail}",
                request_payload={"item": item},
                start_at=start_at,
            )

        sku_payloads = self._build_sku_payloads(item)
        if not sku_payloads:
            logger.warning(
                "[jushuitan] QUERY FAILED | %s",
                self._json_for_log(
                    {
                        "query_id": query_id,
                        "reason": "empty_sku_payload",
                        "item": item,
                    }
                ),
            )
            return self._failed_result(
                "缺少有效查询条件（sku_ids/name/exactly_name 或 modified 时间范围）",
                request_payload={"sku_payloads": sku_payloads},
                start_at=start_at,
            )

        sku_rows: list[dict[str, Any]] = []
        sku_error = ""
        sku_body: dict[str, Any] = {}
        sku_page_count = 0
        sku_payload_used: dict[str, Any] = {"queries": sku_payloads}
        for payload_idx, sku_payload in enumerate(sku_payloads, start=1):
            logger.info(
                "[jushuitan] SKU QUERY START | %s",
                self._json_for_log(
                    {
                        "query_id": query_id,
                        "payload_idx": payload_idx,
                        "payload_count": len(sku_payloads),
                        "sku_payload": sku_payload,
                    }
                ),
            )
            rows, error, body, page_count = await self._query_all_sku_rows(
                sku_payload=sku_payload, access_token=token
            )
            logger.info(
                "[jushuitan] SKU QUERY DONE | %s",
                self._json_for_log(
                    {
                        "query_id": query_id,
                        "payload_idx": payload_idx,
                        "rows_count": len(rows),
                        "page_count": page_count,
                        "api_code": body.get("code") if isinstance(body, dict) else None,
                        "api_msg": body.get("msg") if isinstance(body, dict) else "",
                        "error": error,
                    }
                ),
            )
            if rows:
                sku_rows = self._merge_sku_rows(sku_rows, rows)
            if isinstance(body, dict) and body:
                sku_body = body
            sku_page_count += page_count
            sku_error = self._join_errors([sku_error, error])

        inventory_rows: list[dict[str, Any]] = []
        inventory_payloads: list[dict[str, Any]] = []
        inventory_response_previews: list[dict[str, Any]] = []
        inventory_error = ""
        logger.info(
            "[jushuitan] INVENTORY QUERY START | %s",
            self._json_for_log(
                {
                    "query_id": query_id,
                    "sku_rows_count": len(sku_rows),
                    "warehouse_limit": int(getattr(settings, "JUSHUITAN_INVENTORY_MAX_WAREHOUSES", 4) or 4),
                }
            ),
        )
        inv_result = await self._query_inventory_across_warehouses(item=item, sku_rows=sku_rows, access_token=token)
        inventory_rows = inv_result.get("rows", [])
        inventory_payloads = inv_result.get("request_payloads", [])
        inventory_response_previews = inv_result.get("response_previews", [])
        inventory_error = inv_result.get("error", "")
        logger.info(
            "[jushuitan] INVENTORY QUERY DONE | %s",
            self._json_for_log(
                {
                    "query_id": query_id,
                    "rows_count": len(inventory_rows),
                    "payload_count": len(inventory_payloads),
                    "response_previews": inventory_response_previews[:5],
                    "error": inventory_error,
                }
            ),
        )

        # 已拿到 SKU 但价格缺失时，用 sku_ids 再补查一次商品资料
        if self._need_price_backfill(sku_rows):
            sku_ref_payload = self._build_sku_payload_by_identifiers(item=item, sku_rows=sku_rows, inventory_rows=inventory_rows)
            if sku_ref_payload:
                extra_rows, extra_error, extra_body, extra_pages = await self._query_all_sku_rows(
                    sku_payload=sku_ref_payload, access_token=token
                )
                if extra_rows:
                    sku_rows = self._merge_sku_rows(sku_rows, extra_rows)
                sku_error = self._join_errors([sku_error, extra_error])
                if isinstance(extra_body, dict):
                    sku_body = extra_body
                sku_page_count += extra_pages

        # 首轮库存为空时，若已补到 sku_rows，则再按 sku_id/sku_code 重查一次库存
        if (not inventory_rows) and sku_rows:
            inv_retry = await self._query_inventory_across_warehouses(item=item, sku_rows=sku_rows, access_token=token)
            inventory_rows = inv_retry.get("rows", []) or inventory_rows
            inventory_payloads.extend(inv_retry.get("request_payloads", []))
            inventory_response_previews.extend(inv_retry.get("response_previews", []))
            inventory_error = self._join_errors([inventory_error, inv_retry.get("error", "")])

        merged_records = self._merge_price_and_inventory(sku_rows, inventory_rows, item)
        status = "ok" if merged_records else "failed"
        error_message = self._join_errors([sku_error, inventory_error])
        if not merged_records and not error_message:
            error_message = "聚水潭未返回有效数据"

        response = {
            "status": status,
            "error": error_message,
            "records": merged_records,
            "request_payload": {
                "sku_payload": sku_payload_used,
                "inventory_payload": inventory_payloads,
            },
            "response_preview": {
                "sku_count": len(sku_rows),
                "sku_page_count": sku_page_count,
                "inventory_count": len(inventory_rows),
                "sku_api_code": sku_body.get("code") if isinstance(sku_body, dict) else None,
                "sku_api_msg": sku_body.get("msg") if isinstance(sku_body, dict) else None,
                "inventory_warehouse_count": len({int(row.get("wms_co_id", 0)) for row in inventory_rows if row.get("wms_co_id") is not None}),
                "inventory_response_previews": inventory_response_previews[:10],
            },
            "cost_ms": int((time.perf_counter() - start_at) * 1000),
        }
        if status == "ok":
            await self._set_cached_query_result(item, response)
        logger.info(
            "[jushuitan] QUERY DONE | %s",
            self._json_for_log(
                {
                    "query_id": query_id,
                    "status": status,
                    "records_count": len(merged_records),
                    "sku_rows_count": len(sku_rows),
                    "inventory_rows_count": len(inventory_rows),
                    "error": error_message,
                    "cost_ms": response["cost_ms"],
                    "response_preview": response.get("response_preview", {}),
                }
            ),
        )
        return response

    async def query_dynamic_cost_records_by_skus(
        self,
        sku_ids: list[str],
        lookback_days: int | None = None,
        per_sku_limit: int = 10,
    ) -> dict[str, list[dict[str, Any]]]:
        normalized_skus = list(dict.fromkeys(str(sku or "").strip() for sku in sku_ids if str(sku or "").strip()))
        if not normalized_skus:
            return {}
        token = await self._ensure_access_token()
        if not token:
            return {}

        sku_set = set(normalized_skus)
        records_by_sku: dict[str, list[dict[str, Any]]] = {sku: [] for sku in normalized_skus}
        days = max(1, int(lookback_days or getattr(settings, "JUSHUITAN_DYNAMIC_COST_LOOKBACK_DAYS", 180) or 180))
        max_pages_total = max(1, int(getattr(settings, "JUSHUITAN_DYNAMIC_COST_MAX_PAGES", 20) or 20))
        page_size = max(1, min(int(getattr(settings, "JUSHUITAN_PAGE_SIZE", 100) or 100), 100))
        end_at = datetime.now()
        begin_at = end_at - timedelta(days=days)
        pages_used = 0

        window_end = end_at
        while window_end > begin_at and pages_used < max_pages_total:
            window_begin = max(begin_at, window_end - timedelta(days=7))
            for sku_chunk in self._chunks(normalized_skus, 20):
                for page_index in range(1, max_pages_total - pages_used + 1):
                    payload = {
                        "page_index": page_index,
                        "page_size": page_size,
                        "modified_begin": window_begin.strftime("%Y-%m-%d %H:%M:%S"),
                        "modified_end": window_end.strftime("%Y-%m-%d %H:%M:%S"),
                        "sku_ids": sku_chunk,
                    }
                    body = await self._request_business_api(
                        path=settings.JUSHUITAN_PURCHASE_IN_QUERY_PATH,
                        biz_payload=payload,
                        access_token=token,
                    )
                    pages_used += 1
                    rows = self._extract_purchase_in_rows(body)
                    self._collect_dynamic_cost_rows(rows=rows, sku_set=sku_set, records_by_sku=records_by_sku)
                    if len(rows) < page_size or not self._body_has_next(body):
                        break
                    if pages_used >= max_pages_total:
                        break
                if pages_used >= max_pages_total:
                    break
            window_end = window_begin

        for sku_id, rows in records_by_sku.items():
            rows.sort(key=lambda row: str(row.get("io_date") or ""), reverse=True)
            records_by_sku[sku_id] = rows[: max(1, int(per_sku_limit or 10))]
        return {sku_id: rows for sku_id, rows in records_by_sku.items() if rows}

    def _collect_dynamic_cost_rows(
        self,
        rows: list[dict[str, Any]],
        sku_set: set[str],
        records_by_sku: dict[str, list[dict[str, Any]]],
    ) -> None:
        for row in rows:
            supplier_name = self._normalize_text(row.get("supplier_name"))
            io_date = self._normalize_text(row.get("io_date")) or self._normalize_text(row.get("modified"))
            for item in row.get("items", []) or []:
                if not isinstance(item, dict):
                    continue
                sku_id = self._normalize_text(item.get("sku_id") or item.get("i_id"))
                if sku_id not in sku_set:
                    continue
                cost_price = self._pick_number(item, ["cost_price", "price", "unit_price"])
                if cost_price is None:
                    continue
                records_by_sku.setdefault(sku_id, []).append(
                    {
                        "sku_id": sku_id,
                        "product_name": self._normalize_text(item.get("name")),
                        "properties_value": self._normalize_text(item.get("properties_value")),
                        "io_date": io_date,
                        "supplier_name": supplier_name,
                        "qty": self._pick_number(item, ["qty"]),
                        "cost_price": cost_price,
                        "cost_amount": self._pick_number(item, ["cost_amount"]),
                        "io_id": row.get("io_id") or item.get("io_id"),
                        "po_id": row.get("po_id"),
                        "warehouse": self._normalize_text(row.get("warehouse")),
                        "status": self._normalize_text(row.get("status") or row.get("f_status")),
                    }
                )

    async def _get_cached_query_result(self, item: dict[str, Any]) -> dict[str, Any] | None:
        ttl = int(getattr(settings, "JUSHUITAN_QUERY_CACHE_TTL_SECONDS", 0) or 0)
        if ttl <= 0:
            return None
        cache_key = self._query_cache_key(item)
        now = time.time()
        async with self._query_cache_lock:
            cached = self._query_cache.get(cache_key)
            if not cached:
                return None
            expires_at, payload = cached
            if expires_at <= now:
                self._query_cache.pop(cache_key, None)
                return None
            return copy.deepcopy(payload)

    async def _set_cached_query_result(self, item: dict[str, Any], payload: dict[str, Any]) -> None:
        ttl = int(getattr(settings, "JUSHUITAN_QUERY_CACHE_TTL_SECONDS", 0) or 0)
        if ttl <= 0:
            return
        cache_key = self._query_cache_key(item)
        async with self._query_cache_lock:
            self._query_cache[cache_key] = (time.time() + ttl, copy.deepcopy(payload))
            if len(self._query_cache) > 2000:
                now = time.time()
                expired = [key for key, (expires_at, _) in self._query_cache.items() if expires_at <= now]
                for key in expired:
                    self._query_cache.pop(key, None)

    @staticmethod
    def _query_cache_key(item: dict[str, Any]) -> str:
        keys = [
            "sku",
            "product_code",
            "product_name",
            "product_model",
            "purchase_model",
            "purchase_spec",
            "modified_begin",
            "modified_end",
        ]
        payload = {key: str((item or {}).get(key, "")).strip().lower() for key in keys}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def summarize_records(records: list[dict[str, Any]]) -> str:
        if not records:
            return "聚水潭无匹配数据。"
        cost_count = sum(1 for row in records if row.get("cost_price") is not None)
        purchase_count = sum(1 for row in records if row.get("purchase_price") is not None)
        sale_count = sum(1 for row in records if row.get("sale_price") is not None)
        in_stock_count = sum(
            1 for row in records if isinstance(row.get("stock_qty"), (int, float)) and float(row["stock_qty"]) > 0
        )
        return (
            f"聚水潭匹配{len(records)}条，"
            f"成本价{cost_count}条，采购价{purchase_count}条，销售价{sale_count}条，"
            f"有库存{in_stock_count}条。"
        )

    @staticmethod
    def _build_sku_payload(item: dict[str, Any]) -> dict[str, Any]:
        payloads = JushuitanService._build_sku_payloads(item)
        return payloads[0] if payloads else {}

    @staticmethod
    def _build_sku_payloads(item: dict[str, Any]) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        product_name = (item.get("product_name") or "").strip()
        code_candidates = JushuitanService._item_code_candidates(item)
        enable_fuzzy_code_match = bool(item.get("enable_fuzzy_code_match", False))
        search_terms = JushuitanService._item_search_terms(item, enable_fuzzy_code_match=enable_fuzzy_code_match)
        flds = ",".join(
            [
                "sku_id",
                "sku_code",
                "name",
                "brand",
                "cost_price",
                "purchase_price",
                "sale_price",
                "market_price",
                "other_price_1",
                "other_price_2",
                "other_price_3",
                "other_price_4",
                "other_price_5",
                "other_price_6",
                "other_price_7",
                "other_price_8",
                "other_price_9",
                "other_price_10",
                "supplier_name",
                "modified",
            ]
        )
        max_items = max(1, min(int(settings.JUSHUITAN_MAX_ITEMS), 100))
        page_size = max(1, min(int(settings.JUSHUITAN_PAGE_SIZE), max_items))

        def _base() -> dict[str, Any]:
            return {"page_index": 1, "page_size": page_size, "flds": flds}

        if code_candidates:
            for chunk in JushuitanService._chunks(code_candidates, 20):
                payloads.append(
                    {
                        **_base(),
                        "sku_ids": ",".join(chunk),
                    }
                )
            for code in code_candidates:
                payloads.append({**_base(), "sku_ids": code})
                payloads.append({**_base(), "name": code})

        for term in search_terms:
            payloads.append({**_base(), "name": term})

        normalized_payloads: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            try:
                normalized = JushuitanService._normalize_sku_query_payload(payload)
            except Exception:
                continue
            if not normalized:
                continue
            key = json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            normalized_payloads.append(normalized)
        return normalized_payloads[:12] if enable_fuzzy_code_match else normalized_payloads[:6]

    @staticmethod
    def _chunks(values: list[str], size: int) -> list[list[str]]:
        chunk_size = max(1, int(size or 1))
        return [values[idx : idx + chunk_size] for idx in range(0, len(values), chunk_size)]

    @staticmethod
    def _build_spec_fallback_sku_payload(item: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        spec_text = str(item.get("purchase_model") or "").strip()
        payload = dict(base or {})
        payload["name"] = spec_text
        return payload

    @staticmethod
    def _should_retry_sku_by_spec(item: dict[str, Any], sku_payload: dict[str, Any], sku_rows: list[dict[str, Any]]) -> bool:
        if sku_rows:
            return False
        # 仅用于首轮模糊检索：已有 sku_ids 时说明是精确查，不做型号兜底
        if sku_payload.get("sku_ids"):
            return False
        product_name = str(item.get("product_name") or "").strip()
        spec_text = str(item.get("purchase_model") or "").strip()
        if not product_name or not spec_text:
            return False
        return product_name != spec_text

    @staticmethod
    def _looks_like_sku_code(value: str) -> bool:
        text = (value or "").strip()
        if not text:
            return False
        # 允许常见编码字符；出现中文或过长文本时不认为是编码
        if re.search(r"[\u4e00-\u9fff]", text):
            return False
        if len(text) > 40:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-./]*", text))

    def _build_inventory_payload(
        self, item: dict[str, Any], sku_rows: list[dict[str, Any]], wms_co_id: int
    ) -> dict[str, Any]:
        sku_ids = self._item_code_candidates(item)
        for row in sku_rows:
            sku_ids.extend(
                [
                    self._normalize_text(row.get("sku_id")),
                    self._normalize_text(row.get("sku_code")),
                    self._normalize_text(row.get("item_sku_id")),
                ]
            )
        merged = [s for s in sku_ids if s]
        deduped: list[str] = []
        for code in merged:
            if code not in deduped:
                deduped.append(code)
        if not deduped:
            return {}
        max_items = max(1, min(int(settings.JUSHUITAN_MAX_ITEMS), 100))
        payload = {
            "wms_co_id": int(wms_co_id),
            "sku_ids": ",".join(deduped[:50]),
            "page_index": 1,
            "page_size": max(1, min(int(settings.JUSHUITAN_PAGE_SIZE), max_items)),
            "modified_begin": "",
            "modified_end": "",
            "has_lock_qty": True,
        }
        if isinstance(item, dict):
            if item.get("modified_begin"):
                payload["modified_begin"] = str(item.get("modified_begin", "")).strip()
            if item.get("modified_end"):
                payload["modified_end"] = str(item.get("modified_end", "")).strip()
        return payload

    async def _query_inventory_across_warehouses(
        self, item: dict[str, Any], sku_rows: list[dict[str, Any]], access_token: str
    ) -> dict[str, Any]:
        warehouses = self._warehouse_list()
        if not warehouses:
            return {"rows": [], "request_payloads": [], "response_previews": [], "error": "未配置可用仓库"}

        semaphore = asyncio.Semaphore(max(1, int(settings.JUSHUITAN_INVENTORY_MAX_CONCURRENCY)))
        rows: list[dict[str, Any]] = []
        request_payloads: list[dict[str, Any]] = []
        response_previews: list[dict[str, Any]] = []
        errors: list[str] = []

        async def _query_one(warehouse: dict[str, Any]) -> None:
            wms_co_id = int(warehouse.get("wms_co_id", 0))
            warehouse_name = str(warehouse.get("name", "")).strip()
            payload = self._build_inventory_payload(item=item, sku_rows=sku_rows, wms_co_id=wms_co_id)
            if not payload:
                return
            request_payloads.append(payload)
            async with semaphore:
                inventory_rows, body, page_count = await self._query_inventory_rows_for_warehouse(
                    base_payload=payload,
                    access_token=access_token,
                )
            err = self._extract_api_error(body)
            if err:
                errors.append(f"{warehouse_name or wms_co_id}:{err}")
            for row in inventory_rows:
                if isinstance(row, dict):
                    rows.append(
                        {
                            **row,
                            "wms_co_id": wms_co_id,
                            "warehouse_name": warehouse_name,
                        }
                    )
            response_previews.append(
                {
                    "wms_co_id": wms_co_id,
                    "warehouse_name": warehouse_name,
                    "count": len(inventory_rows),
                    "page_count": page_count,
                    "code": body.get("code") if isinstance(body, dict) else None,
                    "msg": body.get("msg") if isinstance(body, dict) else "",
                }
            )

        await asyncio.gather(*[_query_one(warehouse) for warehouse in warehouses], return_exceptions=False)
        return {
            "rows": rows,
            "request_payloads": request_payloads,
            "response_previews": response_previews,
            "error": " | ".join(errors[:8]),
        }

    @staticmethod
    def _normalize_sku_query_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        if normalized.get("names") and not normalized.get("name"):
            normalized["name"] = normalized.get("names")
        normalized.pop("names", None)
        normalized.pop("wms_co_id", None)
        normalized.pop("has_lock_qty", None)

        for key in ["name", "exactly_name"]:
            value = normalized.get(key)
            if isinstance(value, str):
                value = value.strip()
                if value:
                    normalized[key] = value
                else:
                    normalized.pop(key, None)

        normalized.pop("sku_codes", None)

        sku_ids = normalized.get("sku_ids")
        if isinstance(sku_ids, list):
            normalized["sku_ids"] = ",".join(str(x).strip() for x in sku_ids if str(x).strip())
        elif isinstance(sku_ids, str):
            normalized["sku_ids"] = ",".join(x.strip() for x in sku_ids.split(",") if x.strip())
        if not normalized.get("sku_ids"):
            normalized.pop("sku_ids", None)

        max_items = max(1, min(int(settings.JUSHUITAN_MAX_ITEMS), 100))
        try:
            normalized["page_index"] = max(1, int(normalized.get("page_index", 1)))
        except (TypeError, ValueError):
            normalized["page_index"] = 1
        try:
            normalized["page_size"] = max(
                1, min(int(normalized.get("page_size", settings.JUSHUITAN_PAGE_SIZE)), max_items)
            )
        except (TypeError, ValueError):
            normalized["page_size"] = max(1, min(int(settings.JUSHUITAN_PAGE_SIZE), max_items))

        modified_begin = normalized.get("modified_begin")
        modified_end = normalized.get("modified_end")
        if bool(modified_begin) ^ bool(modified_end):
            raise ValueError("modified_begin 与 modified_end 必须同时传入")
        if modified_begin and modified_end:
            begin_dt = datetime.strptime(str(modified_begin), "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(str(modified_end), "%Y-%m-%d %H:%M:%S")
            if end_dt < begin_dt:
                raise ValueError("modified_end 不能早于 modified_begin")
            if (end_dt - begin_dt).days > 7:
                raise ValueError("modified 时间范围不能超过 7 天")

        has_query = any(normalized.get(k) for k in ("sku_ids", "name", "exactly_name"))
        has_modified = bool(modified_begin and modified_end)
        if not (has_query or has_modified):
            return {}
        return normalized

    async def _query_all_sku_rows(
        self, sku_payload: dict[str, Any], access_token: str
    ) -> tuple[list[dict[str, Any]], str, dict[str, Any], int]:
        payload = dict(sku_payload or {})
        page_size = max(1, int(payload.get("page_size", settings.JUSHUITAN_PAGE_SIZE)))
        max_pages = max(1, min(int(settings.JUSHUITAN_QUERY_MAX_PAGES), 20))
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        latest_body: dict[str, Any] = {}
        error_message = ""
        page_count = 0
        for page_index in range(1, max_pages + 1):
            page_payload = {**payload, "page_index": page_index, "page_size": page_size}
            body = await self._request_business_api(
                path=settings.JUSHUITAN_SKU_QUERY_PATH,
                biz_payload=page_payload,
                access_token=access_token,
            )
            latest_body = body if isinstance(body, dict) else {}
            page_count = page_index
            page_error = self._extract_api_error(body)
            if page_error:
                error_message = page_error
                if page_index == 1:
                    break
            page_rows = self._extract_sku_rows(body)
            for row in page_rows:
                key = f"{row.get('sku_id', '')}|{row.get('sku_code', '')}"
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
            if len(page_rows) < page_size:
                break
        return rows, error_message, latest_body, page_count

    async def _query_inventory_rows_for_warehouse(
        self, base_payload: dict[str, Any], access_token: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        payload = dict(base_payload or {})
        page_size = max(1, int(payload.get("page_size", settings.JUSHUITAN_PAGE_SIZE)))
        max_pages = max(1, min(int(settings.JUSHUITAN_QUERY_MAX_PAGES), 20))
        rows: list[dict[str, Any]] = []
        latest_body: dict[str, Any] = {}
        page_count = 0
        for page_index in range(1, max_pages + 1):
            page_payload = {**payload, "page_index": page_index, "page_size": page_size}
            body = await self._request_business_api(
                path=settings.JUSHUITAN_INVENTORY_QUERY_PATH,
                biz_payload=page_payload,
                access_token=access_token,
            )
            latest_body = body if isinstance(body, dict) else {}
            page_count = page_index
            page_rows = self._extract_inventory_rows(body)
            rows.extend(page_rows)
            if len(page_rows) < page_size:
                break
        return rows, latest_body, page_count

    async def _request_business_api(self, path: str, biz_payload: dict[str, Any], access_token: str) -> dict[str, Any]:
        if not path or not str(path).strip():
            return {"code": -1, "msg": "未配置接口路径", "issuccess": False}
        url = f"{self._base_url().rstrip('/')}/{str(path).lstrip('/')}"
        form_payload = self._build_signed_form_payload(access_token=access_token, biz_payload=biz_payload)
        headers = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
        start_at = time.perf_counter()
        logger.info(
            "[jushuitan] API START | %s",
            self._json_for_log(
                {
                    "path": path,
                    "biz_payload": biz_payload,
                }
            ),
        )
        try:
            async with httpx.AsyncClient(timeout=settings.JUSHUITAN_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, content=urlencode(form_payload))
                resp.raise_for_status()
                body = resp.json()
                if self._is_token_invalid(body):
                    logger.warning(
                        "[jushuitan] API TOKEN INVALID | %s",
                        self._json_for_log(
                            {
                                "path": path,
                                "code": body.get("code") if isinstance(body, dict) else None,
                                "msg": body.get("msg") if isinstance(body, dict) else "",
                            }
                        ),
                    )
                    refreshed = await self._refresh_access_token()
                    if not refreshed:
                        refreshed = await self._init_access_token()
                    if refreshed:
                        form_payload = self._build_signed_form_payload(access_token=refreshed, biz_payload=biz_payload)
                        resp = await client.post(url, headers=headers, content=urlencode(form_payload))
                        resp.raise_for_status()
                        body = resp.json()
                logger.info(
                    "[jushuitan] API DONE | %s",
                    self._json_for_log(
                        {
                            "path": path,
                            "http_status": resp.status_code,
                            "code": body.get("code") if isinstance(body, dict) else None,
                            "msg": body.get("msg") if isinstance(body, dict) else "",
                            "issuccess": body.get("issuccess") if isinstance(body, dict) else None,
                            "elapsed_ms": int((time.perf_counter() - start_at) * 1000),
                        }
                    ),
                )
                return body if isinstance(body, dict) else {"code": -1, "msg": "返回非JSON对象", "issuccess": False}
        except Exception as exc:
            logger.warning(
                "[jushuitan] API FAILED | %s",
                self._json_for_log(
                    {
                        "path": path,
                        "elapsed_ms": int((time.perf_counter() - start_at) * 1000),
                        "error": str(exc).strip() or repr(exc),
                    }
                ),
            )
            return {"code": -1, "msg": str(exc).strip() or repr(exc), "issuccess": False}

    def _build_signed_form_payload(self, access_token: str, biz_payload: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "app_key": self._app_key(),
            "access_token": access_token,
            "timestamp": self._now_seconds(),
            "charset": settings.JUSHUITAN_CHARSET,
            "version": settings.JUSHUITAN_VERSION,
            "biz": json.dumps(biz_payload, ensure_ascii=False, separators=(",", ":")),
        }
        payload["sign"] = self._generate_sign(payload)
        return payload

    async def _ensure_access_token(self) -> str:
        async with self._token_lock:
            if not self._access_token:
                self._load_token_cache()
            if self._access_token and (
                self._token_expire_at <= 0 or time.time() < (self._token_expire_at - 120)
            ):
                return self._access_token
            if self._refresh_token:
                refreshed = await self._refresh_access_token()
                if refreshed:
                    return refreshed
            initialized = await self._init_access_token()
            if initialized:
                return initialized
            return self._access_token

    async def _init_access_token(self) -> str:
        auth_code = self._build_auth_code()
        # 自研应用：直接调用 getInitToken，通过 app_key/app_secret + code 获取 token
        auth_payload = {
            "app_key": self._app_key(),
            "grant_type": "authorization_code",
            "charset": settings.JUSHUITAN_CHARSET,
            "timestamp": self._now_seconds(),
            "code": auth_code,
        }
        auth_payload["sign"] = self._generate_sign(auth_payload)
        body = await self._call_auth_api(auth_payload)
        token_data = self._extract_token_data(body or {})
        if not token_data:
            self._last_auth_error = self._extract_auth_error(body)
            return ""
        self._set_tokens(token_data)
        self._last_auth_error = ""
        return self._access_token

    async def _refresh_access_token(self) -> str:
        if not self._refresh_token:
            return ""
        form_payload = {
            "app_key": self._app_key(),
            "grant_type": "refresh_token",
            "charset": settings.JUSHUITAN_CHARSET,
            "timestamp": self._now_seconds(),
            "code": self._build_auth_code(),
            "refresh_token": self._refresh_token,
        }
        form_payload["sign"] = self._generate_sign(form_payload)
        body = await self._call_auth_api(form_payload)
        token_data = self._extract_token_data(body or {})
        if not token_data:
            self._last_auth_error = self._extract_auth_error(body)
            return ""
        self._set_tokens(token_data)
        self._last_auth_error = ""
        return self._access_token

    async def _call_auth_api(self, auth_payload: dict[str, Any]) -> dict[str, Any] | None:
        auth_path = settings.JUSHUITAN_AUTH_INIT_PATH_TEST if self._is_test_env() else settings.JUSHUITAN_AUTH_INIT_PATH
        if not auth_path:
            return None
        url = f"{self._base_url().rstrip('/')}/{str(auth_path).lstrip('/')}"
        headers = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
        start_at = time.perf_counter()
        logger.info(
            "[jushuitan] AUTH START | %s",
            self._json_for_log(
                {
                    "path": auth_path,
                    "grant_type": auth_payload.get("grant_type", ""),
                    "has_code": bool(auth_payload.get("code")),
                    "has_refresh_token": bool(auth_payload.get("refresh_token")),
                }
            ),
        )
        try:
            async with httpx.AsyncClient(timeout=settings.JUSHUITAN_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, content=urlencode(auth_payload))
                resp.raise_for_status()
                payload = resp.json()
                logger.info(
                    "[jushuitan] AUTH DONE | %s",
                    self._json_for_log(
                        {
                            "path": auth_path,
                            "http_status": resp.status_code,
                            "code": payload.get("code") if isinstance(payload, dict) else None,
                            "msg": payload.get("msg") if isinstance(payload, dict) else "",
                            "has_access_token": bool(self._extract_token_data(payload if isinstance(payload, dict) else {})),
                            "elapsed_ms": int((time.perf_counter() - start_at) * 1000),
                        }
                    ),
                )
                return payload if isinstance(payload, dict) else None
        except Exception as exc:
            self._last_auth_error = str(exc).strip() or repr(exc)
            logger.warning(
                "[jushuitan] AUTH FAILED | %s",
                self._json_for_log(
                    {
                        "path": auth_path,
                        "elapsed_ms": int((time.perf_counter() - start_at) * 1000),
                        "error": str(exc).strip() or repr(exc),
                    }
                ),
            )
            return None

    def _set_tokens(self, token_data: dict[str, Any]) -> None:
        self._access_token = str(token_data.get("access_token", "")).strip()
        self._refresh_token = str(token_data.get("refresh_token", self._refresh_token)).strip()
        expires_in = self._to_number(token_data.get("expires_in"))
        self._token_expire_at = time.time() + float(expires_in or 7200)
        self._save_token_cache()

    @staticmethod
    def _extract_token_data(body: dict[str, Any]) -> dict[str, Any] | None:
        for key in ["data", "result"]:
            value = body.get(key)
            if isinstance(value, dict) and value.get("access_token"):
                return value
        if body.get("access_token"):
            return body
        return None

    @staticmethod
    def _extract_auth_error(body: Any) -> str:
        if isinstance(body, dict):
            code = body.get("code")
            msg = str(body.get("msg", "")).strip()
            if msg and code is not None:
                return f"code={code}, msg={msg}"
            if msg:
                return msg
        return "鉴权接口未返回 access_token"

    @staticmethod
    def _generate_random_code(length: int = 6) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    @staticmethod
    def _build_auth_code() -> str:
        configured = str(settings.JUSHUITAN_AUTH_CODE or "").strip()
        if configured:
            return configured
        # 聚水潭文档要求 code 为随机创建的六位字符串。
        return JushuitanService._generate_random_code(6)

    def _generate_sign(self, params: dict[str, Any]) -> str:
        secret = self._app_secret()
        filtered: dict[str, str] = {}
        for key, value in params.items():
            if key == "sign" or value is None:
                continue
            text = str(value).strip()
            if text:
                filtered[str(key)] = text
        merged = f"{secret}{''.join(f'{key}{filtered[key]}' for key in sorted(filtered.keys()))}"
        algo = str(settings.JUSHUITAN_SIGN_ALGO or "md5").strip().lower()
        if algo != "md5":
            logger.warning("jushuitan sign algo=%s not supported, fallback=md5", algo)
        digest = hashlib.md5(merged.encode("utf-8")).hexdigest().lower()
        return digest if settings.JUSHUITAN_SIGN_LOWERCASE else digest.upper()

    @staticmethod
    def _now_seconds() -> int:
        return int(time.time())

    @staticmethod
    def _extract_sku_rows(body: Any) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            return []
        data = body.get("data")
        if isinstance(data, dict):
            datas = data.get("datas")
            if isinstance(datas, list):
                return [row for row in datas if isinstance(row, dict)]
        datas = body.get("datas")
        if isinstance(datas, list):
            return [row for row in datas if isinstance(row, dict)]
        return []

    @staticmethod
    def _extract_inventory_rows(body: Any) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            return []
        data = body.get("data")
        if isinstance(data, dict):
            inventorys = data.get("inventorys")
            if isinstance(inventorys, list):
                return [row for row in inventorys if isinstance(row, dict)]
        inventorys = body.get("inventorys")
        if isinstance(inventorys, list):
            return [row for row in inventorys if isinstance(row, dict)]
        return []

    @staticmethod
    def _extract_purchase_in_rows(body: Any) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            return []
        data = body.get("data")
        if isinstance(data, dict):
            datas = data.get("datas") or data.get("items")
            if isinstance(datas, list):
                return [row for row in datas if isinstance(row, dict)]
        datas = body.get("datas") or body.get("items")
        if isinstance(datas, list):
            return [row for row in datas if isinstance(row, dict)]
        return []

    @staticmethod
    def _body_has_next(body: Any) -> bool:
        if not isinstance(body, dict):
            return False
        data = body.get("data")
        if isinstance(data, dict):
            return bool(data.get("has_next"))
        return bool(body.get("has_next"))

    @staticmethod
    def _merge_price_and_inventory(
        sku_rows: list[dict[str, Any]], inventory_rows: list[dict[str, Any]], item: dict[str, Any]
    ) -> list[dict[str, Any]]:
        inventory_map: dict[str, float] = {}
        for row in inventory_rows:
            keys = [
                JushuitanService._normalize_text(row.get("sku_id")),
                JushuitanService._normalize_text(row.get("sku_code")),
                JushuitanService._normalize_text(row.get("item_sku_id")),
            ]
            qty = JushuitanService._to_number(row.get("qty"))
            if qty is None:
                qty = JushuitanService._to_number(row.get("stock_qty"))
            if qty is None:
                qty = JushuitanService._to_number(row.get("available_qty"))
            if qty is None:
                qty = JushuitanService._to_number(row.get("inventory_qty"))
            for key in keys:
                if not key:
                    continue
                inventory_map[key] = inventory_map.get(key, 0.0) + float(qty or 0.0)

        merged: list[dict[str, Any]] = []
        if sku_rows:
            for row in sku_rows:
                sku_id = JushuitanService._normalize_text(row.get("sku_id"))
                sku_code = JushuitanService._normalize_text(row.get("sku_code"))
                item_sku_id = JushuitanService._normalize_text(row.get("item_sku_id"))
                fallback_code = JushuitanService._normalize_text(item.get("product_code")) or JushuitanService._normalize_text(
                    item.get("sku")
                )
                sku_display = sku_code or sku_id or item_sku_id or fallback_code
                stock_qty = inventory_map.get(sku_id)
                if stock_qty is None:
                    stock_qty = inventory_map.get(sku_code)
                if stock_qty is None:
                    stock_qty = inventory_map.get(item_sku_id)
                if stock_qty is None and fallback_code:
                    stock_qty = inventory_map.get(fallback_code)
                merged.append(
                    {
                        "sku": sku_display,
                        "sku_id": sku_id,
                        "sku_code": sku_code,
                        "product_code": sku_display,
                        "product_name": row.get("name", item.get("product_name", "")),
                        "brand": row.get("brand", item.get("brand", "")),
                        "purchase_model": item.get("purchase_model", ""),
                        "purchase_spec": item.get("purchase_spec", ""),
                        "stock_qty": stock_qty,
                        "lead_time_days": None,
                        "supplier_type": "",
                        "order_link": "",
                        "cost_price": JushuitanService._pick_number(
                            row, ["cost_price", "costprice", "cost", "last_cost_price"]
                        ),
                        "purchase_price": JushuitanService._pick_number(
                            row, ["purchase_price", "buy_price", "last_purchase_price"]
                        ),
                        "sale_price": JushuitanService._pick_number(row, ["sale_price", "price", "retail_price"]),
                        "market_price": JushuitanService._pick_number(row, ["market_price"]),
                        "other_price_1": JushuitanService._pick_number(row, ["other_price_1"]),
                        "other_price_2": JushuitanService._pick_number(row, ["other_price_2"]),
                        "other_price_3": JushuitanService._pick_number(row, ["other_price_3"]),
                        "other_price_4": JushuitanService._pick_number(row, ["other_price_4"]),
                        "other_price_5": JushuitanService._pick_number(row, ["other_price_5"]),
                        "other_price_6": JushuitanService._pick_number(row, ["other_price_6"]),
                        "other_price_7": JushuitanService._pick_number(row, ["other_price_7"]),
                        "other_price_8": JushuitanService._pick_number(row, ["other_price_8"]),
                        "other_price_9": JushuitanService._pick_number(row, ["other_price_9"]),
                        "other_price_10": JushuitanService._pick_number(row, ["other_price_10"]),
                        "latest_purchase_price": JushuitanService._pick_number(
                            row, ["purchase_price", "buy_price", "last_purchase_price"]
                        ),
                        "supplier_name": row.get("supplier_name", ""),
                        "modified": row.get("modified", ""),
                        "raw": {"sku": row, "inventory": inventory_rows},
                    }
                )
            return merged

        # 无商品资料时，降级为库存记录输出
        for row in inventory_rows:
            qty = JushuitanService._to_number(row.get("qty"))
            if qty is None:
                qty = JushuitanService._to_number(row.get("stock_qty"))
            if qty is None:
                qty = JushuitanService._to_number(row.get("available_qty"))
            if qty is None:
                qty = JushuitanService._to_number(row.get("inventory_qty"))
            sku_code = JushuitanService._normalize_text(row.get("sku_code"))
            sku_id = JushuitanService._normalize_text(row.get("sku_id"))
            item_sku_id = JushuitanService._normalize_text(row.get("item_sku_id"))
            fallback_code = JushuitanService._normalize_text(item.get("product_code")) or JushuitanService._normalize_text(
                item.get("sku")
            )
            sku_display = sku_code or sku_id or item_sku_id or fallback_code
            merged.append(
                {
                    "sku": sku_display,
                    "sku_id": sku_id,
                    "sku_code": sku_code,
                    "product_code": sku_display,
                    "product_name": item.get("product_name", ""),
                    "brand": item.get("brand", ""),
                    "purchase_model": item.get("purchase_model", ""),
                    "purchase_spec": item.get("purchase_spec", ""),
                    "stock_qty": qty,
                    "lead_time_days": None,
                    "supplier_type": "",
                    "order_link": "",
                    "cost_price": None,
                    "purchase_price": None,
                    "sale_price": None,
                    "market_price": None,
                    "other_price_1": None,
                    "other_price_2": None,
                    "other_price_3": None,
                    "other_price_4": None,
                    "other_price_5": None,
                    "other_price_6": None,
                    "other_price_7": None,
                    "other_price_8": None,
                    "other_price_9": None,
                    "other_price_10": None,
                    "latest_purchase_price": None,
                    "supplier_name": "",
                    "modified": "",
                    "raw": {"inventory": row},
                }
            )
        return merged

    @staticmethod
    def _extract_api_error(body: Any) -> str:
        if not isinstance(body, dict):
            return "聚水潭返回非JSON对象"
        code = body.get("code")
        msg = str(body.get("msg", "")).strip()
        issuccess = body.get("issuccess")
        if (code in (0, "0") and issuccess is not False) or issuccess is True:
            return ""
        if msg:
            return msg
        if code not in (None, 0, "0"):
            return f"聚水潭返回错误码: {code}"
        return ""

    @staticmethod
    def _is_token_invalid(body: Any) -> bool:
        if not isinstance(body, dict):
            return False
        msg = str(body.get("msg", "")).lower()
        code = body.get("code")
        return ("token" in msg and ("invalid" in msg or "expired" in msg or "失效" in msg)) or code in {100, 401, 403}

    @staticmethod
    def _join_errors(errors: list[str]) -> str:
        valid = [e for e in errors if e]
        return " | ".join(valid)

    @staticmethod
    def _failed_result(error: str, request_payload: dict[str, Any], start_at: float) -> dict[str, Any]:
        return {
            "status": "failed",
            "error": error,
            "records": [],
            "request_payload": request_payload,
            "cost_ms": int((time.perf_counter() - start_at) * 1000),
        }

    @staticmethod
    def _to_number(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _pick_number(row: dict[str, Any], keys: list[str]) -> float | None:
        if not isinstance(row, dict):
            return None
        for key in keys:
            value = JushuitanService._to_number(row.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if text.lower() in {"none", "null", "nan"}:
            return ""
        return text

    @staticmethod
    def _merge_sku_rows(base_rows: list[dict[str, Any]], extra_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in [*(base_rows or []), *(extra_rows or [])]:
            if not isinstance(row, dict):
                continue
            key = (
                f"{JushuitanService._normalize_text(row.get('sku_id'))}|"
                f"{JushuitanService._normalize_text(row.get('sku_code'))}|"
                f"{JushuitanService._normalize_text(row.get('item_sku_id'))}"
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
        return merged

    @staticmethod
    def _need_price_backfill(sku_rows: list[dict[str, Any]]) -> bool:
        if not sku_rows:
            return True
        for row in sku_rows:
            if JushuitanService._pick_number(
                row, ["cost_price", "costprice", "cost", "last_cost_price", "purchase_price", "buy_price", "sale_price"]
            ) is not None:
                return False
        return True

    def _build_sku_payload_by_identifiers(
        self, item: dict[str, Any], sku_rows: list[dict[str, Any]], inventory_rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        sku_ids: list[str] = []
        # 文档要求：按 sku_ids 精确查询价格
        sku_ids.extend(self._item_code_candidates(item))
        for row in [*(sku_rows or []), *(inventory_rows or [])]:
            if not isinstance(row, dict):
                continue
            sid = self._normalize_text(row.get("sku_id"))
            if sid:
                sku_ids.append(sid)
            isid = self._normalize_text(row.get("item_sku_id"))
            if isid:
                sku_ids.append(isid)
        dedup_ids = list(dict.fromkeys(sku_ids))[:50]
        if not dedup_ids:
            return {}
        # 文档示例建议 page_size=10，sku_ids 最多 20
        page_size = max(1, min(10, len(dedup_ids)))
        return {
            "sku_ids": ",".join(dedup_ids[:50]),
            "page_index": 1,
            "page_size": page_size,
            "flds": ",".join(
                [
                    "sku_id",
                    "sku_code",
                    "name",
                    "brand",
                    "cost_price",
                    "purchase_price",
                    "sale_price",
                    "market_price",
                    "other_price_1",
                    "other_price_2",
                    "other_price_3",
                    "other_price_4",
                    "other_price_5",
                    "other_price_6",
                    "other_price_7",
                    "other_price_8",
                    "other_price_9",
                    "other_price_10",
                    "supplier_name",
                    "modified",
                ]
            ),
        }

    @staticmethod
    def _item_code_candidates(item: dict[str, Any]) -> list[str]:
        expanded_sku_ids = item.get("expanded_sku_ids") or []
        if isinstance(expanded_sku_ids, str):
            expanded_values = [part.strip() for part in expanded_sku_ids.split(",") if part.strip()]
        elif isinstance(expanded_sku_ids, list):
            expanded_values = expanded_sku_ids
        else:
            expanded_values = []
        values = [
            item.get("sku"),
            item.get("product_code"),
            *expanded_values,
            item.get("product_name"),
            item.get("product_model"),
            item.get("purchase_model"),
            item.get("purchase_spec"),
        ]
        candidates: list[str] = []
        for value in values:
            text = JushuitanService._normalize_text(value)
            if not text or not JushuitanService._looks_like_sku_code(text):
                continue
            candidates.append(text)
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _item_search_terms(item: dict[str, Any], enable_fuzzy_code_match: bool = False) -> list[str]:
        values = [
            (item.get("product_name"), True),
            (item.get("product_model"), False),
            (item.get("purchase_model"), False),
            (item.get("purchase_spec"), False),
            (item.get("sku"), False),
            (item.get("product_code"), False),
        ]
        terms: list[str] = []
        for value, is_name_field in values:
            text = JushuitanService._normalize_text(value)
            if len(text) < 2:
                continue
            if text.lower() in {"none", "null", "nan", "unknown", "未知"}:
                continue
            if not is_name_field and JushuitanService._looks_like_sku_code(text) and not enable_fuzzy_code_match:
                continue
            terms.append(text[:80])
        return list(dict.fromkeys(terms))

    @staticmethod
    def _is_test_env() -> bool:
        return str(settings.JUSHUITAN_ENV).strip().lower() in {"test", "dev", "sandbox"}

    def _base_url(self) -> str:
        if self._is_test_env():
            return (settings.JUSHUITAN_BASE_URL_TEST or "").strip()
        return (settings.JUSHUITAN_BASE_URL or "").strip()

    @staticmethod
    def _app_key() -> str:
        return (settings.JUSHUITAN_APP_KEY or "").strip()

    @staticmethod
    def _app_secret() -> str:
        return (settings.JUSHUITAN_APP_SECRET or "").strip()

    def _warehouse_list(self) -> list[dict[str, Any]]:
        seen: set[int] = set()
        merged: list[dict[str, Any]] = []
        max_warehouses = max(1, int(getattr(settings, "JUSHUITAN_INVENTORY_MAX_WAREHOUSES", 4) or 4))
        configured_ids = [
            int(value.strip())
            for value in str(getattr(settings, "JUSHUITAN_INVENTORY_WMS_CO_IDS", "") or "").split(",")
            if value.strip().isdigit()
        ]
        if configured_ids:
            default_names = {int(wh.get("wms_co_id", 0)): str(wh.get("name", "")).strip() for wh in DEFAULT_WAREHOUSES}
            for wms in configured_ids[:max_warehouses]:
                if wms <= 0 or wms in seen:
                    continue
                seen.add(wms)
                merged.append({"wms_co_id": wms, "name": default_names.get(wms, "configured warehouse")})
            return merged

        default_wms = int(settings.JUSHUITAN_DEFAULT_WMS_CO_ID or 0)
        if default_wms > 0:
            seen.add(default_wms)
            merged.append({"wms_co_id": default_wms, "name": "默认仓库"})
        for wh in DEFAULT_WAREHOUSES:
            if len(merged) >= max_warehouses:
                break
            wms = int(wh.get("wms_co_id", 0))
            if wms <= 0 or wms in seen:
                continue
            seen.add(wms)
            merged.append({"wms_co_id": wms, "name": str(wh.get("name", "")).strip()})
        return merged

    def _resolve_token_cache_path(self) -> Path:
        path = Path(self._token_cache_file or ".jushuitan_token_cache.json")
        if path.is_absolute():
            return path
        return Path(os.getcwd()) / path

    def _load_token_cache(self) -> None:
        if not self._enable_token_cache or not self._token_cache_file:
            return
        cache_path = self._resolve_token_cache_path()
        if not cache_path.exists():
            return
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            access_token = str(payload.get("access_token", "")).strip()
            refresh_token = str(payload.get("refresh_token", "")).strip()
            expire_at = self._to_number(payload.get("token_expire_at"))
            if access_token and not self._access_token:
                self._access_token = access_token
            if refresh_token and not self._refresh_token:
                self._refresh_token = refresh_token
            if expire_at and self._token_expire_at <= 0:
                self._token_expire_at = float(expire_at)
        except Exception as exc:
            logger.warning("load jushuitan token cache failed detail=%s", str(exc).strip() or repr(exc))

    def _save_token_cache(self) -> None:
        if not self._enable_token_cache or not self._token_cache_file:
            return
        cache_path = self._resolve_token_cache_path()
        payload = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "token_expire_at": self._token_expire_at,
            "updated_at": int(time.time()),
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("save jushuitan token cache failed detail=%s", str(exc).strip() or repr(exc))

    @staticmethod
    def _query_log_id(item: dict[str, Any]) -> str:
        payload = json.dumps(item or {}, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()[:10]

    @staticmethod
    def _json_for_log(payload: Any) -> str:
        try:
            return json.dumps(JushuitanService._sanitize_for_log(payload), ensure_ascii=False, default=str)
        except Exception:
            return str(payload)

    @staticmethod
    def _sanitize_for_log(value: Any) -> Any:
        secret_markers = ("token", "secret", "password", "api_key", "apikey", "sign")
        if isinstance(value, bytes):
            return f"<bytes:{len(value)}>"
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                key_lower = key_text.lower()
                if any(marker in key_lower for marker in secret_markers) and not key_lower.startswith(("has_", "is_")):
                    sanitized[key_text] = "<redacted>"
                else:
                    sanitized[key_text] = JushuitanService._sanitize_for_log(item)
            return sanitized
        if isinstance(value, list):
            limit = 8
            sanitized_items = [JushuitanService._sanitize_for_log(item) for item in value[:limit]]
            if len(value) > limit:
                sanitized_items.append({"truncated_count": len(value) - limit})
            return sanitized_items
        if isinstance(value, str):
            return JushuitanService._preview_text(value)
        return value

    @staticmethod
    def _preview_text(value: Any, limit: int = 300) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit]}...<truncated:{len(text) - limit}>"


jushuitan_service = JushuitanService()
