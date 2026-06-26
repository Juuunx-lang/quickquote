import asyncio
import json
import logging
import re
import time
import unicodedata
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.rules.sku_classifier import is_external_purchase_item
from app.db.session import AsyncSessionGoodsLocal, AsyncSessionLocal
from app.services.conversation_memory_service import conversation_memory_service
from app.services.context_store import context_store
from app.services.extract_service import extract_service
from app.services.jushuitan_service import jushuitan_service
from app.services.llm_service import llm_service
from app.services.order_goods_service import order_goods_service
from app.services.purchase_record_service import purchase_record_service
from app.services.quote_archive_service import quote_archive_service
from app.services.supplier_quote_service import supplier_quote_service

logger = logging.getLogger(__name__)


class ValuationState(TypedDict, total=False):
    session: AsyncSession
    request_id: str
    input_text: str
    excel_rows: list[str]
    enable_fuzzy_code_match: bool
    images: list[dict[str, Any]]
    raw_files: list[dict[str, Any]]
    extracted_items: list[dict[str, Any]]
    extract_failed_fallback_used: bool
    jushuitan_groups: list[dict[str, Any]]
    database_groups: list[dict[str, Any]]
    candidate_groups: list[dict[str, Any]]
    routed_groups: list[dict[str, Any]]
    final_items: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    query_summary: str


class ValuationWorkflow:
    def __init__(self) -> None:
        graph = StateGraph(ValuationState)
        graph.add_node("extract_stage", self._stage_runner("extract_stage", self._extract_stage))
        graph.add_node("multi_source_match_stage", self._stage_runner("multi_source_match_stage", self._multi_source_match_stage))
        graph.add_node("purchase_route_stage", self._stage_runner("purchase_route_stage", self._purchase_route_stage))
        graph.add_node("result_stage", self._stage_runner("result_stage", self._result_stage))
        graph.set_entry_point("extract_stage")
        graph.add_edge("extract_stage", "multi_source_match_stage")
        graph.add_edge("multi_source_match_stage", "purchase_route_stage")
        graph.add_edge("purchase_route_stage", "result_stage")
        graph.add_edge("result_stage", END)
        self._graph = graph.compile()

    def _stage_runner(self, stage_name: str, stage_fn):
        async def runner(state: dict[str, Any]) -> dict[str, Any]:
            return await self._execute_stage(stage_name, stage_fn, state)

        return runner

    async def _execute_stage(self, stage_name: str, stage_fn, state: dict[str, Any]) -> dict[str, Any]:
        start_at = time.perf_counter()
        self._log_stage_event("START", stage_name, state, self._stage_input_metrics(stage_name, state))
        self._log_stage_event("RUNNING", stage_name, state, {"action": "node_handler_entered"})
        try:
            output = await stage_fn(state)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_at) * 1000)
            logger.exception(
                "[workflow] STAGE FAILED | request_id=%s | stage=%s | elapsed_ms=%s | error=%s",
                state.get("request_id", ""),
                stage_name,
                elapsed_ms,
                str(exc).strip() or repr(exc),
            )
            raise

        elapsed_ms = int((time.perf_counter() - start_at) * 1000)
        merged_state = {**state, **(output or {})}
        self._log_stage_event(
            "DONE",
            stage_name,
            merged_state,
            {
                "elapsed_ms": elapsed_ms,
                "summary": self._stage_summary(stage_name, merged_state),
                **self._stage_output_metrics(stage_name, merged_state),
            },
        )
        return output

    async def run_text(self, session: AsyncSession, product_info: str) -> dict[str, Any]:
        return await self.run_multimodal(session=session, input_text=product_info, excel_rows=[], images=[], raw_files=[])

    async def run_file(self, session: AsyncSession, file_name: str, file_content: bytes) -> dict[str, Any]:
        return await self.run_multimodal(
            session=session,
            input_text="",
            excel_rows=[],
            images=[],
            raw_files=[{"file_name": file_name, "file_content": file_content}],
        )

    async def run_multimodal(
        self,
        session: AsyncSession,
        input_text: str,
        excel_rows: list[str] | None = None,
        enable_fuzzy_code_match: bool = False,
        images: list[dict[str, Any]] | None = None,
        raw_files: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized_images = images or []
        normalized_raw_files = raw_files or []
        if files:
            normalized_raw_files.extend(files)
        logger.debug(
            "用户上传原始数据: %s",
            self._to_json_text(
                {
                    "input_text": input_text or "",
                    "excel_rows_count": len(excel_rows or []),
                    "enable_fuzzy_code_match": bool(enable_fuzzy_code_match),
                    "images_count": len(normalized_images),
                    "raw_files_count": len(normalized_raw_files),
                }
            ),
        )
        request_id = str(uuid.uuid4())
        start_at = time.perf_counter()
        initial_state = {
            "session": session,
            "request_id": request_id,
            "input_text": input_text or "",
            "excel_rows": (excel_rows or [])[: settings.MAX_INPUT_ITEMS],
            "enable_fuzzy_code_match": bool(enable_fuzzy_code_match),
            "images": normalized_images,
            "raw_files": normalized_raw_files,
            "errors": [],
        }
        logger.info(
            "[workflow] REQUEST START | %s",
            self._to_json_text(self._sanitize_for_log(self._request_metrics(initial_state))),
        )
        try:
            output = await self._graph.ainvoke(initial_state)
            payload = await self._persist_context(output)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_at) * 1000)
            logger.exception(
                "[workflow] REQUEST FAILED | request_id=%s | elapsed_ms=%s | error=%s",
                request_id,
                elapsed_ms,
                str(exc).strip() or repr(exc),
            )
            raise
        logger.info(
            "[workflow] REQUEST DONE | %s",
            self._to_json_text(
                self._sanitize_for_log(
                    {
                        "request_id": request_id,
                        "context_id": payload.get("context_id", ""),
                        "elapsed_ms": int((time.perf_counter() - start_at) * 1000),
                        "final_items_count": len(payload.get("items", []) or []),
                        "errors_count": len(payload.get("errors", []) or []),
                    }
                )
            ),
        )
        return payload

    async def stream_multimodal_events(
        self,
        session: AsyncSession,
        input_text: str,
        excel_rows: list[str] | None = None,
        enable_fuzzy_code_match: bool = False,
        images: list[dict[str, Any]] | None = None,
        raw_files: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
    ):
        normalized_images = images or []
        normalized_raw_files = raw_files or []
        if files:
            normalized_raw_files.extend(files)
        request_id = str(uuid.uuid4())
        state: dict[str, Any] = {
            "session": session,
            "request_id": request_id,
            "input_text": input_text or "",
            "excel_rows": (excel_rows or [])[: settings.MAX_INPUT_ITEMS],
            "enable_fuzzy_code_match": bool(enable_fuzzy_code_match),
            "images": normalized_images,
            "raw_files": normalized_raw_files,
            "errors": [],
        }
        request_start_at = time.perf_counter()
        logger.info(
            "[workflow] STREAM REQUEST START | %s",
            self._to_json_text(self._sanitize_for_log(self._request_metrics(state))),
        )

        stages = [
            ("extract_stage", self._extract_stage),
            ("multi_source_match_stage", self._multi_source_match_stage),
            ("purchase_route_stage", self._purchase_route_stage),
            ("result_stage", self._result_stage),
        ]
        for stage_name, stage_fn in stages:
            yield {"event": "stage", "data": {"name": stage_name, "status": "running"}}
            stage_output = await self._execute_stage(stage_name, stage_fn, state)
            state.update(stage_output)
            yield {
                "event": "stage",
                "data": {
                    "name": stage_name,
                    "status": "done",
                    "summary": self._stage_summary(stage_name, state),
                },
            }

        payload = await self._persist_context(state)
        async for chunk in self.stream_final_answer(payload):
            yield {"event": "answer", "data": {"chunk": chunk}}
        logger.info(
            "[workflow] STREAM REQUEST DONE | %s",
            self._to_json_text(
                self._sanitize_for_log(
                    {
                        "request_id": request_id,
                        "context_id": payload.get("context_id", ""),
                        "elapsed_ms": int((time.perf_counter() - request_start_at) * 1000),
                        "final_items_count": len(payload.get("items", []) or []),
                        "errors_count": len(payload.get("errors", []) or []),
                    }
                )
            ),
        )
        yield {
            "event": "done",
            "data": {
                "request_id": payload.get("request_id", ""),
                "context_id": payload["context_id"],
                "items": payload.get("items", []),
                "errors": payload.get("errors", []),
                "query_summary": payload.get("query_summary", ""),
                "extract_failed_fallback_used": payload.get("extract_failed_fallback_used", False),
            },
        }

    async def _extract_stage(self, state: dict[str, Any]) -> dict[str, Any]:
        input_text = state.get("input_text", "")
        excel_rows = state.get("excel_rows", []) or []
        image_files = state.get("images", []) or []
        raw_files = state.get("raw_files", []) or []
        all_files = [*image_files, *raw_files]
        self._log_stage_event(
            "RUNNING",
            "extract_stage",
            state,
            {
                "action": "extract_items",
                "input_chars": len(input_text or ""),
                "excel_rows_count": len(excel_rows),
                "files_count": len(all_files),
            },
        )
        extracted = await extract_service.extract_items(input_text=input_text, excel_rows=excel_rows, input_files=all_files)
        logger.debug(
            "大模型提取结构化商品信息: %s",
            self._to_json_text(
                {
                    "items": extracted.get("items", [])[: settings.MAX_INPUT_ITEMS],
                    "extract_failed_fallback_used": bool(extracted.get("extract_failed_fallback_used", False)),
                }
            ),
        )
        self._log_stage_event(
            "RUNNING",
            "extract_stage",
            state,
            {
                "action": "extract_items_done",
                "extracted_items_count": len(extracted.get("items", []) or []),
                "extract_failed_fallback_used": bool(extracted.get("extract_failed_fallback_used", False)),
                "items_preview": self._items_preview(extracted.get("items", []) or []),
            },
        )
        return {
            "extracted_items": extracted.get("items", [])[: settings.MAX_INPUT_ITEMS],
            "extract_failed_fallback_used": bool(extracted.get("extract_failed_fallback_used", False)),
        }

    async def _multi_source_match_stage(self, state: dict[str, Any]) -> dict[str, Any]:
        items = state.get("extracted_items", []) or []
        errors = list(state.get("errors", []))
        if not items:
            self._log_stage_event(
                "RUNNING",
                "multi_source_match_stage",
                state,
                {"action": "skip_no_extracted_items"},
            )
            return {"jushuitan_groups": [], "database_groups": [], "candidate_groups": [], "errors": errors}

        self._log_stage_event(
            "RUNNING",
            "multi_source_match_stage",
            state,
            {
                "action": "query_multi_source_batch",
                "items_count": len(items),
                "candidate_limit": settings.QUERY_CANDIDATE_LIMIT,
                "sources": ["jushuitan", "database", "supplier_quote"],
            },
        )

        source_state = {**state, "errors": []}
        jushuitan_task = asyncio.create_task(self._jushuitan_match_stage(source_state))
        database_task = asyncio.create_task(self._database_match_stage(source_state))
        jushuitan_output, database_output = await asyncio.gather(
            jushuitan_task,
            database_task,
            return_exceptions=True,
        )

        jushuitan_groups: list[dict[str, Any]] = []
        database_groups: list[dict[str, Any]] = []
        if isinstance(jushuitan_output, Exception):
            errors.append({"stage": "multi_source_match_stage", "source": "jushuitan", "error": str(jushuitan_output)})
            jushuitan_groups = [
                {"idx": idx, "item": item, "candidates": [], "provider_error": "jushuitan_query_failed"}
                for idx, item in enumerate(items, start=1)
            ]
        else:
            jushuitan_groups = jushuitan_output.get("jushuitan_groups", []) or []
            errors.extend(jushuitan_output.get("errors", []) or [])

        if isinstance(database_output, Exception):
            errors.append({"stage": "multi_source_match_stage", "source": "database", "error": str(database_output)})
            database_groups = [
                {"idx": idx, "item": item, "candidates": [], "provider_error": "database_query_failed"}
                for idx, item in enumerate(items, start=1)
            ]
        else:
            database_groups = database_output.get("database_groups", []) or []
            errors.extend(database_output.get("errors", []) or [])

        candidate_groups = self._merge_source_groups(
            items=items,
            jushuitan_groups=jushuitan_groups,
            database_groups=database_groups,
        )
        self._log_stage_event(
            "RUNNING",
            "multi_source_match_stage",
            state,
            {
                "action": "merge_multi_source_candidates_done",
                "jushuitan_groups_count": len(jushuitan_groups),
                "database_groups_count": len(database_groups),
                "merged_groups_count": len(candidate_groups),
                "merged_candidate_count": sum(len(group.get("candidates", []) or []) for group in candidate_groups),
                "groups_preview": self._groups_preview(candidate_groups),
            },
        )
        return {
            "jushuitan_groups": jushuitan_groups,
            "database_groups": database_groups,
            "candidate_groups": candidate_groups,
            "errors": errors,
        }

    async def _database_match_stage(self, state: dict[str, Any]) -> dict[str, Any]:
        items = state.get("extracted_items", []) or []
        errors = list(state.get("errors", []))
        if not items:
            return {"database_groups": [], "errors": errors}

        start_at = time.perf_counter()
        self._log_stage_event(
            "RUNNING",
            "multi_source_match_stage",
            state,
            {
                "action": "query_database_batch_start",
                "items_count": len(items),
                "batch_size": int(getattr(settings, "DB_CANDIDATE_BATCH_SIZE", 25) or 25),
                "timeout_seconds": self._database_candidate_timeout_seconds(len(items)),
            },
        )
        order_groups: list[dict[str, Any]] = []
        purchase_groups: list[dict[str, Any]] = []
        supplier_quote_groups: list[dict[str, Any]] = []
        try:
            async with AsyncSessionGoodsLocal() as order_session, AsyncSessionLocal() as purchase_session:
                order_task = asyncio.create_task(
                    order_goods_service.query_candidates_by_items(
                        session=order_session,
                        items=items,
                        limit=self._intermediate_candidate_limit(),
                        enable_fuzzy_code_match=bool(state.get("enable_fuzzy_code_match", False)),
                    )
                )
                purchase_task = asyncio.create_task(
                    purchase_record_service.query_candidates_by_items(
                        session=purchase_session,
                        items=items,
                        limit=self._intermediate_candidate_limit(),
                        enable_fuzzy_code_match=bool(state.get("enable_fuzzy_code_match", False)),
                    )
                )
                supplier_quote_task = asyncio.create_task(
                    supplier_quote_service.query_candidates_by_items(
                        items=items,
                        limit=self._intermediate_candidate_limit(),
                        enable_fuzzy_code_match=bool(state.get("enable_fuzzy_code_match", False)),
                    )
                )
                order_result, purchase_result, supplier_quote_result = await asyncio.wait_for(
                    asyncio.gather(order_task, purchase_task, supplier_quote_task, return_exceptions=True),
                    timeout=self._database_candidate_timeout_seconds(len(items)),
                )
                if isinstance(order_result, Exception):
                    errors.append(
                        {
                            "stage": "multi_source_match_stage",
                            "source": "order_goods",
                            "error": str(order_result),
                        }
                    )
                    order_groups = [
                        {"idx": idx, "item": item, "candidates": [], "provider_error": "order_goods_query_failed"}
                        for idx, item in enumerate(items, start=1)
                    ]
                else:
                    order_groups = order_result
                if isinstance(purchase_result, Exception):
                    errors.append(
                        {
                            "stage": "multi_source_match_stage",
                            "source": "purchase_records",
                            "error": str(purchase_result),
                        }
                    )
                    purchase_groups = [
                        {"idx": idx, "item": item, "candidates": [], "provider_error": "purchase_records_query_failed"}
                        for idx, item in enumerate(items, start=1)
                    ]
                else:
                    purchase_groups = purchase_result
                if isinstance(supplier_quote_result, Exception):
                    errors.append(
                        {
                            "stage": "multi_source_match_stage",
                            "source": "supplier_quote",
                            "error": str(supplier_quote_result),
                        }
                    )
                    supplier_quote_groups = [
                        {"idx": idx, "item": item, "candidates": [], "provider_error": "supplier_quote_query_failed"}
                        for idx, item in enumerate(items, start=1)
                    ]
                else:
                    supplier_quote_groups = supplier_quote_result
                groups = self._merge_database_groups(
                    items=items,
                    order_groups=order_groups,
                    purchase_groups=purchase_groups,
                    supplier_quote_groups=supplier_quote_groups,
                )
        except asyncio.TimeoutError:
            errors.append({"stage": "multi_source_match_stage", "source": "database", "error": "database_query_timeout"})
            groups = [
                {"idx": idx, "item": item, "candidates": [], "provider_error": "database_query_timeout"}
                for idx, item in enumerate(items, start=1)
            ]
        except Exception as exc:
            errors.append({"stage": "multi_source_match_stage", "source": "database", "error": str(exc)})
            groups = [
                {"idx": idx, "item": item, "candidates": [], "provider_error": "database_query_failed"}
                for idx, item in enumerate(items, start=1)
            ]

        self._log_stage_event(
            "RUNNING",
            "multi_source_match_stage",
            state,
            {
                "action": "query_database_batch_done",
                "groups_count": len(groups),
                "candidates_count": sum(len(group.get("candidates", []) or []) for group in groups),
                "order_candidate_count": sum(len(group.get("candidates", []) or []) for group in order_groups),
                "purchase_candidate_count": sum(len(group.get("candidates", []) or []) for group in purchase_groups),
                "supplier_quote_candidate_count": sum(
                    len(group.get("candidates", []) or []) for group in supplier_quote_groups
                ),
                "elapsed_ms": int((time.perf_counter() - start_at) * 1000),
                "groups_preview": self._groups_preview(groups),
            },
        )
        return {"database_groups": groups, "errors": errors}

    async def _jushuitan_match_stage(self, state: dict[str, Any]) -> dict[str, Any]:
        items = state.get("extracted_items", []) or []
        errors = list(state.get("errors", []))
        if not items:
            self._log_stage_event(
                "RUNNING",
                "jushuitan_match_stage",
                state,
                {"action": "skip_no_extracted_items"},
            )
            return {"jushuitan_groups": [], "errors": errors}

        semaphore = asyncio.Semaphore(max(1, settings.JUSHUITAN_QUERY_MAX_CONCURRENCY))
        self._log_stage_event(
            "RUNNING",
            "jushuitan_match_stage",
            state,
            {
                "action": "query_jushuitan_batch",
                "items_count": len(items),
                "max_concurrency": max(1, settings.JUSHUITAN_QUERY_MAX_CONCURRENCY),
                "candidate_limit": settings.QUERY_CANDIDATE_LIMIT,
            },
        )

        async def process_one(idx: int, item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                try:
                    item_start_at = time.perf_counter()
                    self._log_stage_event(
                        "RUNNING",
                        "jushuitan_match_stage",
                        state,
                        {
                            "action": "query_jushuitan_item_start",
                            "idx": idx,
                            "total": len(items),
                            "item": self._item_preview(item),
                        },
                    )
                    query_payload = {
                        "sku": item.get("sku", ""),
                        "product_code": item.get("product_code", ""),
                        "product_name": item.get("product_name", ""),
                        "purchase_model": item.get("product_model", ""),
                        "purchase_spec": item.get("purchase_spec", ""),
                        "enable_fuzzy_code_match": bool(state.get("enable_fuzzy_code_match", False)),
                    }
                    if query_payload["enable_fuzzy_code_match"]:
                        expanded_sku_ids = await self._expand_fuzzy_jushuitan_sku_ids(query_payload)
                        if expanded_sku_ids:
                            query_payload["expanded_sku_ids"] = expanded_sku_ids
                    result = await jushuitan_service.query_item(query_payload)
                    if result.get("status") != "ok":
                        errors.append(
                            {
                                "stage": "jushuitan_match_stage",
                                "idx": idx,
                                "error": str(result.get("error", "")).strip() or "jushuitan_query_failed",
                            }
                        )
                        self._log_stage_event(
                            "RUNNING",
                            "jushuitan_match_stage",
                            state,
                            {
                                "action": "query_jushuitan_item_failed",
                                "idx": idx,
                                "elapsed_ms": int((time.perf_counter() - item_start_at) * 1000),
                                "error": str(result.get("error", "")).strip() or "jushuitan_query_failed",
                                "response_preview": result.get("response_preview", {}),
                            },
                        )
                        return {"idx": idx, "item": item, "candidates": [], "provider_error": "jushuitan_query_failed"}
                    records = result.get("records", []) or []
                    candidates = self._build_jushuitan_candidates(item=item, records=records)
                    candidates = self._dedupe_by_sku_id(candidates)
                    candidates = self._prioritize_jushuitan_candidates(candidates)[: self._intermediate_candidate_limit()]
                    self._log_stage_event(
                        "RUNNING",
                        "jushuitan_match_stage",
                        state,
                        {
                            "action": "query_jushuitan_item_done",
                            "idx": idx,
                            "elapsed_ms": int((time.perf_counter() - item_start_at) * 1000),
                            "records_count": len(records),
                            "candidates_count": len(candidates),
                            "response_preview": result.get("response_preview", {}),
                            "candidates_preview": self._candidates_preview(candidates),
                        },
                    )
                    return {"idx": idx, "item": item, "candidates": candidates, "provider_error": ""}
                except Exception as exc:
                    errors.append({"stage": "jushuitan_match_stage", "idx": idx, "error": str(exc)})
                    self._log_stage_event(
                        "RUNNING",
                        "jushuitan_match_stage",
                        state,
                        {
                            "action": "query_jushuitan_item_exception",
                            "idx": idx,
                            "error": str(exc).strip() or repr(exc),
                        },
                    )
                    return {"idx": idx, "item": item, "candidates": [], "provider_error": "jushuitan_query_failed"}

        tasks = [asyncio.create_task(process_one(idx, item)) for idx, item in enumerate(items, start=1)]
        groups = await asyncio.gather(*tasks)
        groups.sort(key=lambda x: x["idx"])
        logger.debug("jushuitan match groups: %s", self._to_json_text(groups))
        return {"jushuitan_groups": groups, "errors": errors}

    async def _expand_fuzzy_jushuitan_sku_ids(self, item: dict[str, Any]) -> list[str]:
        limit = 50
        try:
            async with AsyncSessionGoodsLocal() as order_session, AsyncSessionLocal() as purchase_session:
                order_task = asyncio.create_task(
                    order_goods_service.query_sku_ids_by_fuzzy_code(
                        session=order_session,
                        item=item,
                        limit=limit,
                    )
                )
                purchase_task = asyncio.create_task(
                    purchase_record_service.query_sku_ids_by_fuzzy_code(
                        session=purchase_session,
                        item=item,
                        limit=limit,
                    )
                )
                order_skus, purchase_skus = await asyncio.gather(order_task, purchase_task)
        except Exception as exc:
            logger.warning(
                "[workflow] fuzzy jushuitan sku expansion failed | item=%s | error=%s",
                self._to_json_text(self._item_preview(item)),
                str(exc).strip() or repr(exc),
            )
            return []

        expanded: list[str] = []
        for sku_id in [*(purchase_skus or []), *(order_skus or [])]:
            normalized = str(sku_id or "").strip()
            if normalized and normalized not in expanded:
                expanded.append(normalized)
            if len(expanded) >= limit:
                break
        return expanded

    async def _purchase_route_stage(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self._purchase_route_stage_batch(state)

    async def _purchase_route_stage_batch(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self._purchase_route_stage_batch_optimized(state)

    async def _purchase_route_stage_batch_optimized(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self._purchase_route_stage_batch_core(state)

        jushuitan_groups = state.get("jushuitan_groups", []) or []
        errors = list(state.get("errors", []))
        semaphore = asyncio.Semaphore(max(1, settings.EXTERNAL_QUERY_MAX_CONCURRENCY))

        async def _build_internal_result(candidate: dict[str, Any], provider_error: str = "") -> dict[str, Any]:
            sku_id = str(candidate.get("sku_id", "")).strip()
            product_name = candidate.get("product_name", "")
            try:
                async with semaphore:
                    async with AsyncSessionGoodsLocal() as order_session:
                        latest_order = await order_goods_service.query_latest_order_by_sku(session=order_session, sku_id=sku_id)
                return {
                    "item_type": "internal",
                    "sku_id": sku_id,
                    "product_name": product_name,
                    "stock_qty": candidate.get("stock_qty"),
                    "cost_price": candidate.get("cost_price"),
                    "raw_so_id": (latest_order or {}).get("raw_so_id", ""),
                    "order_no": (latest_order or {}).get("raw_so_id", ""),
                    "provider_error": provider_error,
                }
            except Exception as exc:
                errors.append({"stage": "purchase_route_stage", "sku_id": sku_id, "error": str(exc)})
                return {
                    "item_type": "internal",
                    "sku_id": sku_id,
                    "product_name": product_name,
                    "stock_qty": candidate.get("stock_qty"),
                    "cost_price": candidate.get("cost_price"),
                    "raw_so_id": "",
                    "order_no": "",
                    "provider_error": "order_goods_query_failed",
                }

        async def _fallback_to_internal_from_jushuitan(
            source_item: dict[str, Any], original_candidate: dict[str, Any]
        ) -> dict[str, Any] | None:
            fallback_sku_id = str(original_candidate.get("sku_id", "")).strip()
            payload = {
                "sku": fallback_sku_id,
                "product_code": "",
                # 外购回退严格按 sku_ids 精确查询，避免叠加 name 条件导致误过滤
                "product_name": "",
                "purchase_model": "",
                "purchase_spec": "",
            }
            result = await jushuitan_service.query_item(payload)
            if result.get("status") != "ok":
                return None
            records = result.get("records", []) or []
            candidates = self._build_jushuitan_candidates(item=source_item, records=records)
            candidates = self._prioritize_jushuitan_candidates(self._dedupe_by_sku_id(candidates))
            internal_candidates = [row for row in candidates if not is_external_purchase_item({"sku_id": row.get("sku_id", "")})]
            if not internal_candidates:
                return None
            selected = internal_candidates[0]
            return await _build_internal_result(
                selected,
                provider_error=str(original_candidate.get("provider_error", "")).strip() or "external_not_found_fallback_internal",
            )

        async def map_candidate(candidate: dict[str, Any], source_item: dict[str, Any]) -> dict[str, Any]:
            sku_id = str(candidate.get("sku_id", "")).strip()
            product_name = candidate.get("product_name", "")
            provider_error = candidate.get("provider_error", "")
            if not sku_id:
                return {
                    "item_type": "unknown",
                    "sku_id": "",
                    "product_name": product_name,
                    "provider_error": provider_error or "empty_sku_id",
                }
            if not is_external_purchase_item({"sku_id": sku_id}):
                return await _build_internal_result(candidate, provider_error=provider_error)
            try:
                async with semaphore:
                    async with AsyncSessionLocal() as purchase_session:
                        external = await purchase_record_service.query_external_latest(
                            session=purchase_session,
                            sku_id=sku_id,
                            limit=settings.QUERY_CANDIDATE_LIMIT,
                        )
                latest = external.get("latest") or {}
                if not latest:
                    fallback_internal = await _fallback_to_internal_from_jushuitan(source_item, candidate)
                    if fallback_internal:
                        return fallback_internal
                return {
                    "item_type": "external",
                    "sku_id": sku_id,
                    "product_name": product_name,
                    "bill_quantity": latest.get("bill_quantity"),
                    "final_purchase_price": latest.get("final_purchase_price"),
                    "selling_price": latest.get("selling_price"),
                    "settlement_unit_price": latest.get("settlement_unit_price"),
                    "settlement_amount": latest.get("settlement_amount"),
                    "gross_profit_margin": latest.get("gross_profit_margin"),
                    "tax_included": latest.get("tax_included"),
                    "order_no": latest.get("order_no"),
                    "invoice_type": latest.get("invoice_type"),
                    "tax_rate": latest.get("tax_rate"),
                    "product_link": latest.get("product_link"),
                    "supplier_name": latest.get("supplier_name"),
                    "shop_name": latest.get("shop_name"),
                    "unit": latest.get("unit"),
                    "history_records": external.get("history_records", []),
                    "provider_error": "" if latest else provider_error,
                    "manual_estimate_hint": "采购价与售价由业务人员人工估算",
                }
            except Exception as exc:
                errors.append({"stage": "purchase_route_stage", "sku_id": sku_id, "error": str(exc)})
                fallback_internal = await _fallback_to_internal_from_jushuitan(source_item, candidate)
                if fallback_internal:
                    fallback_internal["provider_error"] = "external_purchase_query_failed_fallback_internal"
                    return fallback_internal
                return {
                    "item_type": "external",
                    "sku_id": sku_id,
                    "product_name": product_name,
                    "bill_quantity": None,
                    "final_purchase_price": None,
                    "selling_price": None,
                    "gross_profit_margin": None,
                    "tax_included": None,
                    "order_no": "",
                    "invoice_type": None,
                    "tax_rate": None,
                    "product_link": "",
                    "history_records": [],
                    "provider_error": "external_purchase_query_failed",
                    "manual_estimate_hint": "采购价与售价由业务人员人工估算",
                }

        routed_groups: list[dict[str, Any]] = []
        for group in jushuitan_groups:
            candidates = group.get("candidates", []) or []
            item = group.get("item", {}) or {}
            mapped_candidates = await asyncio.gather(
                *[asyncio.create_task(map_candidate(row, item)) for row in candidates]
            )
            routed_groups.append(
                {
                    **group,
                    "candidates": self._prioritize_merged_candidates(
                        mapped_candidates,
                        item=item,
                    )[: self._intermediate_candidate_limit()],
                }
            )
        logger.debug("legacy purchase route result: %s", self._to_json_text(routed_groups))
        return {"routed_groups": routed_groups, "errors": errors}

    async def _purchase_route_stage_batch_core(self, state: dict[str, Any]) -> dict[str, Any]:
        candidate_groups = state.get("candidate_groups", []) or state.get("jushuitan_groups", []) or []
        errors = list(state.get("errors", []))
        semaphore = asyncio.Semaphore(max(1, settings.EXTERNAL_QUERY_MAX_CONCURRENCY))

        internal_skus: list[str] = []
        external_skus: list[str] = []
        for group in candidate_groups:
            for candidate in group.get("candidates", []) or []:
                sku_id = str(candidate.get("sku_id", "")).strip()
                if not sku_id:
                    continue
                if is_external_purchase_item({"sku_id": sku_id}):
                    external_skus.append(sku_id)
                else:
                    internal_skus.append(sku_id)

        self._log_stage_event(
            "RUNNING",
            "purchase_route_stage",
            state,
            {
                "action": "classify_candidates",
                "groups_count": len(candidate_groups),
                "candidate_count": len(internal_skus) + len(external_skus),
                "internal_sku_count": len(set(internal_skus)),
                "external_sku_count": len(set(external_skus)),
            },
        )

        latest_orders: dict[str, dict[str, Any]] = {}
        external_records: dict[str, dict[str, Any]] = {}
        dynamic_cost_records: dict[str, list[dict[str, Any]]] = {}
        try:
            if internal_skus:
                internal_start_at = time.perf_counter()
                self._log_stage_event(
                    "RUNNING",
                    "purchase_route_stage",
                    state,
                    {
                        "action": "batch_query_internal_orders_start",
                        "sku_count": len(set(internal_skus)),
                    },
                )
                async with AsyncSessionGoodsLocal() as order_session:
                    latest_orders = await order_goods_service.query_latest_orders_by_skus(
                        session=order_session,
                        sku_ids=internal_skus,
                    )
                self._log_stage_event(
                    "RUNNING",
                    "purchase_route_stage",
                    state,
                    {
                        "action": "batch_query_internal_orders_done",
                        "sku_count": len(set(internal_skus)),
                        "matched_count": len(latest_orders),
                        "elapsed_ms": int((time.perf_counter() - internal_start_at) * 1000),
                    },
                )
        except Exception as exc:
            errors.append({"stage": "purchase_route_stage", "error": f"batch_order_goods_query_failed: {exc}"})
            self._log_stage_event(
                "RUNNING",
                "purchase_route_stage",
                state,
                {
                    "action": "batch_query_internal_orders_failed",
                    "sku_count": len(set(internal_skus)),
                    "error": str(exc).strip() or repr(exc),
                },
            )

        try:
            if external_skus:
                external_start_at = time.perf_counter()
                self._log_stage_event(
                    "RUNNING",
                    "purchase_route_stage",
                    state,
                    {
                        "action": "batch_query_external_purchase_start",
                        "sku_count": len(set(external_skus)),
                        "limit": settings.QUERY_CANDIDATE_LIMIT,
                    },
                )
                async with AsyncSessionLocal() as purchase_session:
                    external_records = await purchase_record_service.query_external_latest_by_skus(
                        session=purchase_session,
                        sku_ids=external_skus,
                        limit=settings.QUERY_CANDIDATE_LIMIT,
                    )
                self._log_stage_event(
                    "RUNNING",
                    "purchase_route_stage",
                    state,
                    {
                        "action": "batch_query_external_purchase_done",
                        "sku_count": len(set(external_skus)),
                        "matched_count": len(external_records),
                        "elapsed_ms": int((time.perf_counter() - external_start_at) * 1000),
                    },
                )
        except Exception as exc:
            errors.append({"stage": "purchase_route_stage", "error": f"batch_external_purchase_query_failed: {exc}"})
            self._log_stage_event(
                "RUNNING",
                "purchase_route_stage",
                state,
                {
                    "action": "batch_query_external_purchase_failed",
                    "sku_count": len(set(external_skus)),
                    "error": str(exc).strip() or repr(exc),
                },
            )

        all_candidate_skus = list(dict.fromkeys([*internal_skus, *external_skus]))
        exact_jushuitan_candidates: dict[str, dict[str, Any]] = {}
        try:
            if all_candidate_skus:
                dynamic_start_at = time.perf_counter()
                self._log_stage_event(
                    "RUNNING",
                    "purchase_route_stage",
                    state,
                    {
                        "action": "batch_query_dynamic_cost_start",
                        "sku_count": len(all_candidate_skus),
                    },
                )
                dynamic_cost_records = await jushuitan_service.query_dynamic_cost_records_by_skus(
                    sku_ids=all_candidate_skus,
                    per_sku_limit=10,
                )
                self._log_stage_event(
                    "RUNNING",
                    "purchase_route_stage",
                    state,
                    {
                        "action": "batch_query_dynamic_cost_done",
                        "sku_count": len(all_candidate_skus),
                        "matched_count": len(dynamic_cost_records),
                        "elapsed_ms": int((time.perf_counter() - dynamic_start_at) * 1000),
                    },
                )
        except Exception as exc:
            errors.append({"stage": "purchase_route_stage", "error": f"batch_dynamic_cost_query_failed: {exc}"})
            self._log_stage_event(
                "RUNNING",
                "purchase_route_stage",
                state,
                {
                    "action": "batch_query_dynamic_cost_failed",
                    "sku_count": len(all_candidate_skus),
                    "error": str(exc).strip() or repr(exc),
                },
            )

        try:
            if all_candidate_skus:
                exact_start_at = time.perf_counter()
                self._log_stage_event(
                    "RUNNING",
                    "purchase_route_stage",
                    state,
                    {
                        "action": "batch_query_jushuitan_exact_backfill_start",
                        "sku_count": len(all_candidate_skus),
                    },
                )
                result = await jushuitan_service.query_item(
                    {
                        "sku": "",
                        "product_code": "",
                        "product_name": "",
                        "purchase_model": "",
                        "purchase_spec": "",
                        "expanded_sku_ids": all_candidate_skus,
                    }
                )
                if result.get("status") == "ok":
                    jushuitan_candidates = self._build_jushuitan_candidates(
                        item={},
                        records=result.get("records", []) or [],
                    )
                    for row in jushuitan_candidates:
                        for key in self._jushuitan_candidate_lookup_keys(row):
                            exact_jushuitan_candidates.setdefault(key, row)
                else:
                    errors.append(
                        {
                            "stage": "purchase_route_stage",
                            "error": str(result.get("error", "")).strip() or "jushuitan_exact_backfill_failed",
                        }
                    )
                self._log_stage_event(
                    "RUNNING",
                    "purchase_route_stage",
                    state,
                    {
                        "action": "batch_query_jushuitan_exact_backfill_done",
                        "sku_count": len(all_candidate_skus),
                        "matched_count": len(exact_jushuitan_candidates),
                        "elapsed_ms": int((time.perf_counter() - exact_start_at) * 1000),
                        "response_preview": result.get("response_preview", {}) if isinstance(result, dict) else {},
                    },
                )
        except Exception as exc:
            errors.append({"stage": "purchase_route_stage", "error": f"batch_jushuitan_exact_backfill_failed: {exc}"})
            self._log_stage_event(
                "RUNNING",
                "purchase_route_stage",
                state,
                {
                    "action": "batch_query_jushuitan_exact_backfill_failed",
                    "sku_count": len(all_candidate_skus),
                    "error": str(exc).strip() or repr(exc),
                },
            )

        def build_internal_result(
            candidate: dict[str, Any],
            provider_error: str = "",
            latest_order: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            sku_id = str(candidate.get("sku_id", "")).strip()
            product_name = candidate.get("product_name", "")
            latest_order = latest_order or latest_orders.get(sku_id) or {}
            cost_records = dynamic_cost_records.get(sku_id, [])
            latest_dynamic_cost = cost_records[0] if cost_records else {}
            return {
                **candidate,
                "item_type": "internal",
                "sku_id": sku_id,
                "product_name": product_name,
                "stock_qty": candidate.get("stock_qty"),
                "cost_price": candidate.get("cost_price"),
                "latest_dynamic_cost_price": latest_dynamic_cost.get("cost_price"),
                "latest_dynamic_cost_date": latest_dynamic_cost.get("io_date"),
                "latest_dynamic_cost_supplier": latest_dynamic_cost.get("supplier_name"),
                "dynamic_cost_records": cost_records,
                "raw_so_id": latest_order.get("raw_so_id", ""),
                "order_no": latest_order.get("raw_so_id", ""),
                "provider_error": provider_error,
            }

        async def fallback_to_internal_from_jushuitan(
            source_item: dict[str, Any], original_candidate: dict[str, Any]
        ) -> dict[str, Any] | None:
            fallback_sku_id = str(original_candidate.get("sku_id", "")).strip()
            if not fallback_sku_id:
                return None
            payload = {
                "sku": fallback_sku_id,
                "product_code": "",
                "product_name": "",
                "purchase_model": "",
                "purchase_spec": "",
            }
            async with semaphore:
                result = await jushuitan_service.query_item(payload)
            if result.get("status") != "ok":
                return None
            records = result.get("records", []) or []
            candidates = self._build_jushuitan_candidates(item=source_item, records=records)
            candidates = self._prioritize_jushuitan_candidates(self._dedupe_by_sku_id(candidates))
            internal_candidates = [row for row in candidates if not is_external_purchase_item({"sku_id": row.get("sku_id", "")})]
            if not internal_candidates:
                return None
            selected = internal_candidates[0]
            selected_sku = str(selected.get("sku_id", "")).strip()
            latest_order = latest_orders.get(selected_sku)
            if latest_order is None:
                try:
                    async with AsyncSessionGoodsLocal() as order_session:
                        latest_order = await order_goods_service.query_latest_order_by_sku(
                            session=order_session,
                            sku_id=selected_sku,
                        )
                except Exception as exc:
                    errors.append({"stage": "purchase_route_stage", "sku_id": selected_sku, "error": str(exc)})
            return build_internal_result(
                selected,
                provider_error=str(original_candidate.get("provider_error", "")).strip()
                or "external_not_found_fallback_internal",
                latest_order=latest_order or {},
            )

        async def map_candidate(candidate: dict[str, Any], source_item: dict[str, Any]) -> dict[str, Any]:
            sku_id = str(candidate.get("sku_id", "")).strip()
            provider_error = str(candidate.get("provider_error", "")).strip()
            if not sku_id:
                return {
                    **candidate,
                    "item_type": "unknown",
                    "sku_id": "",
                    "product_name": candidate.get("product_name", ""),
                    "provider_error": provider_error or "empty_sku_id",
                }
            jushuitan_supplement = exact_jushuitan_candidates.get(self._normalize_identity_text(sku_id))
            if jushuitan_supplement:
                candidate = self._merge_candidate(candidate, jushuitan_supplement)
                provider_error = str(candidate.get("provider_error", "")).strip()
            product_name = candidate.get("product_name", "")
            candidate_sources = set(self._candidate_sources(candidate))
            if "supplier_quote" in candidate_sources and not (
                {"database", "jushuitan", "purchase_records", "order_goods"} & candidate_sources
            ):
                cost_records = dynamic_cost_records.get(sku_id, [])
                latest_dynamic_cost = cost_records[0] if cost_records else {}
                return {
                    **candidate,
                    "item_type": "supplier_quote",
                    "sku_id": sku_id,
                    "product_name": product_name,
                    "latest_dynamic_cost_price": latest_dynamic_cost.get("cost_price"),
                    "latest_dynamic_cost_date": latest_dynamic_cost.get("io_date"),
                    "latest_dynamic_cost_supplier": latest_dynamic_cost.get("supplier_name"),
                    "dynamic_cost_records": cost_records,
                    "provider_error": provider_error,
                }
            if not is_external_purchase_item({"sku_id": sku_id}):
                return build_internal_result(candidate, provider_error=provider_error)

            external = external_records.get(sku_id) or {"latest": None, "history_records": []}
            latest = external.get("latest") or {}
            cost_records = dynamic_cost_records.get(sku_id, [])
            latest_dynamic_cost = cost_records[0] if cost_records else {}
            if not latest:
                fallback_internal = await fallback_to_internal_from_jushuitan(source_item, candidate)
                if fallback_internal:
                    return fallback_internal
            return {
                **candidate,
                "item_type": "external",
                "sku_id": sku_id,
                "product_name": product_name,
                "date": latest.get("date"),
                "bill_quantity": latest.get("bill_quantity"),
                "final_purchase_price": latest.get("final_purchase_price"),
                "selling_price": latest.get("selling_price"),
                "settlement_unit_price": latest.get("settlement_unit_price"),
                "settlement_amount": latest.get("settlement_amount"),
                "gross_profit_margin": latest.get("gross_profit_margin"),
                "tax_included": latest.get("tax_included"),
                "order_no": latest.get("order_no"),
                "invoice_type": latest.get("invoice_type"),
                "tax_rate": latest.get("tax_rate"),
                "product_link": latest.get("product_link"),
                "supplier_name": latest.get("supplier_name"),
                "shop_name": latest.get("shop_name"),
                "unit": latest.get("unit"),
                "latest_dynamic_cost_price": latest_dynamic_cost.get("cost_price"),
                "latest_dynamic_cost_date": latest_dynamic_cost.get("io_date"),
                "latest_dynamic_cost_supplier": latest_dynamic_cost.get("supplier_name"),
                "dynamic_cost_records": cost_records,
                "history_records": external.get("history_records", []),
                "provider_error": "" if latest else provider_error or "external_purchase_not_found",
                "manual_estimate_hint": "purchase and sale prices require manual business estimate",
            }

        routed_groups: list[dict[str, Any]] = []
        for group in candidate_groups:
            candidates = group.get("candidates", []) or []
            item = group.get("item", {}) or {}
            self._log_stage_event(
                "RUNNING",
                "purchase_route_stage",
                state,
                {
                    "action": "map_group_candidates",
                    "idx": group.get("idx"),
                    "item": self._item_preview(item),
                    "candidate_count": len(candidates),
                },
            )
            mapped_candidates = await asyncio.gather(
                *[asyncio.create_task(map_candidate(row, item)) for row in candidates]
            )
            routed_groups.append(
                {
                    **group,
                    "candidates": self._prioritize_merged_candidates(
                        mapped_candidates,
                        item=item,
                    )[: self._intermediate_candidate_limit()],
                }
            )
        self._log_stage_event(
            "RUNNING",
            "purchase_route_stage",
            state,
            {
                "action": "route_candidates_done",
                "groups_count": len(routed_groups),
                "routed_candidate_count": sum(len(group.get("candidates", []) or []) for group in routed_groups),
                "groups_preview": self._groups_preview(routed_groups),
            },
        )
        logger.debug("batch purchase route result: %s", self._to_json_text(routed_groups))
        return {"routed_groups": routed_groups, "errors": errors}

    async def _result_stage(self, state: dict[str, Any]) -> dict[str, Any]:
        routed_groups = state.get("routed_groups", []) or []
        extract_failed_fallback_used = bool(state.get("extract_failed_fallback_used", False))
        self._log_stage_event(
            "RUNNING",
            "result_stage",
            state,
            {
                "action": "assemble_results",
                "routed_groups_count": len(routed_groups),
                "routed_candidate_count": sum(len(group.get("candidates", []) or []) for group in routed_groups),
            },
        )
        
        # Sort groups: prioritize those with actionable quote data.
        def _get_group_score(group: dict[str, Any]) -> int:
            candidates = group.get("candidates", []) or []
            if not candidates:
                return 0
            return max(self._candidate_quote_value_score(candidate) for candidate in candidates)

        # Create a copy and sort
        sorted_groups = sorted(routed_groups, key=_get_group_score, reverse=True)

        final_items: list[dict[str, Any]] = []
        summaries: list[str] = []

        for group in sorted_groups:
            idx = int(group.get("idx", 0))
            item = group.get("item", {}) or {}
            candidates = self._finalize_quote_candidates(group.get("candidates", []) or [], item=item)
            status = "matched" if candidates else "no_match"
            final_items.append(
                {
                    "input_text": item.get("input_text", ""),
                    "product_name": item.get("product_name", ""),
                    "product_model": item.get("product_model", ""),
                    "query_status": status,
                    "candidates": candidates,
                }
            )
            summaries.append(f"{idx}. {item.get('product_name', '') or '未识别商品'}: {len(candidates)} candidates")
        
        query_summary = "\n".join(summaries)
        logger.debug(
            "结果组装完成 (已按报价价值优先排序): %s",
            self._to_json_text(
                {
                    "final_items_count": len(final_items),
                    "extract_failed_fallback_used": extract_failed_fallback_used,
                }
            ),
        )
        self._log_stage_event(
            "RUNNING",
            "result_stage",
            state,
            {
                "action": "assemble_results_done",
                "final_items_count": len(final_items),
                "matched_count": sum(1 for item in final_items if item.get("query_status") == "matched"),
                "no_match_count": sum(1 for item in final_items if item.get("query_status") == "no_match"),
                "items_preview": self._items_preview(final_items),
            },
        )
        return {
            "final_items": final_items,
            "query_summary": query_summary,
            "extract_failed_fallback_used": extract_failed_fallback_used,
        }

    async def _persist_context(self, output: dict[str, Any]) -> dict[str, Any]:
        context_id = str(uuid.uuid4())
        payload = {
            "request_id": output.get("request_id", str(uuid.uuid4())),
            "items": output.get("final_items", []),
            "errors": output.get("errors", []),
            "query_summary": output.get("query_summary", ""),
            "extract_failed_fallback_used": bool(output.get("extract_failed_fallback_used", False)),
        }
        logger.info(
            "[workflow] CONTEXT SAVE START | %s",
            self._to_json_text(
                self._sanitize_for_log(
                    {
                        "request_id": payload.get("request_id", ""),
                        "context_id": context_id,
                        "items_count": len(payload.get("items", []) or []),
                        "errors_count": len(payload.get("errors", []) or []),
                    }
                )
            ),
        )
        await context_store.set(context_id, payload)
        logger.info(
            "[workflow] CONTEXT SAVE DONE | %s",
            self._to_json_text(
                self._sanitize_for_log(
                    {
                        "request_id": payload.get("request_id", ""),
                        "context_id": context_id,
                    }
                )
            ),
        )
        archived_payload = {**payload, "context_id": context_id}
        await quote_archive_service.save_quote_record(
            request_id=str(payload.get("request_id", "")),
            context_id=context_id,
            input_text=str(output.get("input_text", "") or ""),
            excel_rows=output.get("excel_rows", []) or [],
            images=output.get("images", []) or [],
            raw_files=output.get("raw_files", []) or [],
            extracted_items=output.get("extracted_items", []) or [],
            system_output=archived_payload,
        )
        return archived_payload

    async def answer_followup(self, session: AsyncSession, context_id: str, question: str) -> str:
        context = await context_store.get(context_id)
        if not context:
            answer = "无效的 context_id 或上下文已过期。"
            await quote_archive_service.save_followup_record(
                context_id=context_id,
                question=question,
                answer=answer,
            )
            return answer
        history = await conversation_memory_service.get_recent_turns(session=session, context_id=context_id, limit=10)
        answer = await llm_service.answer_followup(context=context, question=question, history=history)
        await quote_archive_service.save_followup_record(
            context_id=context_id,
            question=question,
            answer=answer,
        )
        await conversation_memory_service.append_turn(session=session, context_id=context_id, role="user", content=question)
        await conversation_memory_service.append_turn(session=session, context_id=context_id, role="assistant", content=answer)
        return answer

    async def stream_final_answer(self, payload: dict[str, Any]):
        summary = payload.get("query_summary", "") or "处理完成"
        start_at = time.perf_counter()
        chunks_count = 0
        logger.info(
            "[workflow] ANSWER STREAM START | %s",
            self._to_json_text(
                self._sanitize_for_log(
                    {
                        "request_id": payload.get("request_id", ""),
                        "context_id": payload.get("context_id", ""),
                        "summary_chars": len(summary),
                    }
                )
            ),
        )
        async for chunk in llm_service.stream_text(summary):
            chunks_count += 1
            yield chunk
        logger.info(
            "[workflow] ANSWER STREAM DONE | %s",
            self._to_json_text(
                self._sanitize_for_log(
                    {
                        "request_id": payload.get("request_id", ""),
                        "context_id": payload.get("context_id", ""),
                        "chunks_count": chunks_count,
                        "elapsed_ms": int((time.perf_counter() - start_at) * 1000),
                    }
                )
            ),
        )

    def _log_stage_event(
        self,
        phase: str,
        stage_name: str,
        state: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> None:
        request_id = str(state.get("request_id", "") or "")
        data = {
            "request_id": request_id,
            "stage": stage_name,
            **(payload or {}),
        }
        logger.info("[workflow] STAGE %s | %s", phase, self._to_json_text(self._sanitize_for_log(data)))

    @staticmethod
    def _request_metrics(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": state.get("request_id", ""),
            "input_chars": len(str(state.get("input_text", "") or "")),
            "input_preview": ValuationWorkflow._preview_text(state.get("input_text", "")),
            "excel_rows_count": len(state.get("excel_rows", []) or []),
            "images_count": len(state.get("images", []) or []),
            "raw_files_count": len(state.get("raw_files", []) or []),
        }

    @staticmethod
    def _stage_input_metrics(stage_name: str, state: dict[str, Any]) -> dict[str, Any]:
        if stage_name == "extract_stage":
            return ValuationWorkflow._request_metrics(state)
        if stage_name in {"jushuitan_match_stage", "multi_source_match_stage"}:
            return {
                "extracted_items_count": len(state.get("extracted_items", []) or []),
                "items_preview": ValuationWorkflow._items_preview(state.get("extracted_items", []) or []),
                "errors_count": len(state.get("errors", []) or []),
            }
        if stage_name == "purchase_route_stage":
            groups = state.get("candidate_groups", []) or state.get("jushuitan_groups", []) or []
            return {
                "candidate_groups_count": len(groups),
                "candidate_count": sum(len(group.get("candidates", []) or []) for group in groups),
                "groups_preview": ValuationWorkflow._groups_preview(groups),
                "errors_count": len(state.get("errors", []) or []),
            }
        if stage_name == "result_stage":
            groups = state.get("routed_groups", []) or []
            return {
                "routed_groups_count": len(groups),
                "routed_candidate_count": sum(len(group.get("candidates", []) or []) for group in groups),
                "errors_count": len(state.get("errors", []) or []),
            }
        return {"errors_count": len(state.get("errors", []) or [])}

    @staticmethod
    def _stage_output_metrics(stage_name: str, state: dict[str, Any]) -> dict[str, Any]:
        if stage_name == "extract_stage":
            items = state.get("extracted_items", []) or []
            return {
                "extracted_items_count": len(items),
                "extract_failed_fallback_used": bool(state.get("extract_failed_fallback_used", False)),
                "items_preview": ValuationWorkflow._items_preview(items),
                "errors_count": len(state.get("errors", []) or []),
            }
        if stage_name == "jushuitan_match_stage":
            groups = state.get("jushuitan_groups", []) or []
            return {
                "groups_count": len(groups),
                "candidates_count": sum(len(group.get("candidates", []) or []) for group in groups),
                "groups_preview": ValuationWorkflow._groups_preview(groups),
                "errors_count": len(state.get("errors", []) or []),
            }
        if stage_name == "multi_source_match_stage":
            groups = state.get("candidate_groups", []) or []
            jushuitan_groups = state.get("jushuitan_groups", []) or []
            database_groups = state.get("database_groups", []) or []
            return {
                "groups_count": len(groups),
                "candidates_count": sum(len(group.get("candidates", []) or []) for group in groups),
                "jushuitan_candidate_count": sum(len(group.get("candidates", []) or []) for group in jushuitan_groups),
                "database_candidate_count": sum(len(group.get("candidates", []) or []) for group in database_groups),
                "groups_preview": ValuationWorkflow._groups_preview(groups),
                "errors_count": len(state.get("errors", []) or []),
            }
        if stage_name == "purchase_route_stage":
            groups = state.get("routed_groups", []) or []
            candidates = [row for group in groups for row in (group.get("candidates", []) or [])]
            return {
                "groups_count": len(groups),
                "routed_candidates_count": len(candidates),
                "internal_count": sum(1 for row in candidates if row.get("item_type") == "internal"),
                "external_count": sum(1 for row in candidates if row.get("item_type") == "external"),
                "unknown_count": sum(1 for row in candidates if row.get("item_type") == "unknown"),
                "groups_preview": ValuationWorkflow._groups_preview(groups),
                "errors_count": len(state.get("errors", []) or []),
            }
        if stage_name == "result_stage":
            items = state.get("final_items", []) or []
            return {
                "final_items_count": len(items),
                "matched_count": sum(1 for item in items if item.get("query_status") == "matched"),
                "no_match_count": sum(1 for item in items if item.get("query_status") == "no_match"),
                "items_preview": ValuationWorkflow._items_preview(items),
                "errors_count": len(state.get("errors", []) or []),
            }
        return {"errors_count": len(state.get("errors", []) or [])}

    @staticmethod
    def _item_preview(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "input_text": ValuationWorkflow._preview_text(item.get("input_text", "")),
            "product_name": ValuationWorkflow._preview_text(item.get("product_name", "")),
            "product_model": ValuationWorkflow._preview_text(item.get("product_model", "")),
            "sku": ValuationWorkflow._preview_text(item.get("sku", "")),
            "product_code": ValuationWorkflow._preview_text(item.get("product_code", "")),
        }

    @staticmethod
    def _items_preview(items: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
        return [ValuationWorkflow._item_preview(item) for item in (items or [])[:limit]]

    @staticmethod
    def _candidate_preview(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "item_type": candidate.get("item_type", ""),
            "source": candidate.get("source", ""),
            "matched_sources": candidate.get("matched_sources", []),
            "match_score": candidate.get("match_score"),
            "sku_id": ValuationWorkflow._preview_text(candidate.get("sku_id", "")),
            "sku_code": ValuationWorkflow._preview_text(candidate.get("sku_code", "")),
            "product_name": ValuationWorkflow._preview_text(candidate.get("product_name", "")),
            "stock_qty": candidate.get("stock_qty"),
            "cost_price": candidate.get("cost_price"),
            "final_purchase_price": candidate.get("final_purchase_price"),
            "selling_price": candidate.get("selling_price"),
            "provider_error": ValuationWorkflow._preview_text(candidate.get("provider_error", "")),
        }

    @staticmethod
    def _candidates_preview(candidates: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
        return [ValuationWorkflow._candidate_preview(candidate) for candidate in (candidates or [])[:limit]]

    @staticmethod
    def _groups_preview(groups: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
        preview: list[dict[str, Any]] = []
        for group in (groups or [])[:limit]:
            candidates = group.get("candidates", []) or []
            preview.append(
                {
                    "idx": group.get("idx"),
                    "item": ValuationWorkflow._item_preview(group.get("item", {}) or {}),
                    "candidates_count": len(candidates),
                    "provider_error": ValuationWorkflow._preview_text(group.get("provider_error", "")),
                    "candidates_preview": ValuationWorkflow._candidates_preview(candidates),
                }
            )
        return preview

    @staticmethod
    def _preview_text(value: Any, limit: int = 120) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit]}...<truncated:{len(text) - limit}>"

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
                    sanitized[key_text] = ValuationWorkflow._sanitize_for_log(item)
            return sanitized
        if isinstance(value, list):
            limit = 10
            sanitized_items = [ValuationWorkflow._sanitize_for_log(item) for item in value[:limit]]
            if len(value) > limit:
                sanitized_items.append({"truncated_count": len(value) - limit})
            return sanitized_items
        if isinstance(value, str):
            return ValuationWorkflow._preview_text(value, limit=300)
        return value

    @staticmethod
    def _stage_summary(stage_name: str, state: dict[str, Any]) -> str:
        if stage_name == "extract_stage":
            return f"extracted_items={len(state.get('extracted_items', []) or [])}"
        if stage_name == "jushuitan_match_stage":
            groups = state.get("jushuitan_groups", []) or []
            candidate_count = sum(len(group.get("candidates", []) or []) for group in groups)
            return f"groups={len(groups)}, candidates={candidate_count}"
        if stage_name == "multi_source_match_stage":
            groups = state.get("candidate_groups", []) or []
            candidate_count = sum(len(group.get("candidates", []) or []) for group in groups)
            jushuitan_count = sum(
                len(group.get("candidates", []) or []) for group in (state.get("jushuitan_groups", []) or [])
            )
            database_count = sum(
                len(group.get("candidates", []) or []) for group in (state.get("database_groups", []) or [])
            )
            supplier_quote_count = sum(
                int((group.get("source_counts", {}) or {}).get("supplier_quote", 0))
                for group in (state.get("database_groups", []) or [])
            )
            return (
                f"groups={len(groups)}, merged_candidates={candidate_count}, "
                f"jushuitan_candidates={jushuitan_count}, database_candidates={database_count}, "
                f"supplier_quote_candidates={supplier_quote_count}"
            )
        if stage_name == "purchase_route_stage":
            groups = state.get("routed_groups", []) or []
            candidate_count = sum(len(group.get("candidates", []) or []) for group in groups)
            return f"groups={len(groups)}, routed_candidates={candidate_count}"
        if stage_name == "result_stage":
            return state.get("query_summary", "") or f"items={len(state.get('final_items', []) or [])}"
        return ""

    def _merge_database_groups(
        self,
        items: list[dict[str, Any]],
        order_groups: list[dict[str, Any]],
        purchase_groups: list[dict[str, Any]],
        supplier_quote_groups: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        order_by_idx = {int(group.get("idx", 0) or 0): group for group in order_groups or []}
        purchase_by_idx = {int(group.get("idx", 0) or 0): group for group in purchase_groups or []}
        supplier_quote_by_idx = {int(group.get("idx", 0) or 0): group for group in supplier_quote_groups or []}
        merged_groups: list[dict[str, Any]] = []
        for idx, item in enumerate(items or [], start=1):
            order_group = order_by_idx.get(idx) or {"idx": idx, "item": item, "candidates": []}
            purchase_group = purchase_by_idx.get(idx) or {"idx": idx, "item": item, "candidates": []}
            supplier_quote_group = supplier_quote_by_idx.get(idx) or {"idx": idx, "item": item, "candidates": []}
            source_errors = [
                str(error or "").strip()
                for error in (
                    order_group.get("provider_error"),
                    purchase_group.get("provider_error"),
                    supplier_quote_group.get("provider_error"),
                )
                if str(error or "").strip()
            ]
            candidates = []
            for candidate in order_group.get("candidates", []) or []:
                candidates.append(self._prepare_candidate_source(candidate, source="database", item=item))
            for candidate in purchase_group.get("candidates", []) or []:
                candidates.append(self._prepare_candidate_source(candidate, source="database", item=item))
            for candidate in supplier_quote_group.get("candidates", []) or []:
                candidates.append(self._prepare_candidate_source(candidate, source="supplier_quote", item=item))
            merged_candidates = self._merge_candidates_by_identity(candidates)
            merged_groups.append(
                {
                    "idx": idx,
                    "item": item,
                    "candidates": self._prioritize_merged_candidates(merged_candidates, item=item)[
                        : self._intermediate_candidate_limit()
                    ],
                    "provider_error": " | ".join(dict.fromkeys(source_errors)),
                    "source_counts": {
                        "order_goods": len(order_group.get("candidates", []) or []),
                        "purchase_records": len(purchase_group.get("candidates", []) or []),
                        "supplier_quote": len(supplier_quote_group.get("candidates", []) or []),
                    },
                }
            )
        return merged_groups

    def _merge_source_groups(
        self,
        items: list[dict[str, Any]],
        jushuitan_groups: list[dict[str, Any]],
        database_groups: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        jushuitan_by_idx = {int(group.get("idx", 0) or 0): group for group in jushuitan_groups or []}
        database_by_idx = {int(group.get("idx", 0) or 0): group for group in database_groups or []}
        merged_groups: list[dict[str, Any]] = []
        for idx, item in enumerate(items or [], start=1):
            source_errors: list[str] = []
            candidates: list[dict[str, Any]] = []
            jushuitan_group = jushuitan_by_idx.get(idx) or {"idx": idx, "item": item, "candidates": []}
            database_group = database_by_idx.get(idx) or {"idx": idx, "item": item, "candidates": []}

            for error in (jushuitan_group.get("provider_error"), database_group.get("provider_error")):
                error_text = str(error or "").strip()
                if error_text:
                    source_errors.append(error_text)

            for candidate in jushuitan_group.get("candidates", []) or []:
                candidates.append(self._prepare_candidate_source(candidate, source="jushuitan", item=item))
            for candidate in database_group.get("candidates", []) or []:
                candidates.append(self._prepare_candidate_source(candidate, source="database", item=item))

            merged_candidates = self._merge_candidates_by_identity(candidates)
            merged_groups.append(
                {
                    "idx": idx,
                    "item": item,
                    "candidates": self._prioritize_merged_candidates(merged_candidates, item=item)[
                        : self._intermediate_candidate_limit()
                    ],
                    "provider_error": " | ".join(dict.fromkeys(source_errors)),
                    "source_counts": {
                        "jushuitan": len(jushuitan_group.get("candidates", []) or []),
                        "database": len(database_group.get("candidates", []) or []),
                    },
                }
            )
        return merged_groups

    def _prepare_candidate_source(
        self,
        candidate: dict[str, Any],
        source: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(candidate or {})
        sources = payload.get("matched_sources")
        if not isinstance(sources, list):
            sources = []
        sources = [str(row).strip() for row in sources if str(row).strip()]
        if source not in sources:
            sources.append(source)
        payload["matched_sources"] = sources
        payload["source"] = "+".join(sources) if sources else source
        if payload.get("match_score") is None:
            payload["match_score"] = self._candidate_match_score(item=item, candidate=payload)
        return payload

    def _merge_candidates_by_identity(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        ordered_keys: list[str] = []
        for candidate in candidates or []:
            key = self._candidate_identity(candidate)
            if not key:
                continue
            existing_key = self._find_existing_identity_key(merged, candidate)
            target_key = existing_key or key
            if target_key not in merged:
                merged[target_key] = dict(candidate)
                ordered_keys.append(target_key)
                continue
            merged[target_key] = self._merge_candidate(merged[target_key], candidate)
        return [merged[key] for key in ordered_keys]

    @staticmethod
    def _find_existing_identity_key(
        merged: dict[str, dict[str, Any]],
        candidate: dict[str, Any],
    ) -> str:
        incoming_keys = set(ValuationWorkflow._candidate_identity_lookup_keys(candidate))
        if not incoming_keys:
            return ""
        for key, existing in merged.items():
            if incoming_keys & set(ValuationWorkflow._candidate_identity_lookup_keys(existing)):
                return key
        return ""

    @staticmethod
    def _merge_candidate(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        existing = dict(existing or {})
        incoming = dict(incoming or {})
        sources = ValuationWorkflow._merge_sources(existing, incoming)
        reasons = ValuationWorkflow._merge_match_reasons(existing, incoming)
        provider_error = ValuationWorkflow._merge_provider_errors(existing, incoming)
        match_score = max(int(existing.get("match_score") or 0), int(incoming.get("match_score") or 0))

        existing_sources = set(ValuationWorkflow._candidate_sources(existing))
        incoming_sources = set(ValuationWorkflow._candidate_sources(incoming))
        existing_is_database = "database" in existing_sources
        incoming_is_database = "database" in incoming_sources
        existing_is_jushuitan = "jushuitan" in existing_sources
        incoming_is_jushuitan = "jushuitan" in incoming_sources

        if (existing_is_database and incoming_is_jushuitan) or (incoming_is_database and existing_is_jushuitan):
            primary = existing if existing_is_database else incoming
            supplement = incoming if primary is existing else existing
            merged = ValuationWorkflow._merge_database_primary_candidate(
                primary=primary,
                supplement=supplement,
                sources=ValuationWorkflow._database_primary_sources(sources),
                reasons=reasons,
                provider_error=provider_error,
                match_score=match_score,
            )
            return merged

        merged = dict(existing)
        ValuationWorkflow._apply_merge_metadata(
            merged=merged,
            sources=sources,
            reasons=reasons,
            provider_error=provider_error,
            match_score=match_score,
        )

        for key, value in incoming.items():
            if key in {"source", "matched_sources", "match_score", "match_reason", "provider_error"}:
                continue
            if ValuationWorkflow._has_value(value) and not ValuationWorkflow._has_value(merged.get(key)):
                merged[key] = value
        return merged

    @staticmethod
    def _merge_database_primary_candidate(
        primary: dict[str, Any],
        supplement: dict[str, Any],
        sources: list[str],
        reasons: list[str],
        provider_error: str,
        match_score: int,
    ) -> dict[str, Any]:
        merged = dict(primary or {})
        ValuationWorkflow._apply_merge_metadata(
            merged=merged,
            sources=sources,
            reasons=reasons,
            provider_error=provider_error,
            match_score=match_score,
        )
        for key, value in (supplement or {}).items():
            if not ValuationWorkflow._is_jushuitan_source_field(key):
                continue
            if ValuationWorkflow._has_value(value) and not ValuationWorkflow._has_value(merged.get(key)):
                merged[key] = value
        return merged

    @staticmethod
    def _apply_merge_metadata(
        merged: dict[str, Any],
        sources: list[str],
        reasons: list[str],
        provider_error: str,
        match_score: int,
    ) -> None:
        merged["matched_sources"] = sources
        merged["source"] = "+".join(sources)
        merged["match_score"] = match_score
        if reasons:
            merged["match_reason"] = reasons
        elif "match_reason" in merged:
            merged.pop("match_reason", None)
        merged["provider_error"] = provider_error

    @staticmethod
    def _merge_sources(existing: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
        sources: list[str] = []
        for source in [*ValuationWorkflow._candidate_sources(existing), *ValuationWorkflow._candidate_sources(incoming)]:
            source_text = str(source or "").strip()
            if source_text and source_text not in sources:
                sources.append(source_text)
        return sources

    @staticmethod
    def _database_primary_sources(sources: list[str]) -> list[str]:
        ordered: list[str] = []
        for preferred in ("database", "order_goods", "purchase_records", "jushuitan"):
            if preferred in sources:
                ordered.append(preferred)
        for source in sources:
            if source not in ordered:
                ordered.append(source)
        return ordered

    @staticmethod
    def _candidate_sources(candidate: dict[str, Any]) -> list[str]:
        sources: list[str] = []
        raw_sources = candidate.get("matched_sources")
        if isinstance(raw_sources, list):
            sources.extend(str(source or "").strip() for source in raw_sources)
        value = str(candidate.get("source") or "").strip()
        if value:
            sources.extend(part.strip() for part in value.split("+"))
        return [source for source in sources if source]

    @staticmethod
    def _merge_match_reasons(existing: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        for reason in [*(existing.get("match_reason") or []), *(incoming.get("match_reason") or [])]:
            reason_text = str(reason or "").strip()
            if reason_text and reason_text not in reasons:
                reasons.append(reason_text)
        return reasons

    @staticmethod
    def _merge_provider_errors(existing: dict[str, Any], incoming: dict[str, Any]) -> str:
        errors = [
            str(existing.get("provider_error", "") or "").strip(),
            str(incoming.get("provider_error", "") or "").strip(),
        ]
        return " | ".join(dict.fromkeys(error for error in errors if error))

    @staticmethod
    def _is_jushuitan_inventory_field(key: str) -> bool:
        normalized = str(key or "").strip()
        if not normalized:
            return False
        if normalized.startswith("jushuitan_") and (
            "stock" in normalized or "inventory" in normalized or "warehouse" in normalized
        ):
            return True
        return normalized in {
            "stock_qty",
            "lead_time_days",
            "inventory_qty",
            "available_qty",
            "warehouse_name",
            "warehouse_id",
            "wms_co_id",
            "lock_qty",
            "order_lock",
            "pick_lock",
            "virtual_qty",
            "purchase_qty",
            "in_qty",
            "defective_qty",
            "return_qty",
        }

    @staticmethod
    def _is_jushuitan_source_field(key: str) -> bool:
        normalized = str(key or "").strip()
        if not normalized:
            return False
        if ValuationWorkflow._is_jushuitan_inventory_field(normalized):
            return True
        return normalized in {
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
            "latest_purchase_price",
            "latest_dynamic_cost_price",
            "latest_dynamic_cost_date",
            "latest_dynamic_cost_supplier",
            "dynamic_cost_records",
            "modified",
            "raw",
        }

    @staticmethod
    def _candidate_identity(candidate: dict[str, Any]) -> str:
        for field, prefix in (
            ("sku_code", "code"),
            ("product_code", "code"),
            ("purchase_model", "model"),
            ("sku_id", "sku"),
            ("product_name", "name"),
        ):
            value = ValuationWorkflow._normalize_identity_text(candidate.get(field, ""))
            if value:
                return f"{prefix}:{value}"
        return ""

    @staticmethod
    def _candidate_identity_lookup_keys(candidate: dict[str, Any]) -> list[str]:
        keys: list[str] = []
        for field in ("sku_id", "sku_code", "product_code", "purchase_model"):
            value = ValuationWorkflow._normalize_identity_text(candidate.get(field, ""))
            if value and value not in keys:
                keys.append(value)
        name = ValuationWorkflow._normalize_identity_text(candidate.get("product_name", ""))
        brand = ValuationWorkflow._normalize_identity_text(candidate.get("brand", ""))
        spec = ValuationWorkflow._normalize_identity_text(candidate.get("purchase_spec", ""))
        if name:
            text_key = "|".join(part for part in (brand, name, spec) if part)
            if text_key and text_key not in keys:
                keys.append(f"name:{text_key}")
        return keys

    @staticmethod
    def _normalize_identity_text(value: Any) -> str:
        normalized = ValuationWorkflow._normalize_match_text(value)
        if normalized in {"none", "null", "nan", "undefined"}:
            return ""
        return normalized

    def _prioritize_merged_candidates(
        self,
        candidates: list[dict[str, Any]],
        item: dict[str, Any],
    ) -> list[dict[str, Any]]:
        def _rank(candidate: dict[str, Any]) -> tuple[int, float]:
            score = int(candidate.get("match_score") or 0)
            score += self._candidate_match_score(item=item, candidate=candidate)
            score += self._candidate_quote_value_score(candidate)
            sources = candidate.get("matched_sources") or []
            if "jushuitan" in sources and "database" in sources:
                score += 20
            elif "jushuitan" in sources:
                score += 8
            elif "database" in sources:
                score += 6
            elif "supplier_quote" in sources:
                score += 5
            if self._candidate_has_price(candidate):
                score += 10
            if self._to_float(candidate.get("stock_qty")) > 0:
                score += 8
            return (-score, -(self._to_float(candidate.get("stock_qty"))))

        return sorted(candidates or [], key=_rank)

    def _finalize_quote_candidates(
        self,
        candidates: list[dict[str, Any]],
        item: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ranked = self._prioritize_merged_candidates(candidates or [], item=item)
        actionable = [candidate for candidate in ranked if self._candidate_has_actionable_quote_data(candidate)]
        if actionable:
            input_values = [
                self._normalize_match_text(item.get(key, ""))
                for key in ("input_text", "sku", "product_code", "product_model", "purchase_model", "product_name")
            ]
            if any(self._looks_like_code(value) for value in input_values):
                strong_matches = [
                    candidate
                    for candidate in actionable
                    if max(
                        int(candidate.get("match_score") or 0),
                        self._candidate_match_score(item=item, candidate=candidate),
                    )
                    >= 80
                ]
                if strong_matches:
                    return strong_matches[: settings.QUERY_CANDIDATE_LIMIT]
            return actionable[: settings.QUERY_CANDIDATE_LIMIT]
        return []

    @staticmethod
    def _intermediate_candidate_limit() -> int:
        final_limit = max(1, int(settings.QUERY_CANDIDATE_LIMIT or 5))
        scan_limit = int(getattr(settings, "PURCHASE_CANDIDATE_SCAN_LIMIT", final_limit * 20) or final_limit * 20)
        return max(final_limit, min(scan_limit, final_limit * 4))

    @staticmethod
    def _database_candidate_timeout_seconds(item_count: int) -> int:
        base_timeout = max(1, int(getattr(settings, "DB_CANDIDATE_QUERY_TIMEOUT", 8) or 8))
        multiplier = max(1, min(int(item_count or 1), 6))
        return base_timeout * multiplier

    @staticmethod
    def _candidate_quote_value_score(candidate: dict[str, Any]) -> int:
        score = 0
        if candidate.get("final_purchase_price") is not None:
            score += 40
        if candidate.get("selling_price") is not None:
            score += 24
        if candidate.get("cost_price") is not None:
            score += 22
        if candidate.get("purchase_price") is not None:
            score += 16
        if candidate.get("settlement_unit_price") is not None:
            score += 12
        if candidate.get("settlement_amount") is not None:
            score += 10
        if candidate.get("supplier_quote_price") is not None:
            score += 18
        if candidate.get("supplier_quote_discount_price") is not None:
            score += 12
        if candidate.get("supplier_quote_retail_price") is not None:
            score += 8
        if ValuationWorkflow._to_float(candidate.get("stock_qty")) > 0:
            score += 12
        if candidate.get("bill_quantity") not in (None, "", 0):
            score += 8
        if str(candidate.get("supplier_name") or "").strip():
            score += 4
        if str(candidate.get("shop_name") or "").strip():
            score += 4
        if str(candidate.get("product_link") or "").strip():
            score += 3
        if str(candidate.get("provider_error") or "").strip():
            score -= 12
        if score == 0:
            score -= 20
        return score

    @staticmethod
    def _candidate_match_score(item: dict[str, Any], candidate: dict[str, Any]) -> int:
        sku_id = ValuationWorkflow._normalize_match_text(candidate.get("sku_id", ""))
        sku_code = ValuationWorkflow._normalize_match_text(candidate.get("sku_code", ""))
        product_name = ValuationWorkflow._normalize_match_text(candidate.get("product_name", ""))
        purchase_model = ValuationWorkflow._normalize_match_text(candidate.get("purchase_model", ""))
        purchase_spec = ValuationWorkflow._normalize_match_text(candidate.get("purchase_spec", ""))
        brand = ValuationWorkflow._normalize_match_text(candidate.get("brand", ""))
        haystack = f"{sku_id} {sku_code} {product_name} {purchase_model} {purchase_spec} {brand}"
        score = 0
        code_fields = {value for value in (sku_id, sku_code, purchase_model) if value}
        input_values = [
            ValuationWorkflow._normalize_match_text(item.get(key, ""))
            for key in ("input_text", "sku", "product_code", "product_model", "purchase_model", "product_name")
        ]

        for value in input_values:
            if not value:
                continue
            if value in code_fields:
                score += 140
            elif ValuationWorkflow._looks_like_code(value) and any(value in field for field in code_fields):
                score += 100

        for key in ("sku", "product_code"):
            value = ValuationWorkflow._normalize_match_text(item.get(key, ""))
            if not value:
                continue
            if value in {sku_id, sku_code}:
                score += 100
            elif value in haystack:
                score += 70

        model = ValuationWorkflow._normalize_match_text(item.get("product_model", ""))
        if model:
            if model in {sku_id, sku_code, purchase_model}:
                score += 90
            elif model in sku_id or model in sku_code or model in purchase_model:
                score += 70
            elif model in product_name or model in purchase_spec:
                score += 60

        input_name = ValuationWorkflow._normalize_match_text(item.get("product_name", ""))
        if input_name:
            if input_name == product_name:
                score += 60
            elif input_name in product_name:
                score += 45
            elif input_name in purchase_spec or input_name in brand:
                score += 35
        return score

    @staticmethod
    def _looks_like_code(value: Any) -> bool:
        text = ValuationWorkflow._normalize_match_text(value)
        if len(text) < 4:
            return False
        return any(char.isalpha() for char in text) and any(char.isdigit() for char in text)

    @staticmethod
    def _candidate_has_price(candidate: dict[str, Any]) -> bool:
        price_fields = [
            "cost_price",
            "purchase_price",
            "sale_price",
            "market_price",
            "final_purchase_price",
            "selling_price",
            "settlement_unit_price",
            "settlement_amount",
            "supplier_quote_price",
            "supplier_quote_discount_price",
            "supplier_quote_retail_price",
            "other_price_1",
            "other_price_2",
            "other_price_3",
            "other_price_4",
            "other_price_5",
        ]
        return any(candidate.get(field) is not None for field in price_fields)

    @staticmethod
    def _candidate_has_actionable_quote_data(candidate: dict[str, Any]) -> bool:
        if ValuationWorkflow._candidate_has_price(candidate):
            return True
        return ValuationWorkflow._to_float(candidate.get("stock_qty")) > 0

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
    def _has_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, dict)):
            return bool(value)
        return True

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _dedupe_by_sku_id(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in candidates:
            sku_id = str(row.get("sku_id", "")).strip()
            if not sku_id:
                continue
            if sku_id in seen:
                continue
            seen.add(sku_id)
            deduped.append(row)
        return deduped

    @staticmethod
    def _jushuitan_candidate_lookup_keys(candidate: dict[str, Any]) -> list[str]:
        keys: list[str] = []
        for field in ("sku_id", "sku_code", "product_code"):
            key = ValuationWorkflow._normalize_identity_text(candidate.get(field, ""))
            if key and key not in keys:
                keys.append(key)
        return keys

    @staticmethod
    def _build_jushuitan_candidates(item: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for row in records:
            sku_id = str(
                row.get("sku_id") or row.get("sku") or row.get("product_code") or row.get("sku_code") or ""
            ).strip()
            if not sku_id:
                continue
            
            # Map Jushuitan fields to frontend-friendly names
            stock_qty = row.get("stock_qty")
            cost_price = row.get("cost_price")
            purchase_price = row.get("purchase_price")
            sale_price = row.get("sale_price")
            market_price = row.get("market_price")
            
            try:
                stock_qty = float(stock_qty) if stock_qty is not None else None
            except (TypeError, ValueError):
                stock_qty = None
                
            def _to_float(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            candidates.append(
                {
                    "item_type": "internal", # Mark as internal (Jushuitan)
                    "sku_id": sku_id,
                    "sku_code": row.get("sku_code"),
                    "product_code": row.get("product_code"),
                    "product_name": str(row.get("product_name") or item.get("product_name") or "").strip(),
                    "brand": row.get("brand", ""),
                    "stock_qty": stock_qty,
                    "cost_price": _to_float(cost_price),
                    "purchase_price": _to_float(purchase_price),
                    "sale_price": _to_float(sale_price),
                    "market_price": _to_float(market_price),
                    "other_price_1": _to_float(row.get("other_price_1")),
                    "other_price_2": _to_float(row.get("other_price_2")),
                    "other_price_3": _to_float(row.get("other_price_3")),
                    "other_price_4": _to_float(row.get("other_price_4")),
                    "other_price_5": _to_float(row.get("other_price_5")),
                    "jushuitan_supplier_name": row.get("supplier_name", ""),
                    "modified": row.get("modified", ""),
                    "provider_error": "",
                    "source": "jushuitan",
                    "matched_source": "jushuitan",
                    "matched_sources": ["jushuitan"],
                }
            )
        return candidates

    @staticmethod
    def _prioritize_jushuitan_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def _rank(row: dict[str, Any]) -> tuple[int, float]:
            stock_qty = row.get("stock_qty") or 0.0
            
            # Check if any price field has data
            price_fields = [
                "cost_price", "purchase_price", "sale_price", "market_price",
                "other_price_1", "other_price_2", "other_price_3", "other_price_4", "other_price_5"
            ]
            has_price = any(row.get(f) is not None for f in price_fields)
            has_stock = stock_qty > 0

            if has_stock and has_price:
                priority = 0
            elif has_price:
                priority = 1
            elif has_stock:
                priority = 2
            else:
                priority = 3
            return (priority, -stock_qty)

        return sorted(candidates, key=_rank)

    @staticmethod
    def _pick_first_number(records: list[dict[str, Any]], key: str) -> float | None:
        for row in records:
            value = row.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _to_json_text(payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            return str(payload)


valuation_workflow = ValuationWorkflow()
