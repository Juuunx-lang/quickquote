import asyncio
import json
import logging
import re
import statistics
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ASSISTANT_SYSTEM_PROMPT = """
你是“中高端仪器采购平台智能助手”，服务于专业仪器设备采购场景。
平台定位：围绕中高端仪器、实验室设备、工业检测设备等商品，提供采购咨询与智能估价支持。

你的职责：
1. 提取仪器商品核心信息（设备名称、品牌、型号、规格参数、单位、用途、是否含税等）。
2. 基于历史采购数据给出预估购售出价、预估利润、区间判断、发票类型、购买链接(如果有)与关键依据。
3. 解释估价逻辑、数据来源、价格区间和不确定性。

行为约束：
1. 若用户问题与仪器采购或报价无关（如闲聊、通用知识、娱乐话题），不要编造答案。
2. 遇到无关问题时，礼貌引导用户提供商品信息并重新提问。
3. 当信息不足无法估价时，明确指出缺失字段，并给出最小可用提问模板。
4. 输出简洁、专业、可执行，优先中文。
""".strip()

MULTIMODAL_PARSE_SYSTEM_PROMPT = """
# 角色定位
你是通用型「采购数据多模态精准解析专家」，支持解析：图片、Excel、表格、纯文本、扫描件、OCR文本等任意格式的采购清单/物料清单。
你的唯一任务：**完整抽取、零修改、零臆造、零漏项**，输出标准合法JSON。

# 核心规则：
1. 完整性：原始清单有多少行物料，输出items就必须有多少条，**严禁漏项、合并、拆分、凭空新增**。
2. 真实性：所有字段必须**逐字照搬原文**，禁止改写、翻译、简化、归类、猜测。
3. 禁止臆造：原文没有的内容，绝对不能生成；不确定的内容必须留空或标记缺失，不能填“未知”。
4. 格式严格：只输出纯JSON，无任何解释、无注释、无多余文字、无换行冗余。

# 最终输出强制要求
1. 只输出JSON，不输出任何多余内容
2. JSON必须严格合法，双引号、逗号、括号完全正确
3. 所有内容必须来自原文，不得编造
4. 数量必须是数字类型，不能是字符串
5. 空值用 "" 或 null，禁止用“未知”
""".strip()

SQL_ASSISTANT_SYSTEM_PROMPT = """
你是“高效SQL查询助手”，专门为采购估价系统生成可执行、可审计、只读的 MySQL 查询语句。

规则：
1. 仅允许输出 SELECT 查询，严禁任何写操作与DDL。
2. 查询表固定为 purchase_records。
3. 仅可使用字段：
id, brand, purchase_spec, supplier_name, shop_name, date, purchase_model, product_name,
unit, bill_quantity, final_purchase_price, selling_price, settlement_unit_price,
settlement_amount, gross_profit_margin, tax_included, order_no, invoice_type, tax_rate, product_link。
4. SQL 必须使用命名参数（如 :product_name, :brand, :limit），禁止拼接字面值。
5. 必须包含 :limit 参数，按 date 倒序优先。
6. 目标是查询“相似商品”，优先商品名称/品牌/型号/规格匹配。
7. 索引信息：
   - idx_product_name(product_name)
   - idx_brand_model_spec(brand, purchase_model, purchase_spec)
   - idx_date(date)
   - idx_supplier_name(supplier_name)
   - idx_shop_name(shop_name)
   - idx_tax_info(tax_included, tax_rate, invoice_type)
8. 生成SQL时优先走索引：
   - 若有brand/purchase_model/purchase_spec，优先使用等值条件组合命中 idx_brand_model_spec。
   - product_name 优先前缀匹配（LIKE :product_name_prefix），避免无谓全模糊。
   - date 条件尽量使用范围过滤（如近一年）并按 date DESC。
9. 严禁将“未知/unknown/null”作为等值过滤条件；字段缺失时应省略该条件，必要时使用 IS NULL。
10. 查询策略必须分级：精确匹配优先（AND），无结果时给出宽松匹配（OR）思路。
11. 输出仅为 JSON：{"sql":"...","params":{},"limit":<正整数>,"reason":"..."}。
""".strip()

GUIDANCE_TEXT = (
    "我是中高端仪器采购平台智能助手，当前问题与仪器采购估价无直接关联。"
    "请提供仪器商品信息后再提问，例如："
    "“设备名称：气相色谱仪，品牌：Agilent，型号：8890，规格：FID检测器+自动进样器，想了解采购参考价（含税/不含税）”。"
)


class LLMService:
    async def analyze_multimodal_requirements(self, parsed_payload: dict[str, Any]) -> dict[str, Any]:
        user_question = (parsed_payload.get("user_question") or "").strip()
        normalized_text = (parsed_payload.get("normalized_text") or "").strip()
        image_assets = parsed_payload.get("image_assets", []) or []

        if not settings.LLM_API_KEY:
            features = self._rule_extract_features(f"{user_question}\n{normalized_text}".strip())
            return {
                "intent": "valuation",
                "user_question": user_question,
                "items": [features],
                "constraints": {},
                "missing_fields": [],
                "confidence": 0.5,
                "raw_evidence": [normalized_text[:500]],
                "is_relevant": self._is_product_related(f"{user_question}\n{normalized_text}"),
                "guidance": GUIDANCE_TEXT,
            }

        instruction = (
            "请抽取并返回JSON，格式："
            '{"intent":"valuation","user_question":"","items":[{"product_name":"","brand":"","purchase_model":"","purchase_spec":"","unit":""}],"constraints":{"tax_included":null,"invoice_type":"","tax_rate":null},"missing_fields":[],"confidence":0.0,"raw_evidence":[],"is_relevant":true,"guidance":""}。'
            f"items最多{settings.MAX_INPUT_ITEMS}条，字段无值填“未知”，confidence范围0~1。"
            "字段拆分要求：product_name 只保留商品主名称；型号/尺寸/通径/颜色/长度/材质细分放到 purchase_model（必要时放 purchase_spec）。"
            "如果原文是“商品名, 规格型号”或“商品名 规格型号”，必须拆分，不能把规格丢掉。"
            "示例：'不锈钢管卡扣，两通28mm【黑色】' => product_name='不锈钢管卡扣', purchase_model='两通28mm【黑色】'。"
        )
        content_parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"{instruction}\n"
                    f"用户问题:\n{user_question}\n\n"
                    f"文本证据:\n{normalized_text[:120000]}"
                ),
            }
        ]
        for asset in image_assets[:8]:
            mime = asset.get("mime_type", "image/png")
            b64 = asset.get("base64", "")
            if not b64:
                continue
            content_parts.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            )

        raw = await self._chat_messages(
            messages=[{"role": "user", "content": content_parts}],
            system_prompt=MULTIMODAL_PARSE_SYSTEM_PROMPT,
            model_name=settings.MODEL_NAME,
            temperature=0.0,
        )
        fallback = {
            "intent": "valuation",
            "user_question": user_question,
            "items": [self._rule_extract_features(f"{user_question}\n{normalized_text}".strip())],
            "constraints": {},
            "missing_fields": [],
            "confidence": 0.5,
            "raw_evidence": [normalized_text[:500]],
            "is_relevant": True,
            "guidance": "",
        }
        data = self._safe_json(raw, fallback=fallback)
        return self._normalize_multimodal_result(data, user_question, normalized_text)

    async def extract_items_for_valuation(self, raw_text: str) -> list[dict[str, str]]:
        if not settings.LLM_API_KEY:
            return self._rule_extract_items(raw_text)

        prompt = (
            "请从输入文本中提取待估价物品列表，返回JSON数组。每个物品包含：product_name(必填), brand, purchase_model, purchase_spec, unit, sku, product_code。"
            f"最多提取 {settings.MAX_INPUT_ITEMS} 条。"
            f"\n输入文本：\n{raw_text}"
        )
        content = await self._chat(prompt)
        items = self._safe_json_array(content)
        if not items:
            return self._rule_extract_items(raw_text)
        normalized: list[dict[str, str]] = []
        for item in items[:settings.MAX_INPUT_ITEMS]:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "product_name": str(item.get("product_name", "未知")).strip() or "未知",
                    "brand": str(item.get("brand", "未知")).strip() or "未知",
                    "purchase_model": str(item.get("purchase_model", "未知")).strip() or "未知",
                    "purchase_spec": str(item.get("purchase_spec", "未知")).strip() or "未知",
                    "unit": str(item.get("unit", "未知")).strip() or "未知",
                    "sku": str(item.get("sku", "")).strip(),
                    "product_code": str(item.get("product_code", "")).strip(),
                }
            )
        return normalized if normalized else self._rule_extract_items(raw_text)

    async def extract_core_requirements(self, raw_text: str) -> dict[str, Any]:
        if not self._is_product_related(raw_text):
            return {
                "demand_type": "非产品咨询",
                "features": self._rule_extract_features(raw_text),
                "items": [],
                "query_focus": [],
                "is_relevant": False,
                "guidance": GUIDANCE_TEXT,
            }

        items = await self.extract_items_for_valuation(raw_text)
        features = items[0] if items else await self.extract_features(raw_text)
        demand_type = self._classify_demand(raw_text)
        return {
            "demand_type": demand_type,
            "features": features,
            "items": items if items else [features],
            "query_focus": self._collect_keywords(features),
            "is_relevant": True,
            "guidance": "",
        }

    def _normalize_multimodal_result(
        self, data: dict[str, Any], user_question: str, normalized_text: str
    ) -> dict[str, Any]:
        items = data.get("items", [])
        if not isinstance(items, list):
            items = []
        normalized_items: list[dict[str, str]] = []
        for item in items[:settings.MAX_INPUT_ITEMS]:
            if not isinstance(item, dict):
                continue
            normalized_items.append(
                {
                    "product_name": str(item.get("product_name", "未知")).strip() or "未知",
                    "brand": str(item.get("brand", "未知")).strip() or "未知",
                    "purchase_model": str(item.get("purchase_model", "未知")).strip() or "未知",
                    "purchase_spec": str(item.get("purchase_spec", "未知")).strip() or "未知",
                    "unit": str(item.get("unit", "未知")).strip() or "未知",
                    "sku": str(item.get("sku", "")).strip(),
                    "product_code": str(item.get("product_code", "")).strip(),
                }
            )
        if not normalized_items:
            normalized_items = [self._rule_extract_features(f"{user_question}\n{normalized_text}".strip())]

        is_relevant = data.get("is_relevant")
        if not isinstance(is_relevant, bool):
            is_relevant = self._is_product_related(f"{user_question}\n{normalized_text}")

        return {
            "intent": str(data.get("intent", "valuation")),
            "user_question": str(data.get("user_question", user_question)),
            "items": normalized_items,
            "features": normalized_items[0],
            "constraints": data.get("constraints", {}) if isinstance(data.get("constraints"), dict) else {},
            "missing_fields": data.get("missing_fields", []) if isinstance(data.get("missing_fields"), list) else [],
            "confidence": self._normalize_confidence(data.get("confidence", 0.5)),
            "raw_evidence": data.get("raw_evidence", []) if isinstance(data.get("raw_evidence"), list) else [],
            "is_relevant": is_relevant,
            "guidance": str(data.get("guidance", "")) or (GUIDANCE_TEXT if not is_relevant else ""),
        }

    @staticmethod
    def _normalize_confidence(raw_confidence: Any) -> float:
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, confidence))

    async def compose_final_answer(
        self, requirements: dict[str, Any], query_summary: str, records: list[dict[str, Any]]
    ) -> str:
        if not requirements.get("is_relevant", True):
            return requirements.get("guidance") or GUIDANCE_TEXT

        features = requirements.get("features", {})
        estimate_result = await self.estimate_price(features, records)
        fallback_answer = (
            f"需求类型：{requirements.get('demand_type', '通用查询')}。\n"
            f"核心需求：{json.dumps(features, ensure_ascii=False)}\n"
            f"查询总结：{query_summary}\n"
            f"最终建议：{estimate_result.get('valuation_result', '未找到同类商品，无法估价')}。\n"
            f"说明：{estimate_result.get('reason', '无')}"
        )
        if not settings.LLM_API_KEY:
            return fallback_answer
        prompt = (
            "你是智能报价助手。请基于核心需求和数据库查询总结，输出最终简洁答案。"
            "要求：先给结论，再给关键依据。"
            f"\n核心需求: {json.dumps(requirements, ensure_ascii=False)}"
            f"\n查询总结: {query_summary}"
            f"\n估价结果: {json.dumps(estimate_result, ensure_ascii=False)}"
        )
        content = await self._chat(prompt)
        return content.strip() if content.strip() else fallback_answer

    async def compose_batch_final_answer(
        self,
        requirements: dict[str, Any],
        match_groups: list[dict[str, Any]],
        user_question: str = "",
    ) -> str:
        if not requirements.get("is_relevant", True):
            return requirements.get("guidance") or GUIDANCE_TEXT

        if not match_groups:
            return "未提取到可估价物品，请补充设备名称、品牌、型号和规格后再试。"

        fallback_lines = []
        for index, group in enumerate(match_groups, start=1):
            item = group.get("item", {})
            item_name = item.get("product_name", "未知设备")
            summary = group.get("summary", "未查询到同类商品记录。")
            estimate = await self.estimate_price(item, group.get("matches", []))
            fallback_lines.append(
                f"{index}. {item_name}：{estimate.get('valuation_result', '未找到同类商品，无法估价')}；依据：{summary}"
            )
        question_hint = f"用户问题：{user_question}\n" if user_question else ""
        fallback_answer = question_hint + "批量估价结果：\n" + "\n".join(fallback_lines)

        if not settings.LLM_API_KEY:
            return fallback_answer

        llm_input = []
        for group in match_groups[:settings.MAX_INPUT_ITEMS]:
            llm_input.append(
                {
                    "item": group.get("item", {}),
                    "summary": group.get("summary", ""),
                    "samples": self._compress_records(group.get("matches", []), max_items=8),
                }
            )

        prompt = (
            "你是中高端仪器采购平台智能助手。请基于每个待估价物品及其同类样本，给出逐条估价结论。"
            "输出要求：\n"
            "1) 每个物品一条结论；2) 每条包含建议价格或区间；3) 说明关键依据；"
            "4) 若信息不足，明确指出缺失字段并给出补充建议。"
            f"\n用户问题: {user_question}"
            f"\n待估价物品集合: {json.dumps(llm_input, ensure_ascii=False)}"
        )
        content = await self._chat(prompt, model_name=settings.MODEL_THINK)
        return content.strip() if content.strip() else fallback_answer

    async def build_sql_plan_for_item(
        self,
        item: dict[str, str],
        parsed_payload: dict[str, Any],
        user_question: str = "",
        ocr_structured: dict[str, Any] | None = None,
        limit: int = settings.MAX_INPUT_ITEMS,
    ) -> dict[str, Any]:
        fallback = self._fallback_sql_plan(item, limit)
        if not settings.LLM_API_KEY:
            return fallback

        query_context = {
            "user_question": user_question,
            "item": item,
            "ocr_structured": {
                "summary": (ocr_structured or {}).get("summary", ""),
                "current_item_hint": item,
            },
            "text_excerpt": (parsed_payload.get("normalized_text", "") or "")[:1200],
            "chunk_count": len(parsed_payload.get("chunks", [])),
            "limit": limit,
        }
        self._log_pretty(
            title="SQL Node -> MODEL_SQL Request",
            payload={
                "model": settings.MODEL_SQL,
                "system_prompt_preview": SQL_ASSISTANT_SYSTEM_PROMPT[:300],
                "query_context": query_context,
            },
        )
        prompt = (
            "请根据待估价物品生成一条查询相似数据的SQL计划。"
            "要求：若信息不足，适当降级为模糊匹配；仍需保证只读、安全、可执行。"
            f"\n输入上下文：{json.dumps(query_context, ensure_ascii=False)}"
        )
        content = await self._chat(
            prompt=prompt,
            system_prompt=SQL_ASSISTANT_SYSTEM_PROMPT,
            temperature=0.0,
            model_name=settings.MODEL_SQL,
        )
        self._log_pretty(
            title="MODEL_SQL Raw Output",
            payload={"raw_output": content[:2000]},
        )
        plan = self._safe_json(content, fallback=fallback)
        if not isinstance(plan, dict):
            return fallback
        plan.setdefault("limit", limit)
        plan.setdefault("params", {})
        plan.setdefault("source", "llm_fallback")
        self._log_pretty(
            title="MODEL_SQL Parsed Plan",
            payload=plan,
        )
        return plan

    async def stream_text(self, text: str, chunk_size: int = 32):
        normalized = text or ""
        for i in range(0, len(normalized), chunk_size):
            yield normalized[i : i + chunk_size]
            await asyncio.sleep(0)

    async def extract_features(self, raw_text: str) -> dict[str, str]:
        if not settings.LLM_API_KEY:
            return self._rule_extract_features(raw_text)

        prompt = (
            "请从以下文本提取商品字段并返回JSON: "
            '{"product_name":"","brand":"","purchase_model":"","purchase_spec":"","unit":""}。'
            "若无信息填未知。文本:\n"
            f"{raw_text}"
        )
        content = await self._chat(prompt, model_name=settings.MODEL_NAME)
        return self._safe_json(content, fallback=self._rule_extract_features(raw_text))

    async def estimate_price(
        self, features: dict[str, str], records: list[dict[str, Any]]
    ) -> dict[str, str]:
        if not records:
            return {
                "valuation_result": "未找到同类商品，无法估价",
                "reason": "数据库中无有效匹配数据。",
            }

        prices = [r["final_purchase_price"] for r in records if r.get("final_purchase_price")]
        if not prices:
            return {
                "valuation_result": "未找到同类商品，无法估价",
                "reason": "匹配数据无有效价格字段。",
            }

        weighted_price = self._weighted_price(records)
        fallback_result = {
            "valuation_result": f"建议报价：{weighted_price:.2f}",
            "reason": (
                f"基于{len(records)}条同类商品历史记录，采购价中位数 {statistics.median(prices):.2f}，"
                f"时间加权均价 {weighted_price:.2f}。"
            ),
        }
        if not settings.LLM_API_KEY:
            return fallback_result

        prompt = (
            "你是智能报价助手。根据商品特征和历史数据返回JSON:"
            '{"valuation_result":"", "reason":""}。'
            f"商品特征: {json.dumps(features, ensure_ascii=False)}\n"
            f"历史数据: {json.dumps(records[:settings.MAX_INPUT_ITEMS], ensure_ascii=False)}"
        )
        content = await self._chat(prompt, model_name=settings.MODEL_THINK)
        return self._safe_json(content, fallback=fallback_result)

    async def answer_followup(
        self, context: dict[str, Any], question: str, history: list[dict[str, Any]] | None = None
    ) -> str:
        history = history or []
        compact_context = self._compact_context_for_followup(context)
        if not settings.LLM_API_KEY:
            return (
                f"当前结论：{compact_context.get('final_answer', '无')}。"
                f"查询总结：{compact_context.get('query_summary', '无')}。"
                "如需更详细解释，请配置 LLM_API_KEY。"
            )
        history_text = "\n".join(
            [
                f"{item.get('role', 'user')}: {str(item.get('content', ''))[:800]}"
                for item in history[-10:]
            ]
        )
        prompt = (
            "你是智能报价助手，请基于上下文与短期记忆回答用户追问。\n"
            f"上下文: {json.dumps(compact_context, ensure_ascii=False)}\n"
            f"短期记忆(最近10轮):\n{history_text}\n"
            f"用户问题: {question}"
        )
        return await self._chat(prompt, model_name=settings.MODEL_THINK)

    async def _chat(
        self,
        prompt: str,
        system_prompt: str = ASSISTANT_SYSTEM_PROMPT,
        temperature: float = 0.2,
        model_name: str | None = None,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name or settings.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _chat_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        model_name: str,
        temperature: float = 0.0,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    @staticmethod
    def _rule_extract_features(raw_text: str) -> dict[str, str]:
        fields = {
            "product_name": "未知",
            "brand": "未知",
            "purchase_model": "未知",
            "purchase_spec": "未知",
            "unit": "未知",
            "sku": "",
            "product_code": "",
        }
        patterns = {
            "product_name": r"(?:商品名称|名称)[:：]\s*([^\n，,]+)",
            "brand": r"(?:品牌)[:：]\s*([^\n，,]+)",
            "purchase_model": r"(?:型号|采购型号)[:：]\s*([^\n，,]+)",
            "purchase_spec": r"(?:规格|采购规格)[:：]\s*([^\n，,]+)",
            "unit": r"(?:单位)[:：]\s*([^\n，,]+)",
            "sku": r"(?:sku|SKU)[:：]\s*([^\n，,]+)",
            "product_code": r"(?:货品编码|商品编码|编码)[:：]\s*([^\n，,]+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, raw_text, flags=re.IGNORECASE)
            if match:
                fields[key] = match.group(1).strip()

        if fields["product_name"] == "未知":
            chunks = re.split(r"[，,\n]", raw_text)
            fields["product_name"] = chunks[0].strip() if chunks and chunks[0].strip() else "未知"
        return fields

    @staticmethod
    def _safe_json(content: str, fallback: dict[str, Any]) -> dict[str, Any]:
        try:
            json_text = content.strip()
            if json_text.startswith("```"):
                json_text = json_text.strip("`")
                json_text = json_text.replace("json", "", 1).strip()
            data = json.loads(json_text)
            if isinstance(data, dict):
                return data
        except Exception:
            return fallback
        return fallback

    @staticmethod
    def _safe_json_array(content: str) -> list[dict[str, Any]]:
        try:
            json_text = content.strip()
            if json_text.startswith("```"):
                json_text = json_text.strip("`")
                json_text = json_text.replace("json", "", 1).strip()
            data = json.loads(json_text)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            return []
        return []

    @staticmethod
    def _weighted_price(records: list[dict[str, Any]]) -> float:
        weighted_sum = 0.0
        total_weight = 0.0
        for idx, item in enumerate(records):
            price = item.get("final_purchase_price")
            if not price:
                continue
            weight = max(1.0, float(len(records) - idx))
            weighted_sum += float(price) * weight
            total_weight += weight
        if total_weight == 0:
            return 0.0
        return weighted_sum / total_weight

    @staticmethod
    def _classify_demand(raw_text: str) -> str:
        text = (raw_text or "").lower()
        if any(keyword in text for keyword in ["报价", "估价", "价格", "采购价"]):
            return "价格评估"
        if any(keyword in text for keyword in ["型号", "规格", "参数"]):
            return "产品参数查询"
        if any(keyword in text for keyword in ["品牌", "供应商", "店铺"]):
            return "采购信息查询"
        return "通用商品查询"

    @staticmethod
    def _collect_keywords(features: dict[str, str]) -> list[str]:
        return [value for value in features.values() if value and value != "未知"][:5]

    def _rule_extract_items(self, raw_text: str) -> list[dict[str, str]]:
        # 简单规则：按行拆分，优先提取包含设备/商品语义的行；兜底为单条提取。
        lines = [line.strip() for line in re.split(r"[\n\r]+", raw_text or "") if line.strip()]
        candidate_lines = [line for line in lines if self._is_product_related(line)]
        if not candidate_lines:
            return [self._rule_extract_features(raw_text)]

        items = []
        for line in candidate_lines[:settings.MAX_INPUT_ITEMS]:
            items.append(self._rule_extract_features(line))
        return items if items else [self._rule_extract_features(raw_text)]

    @staticmethod
    def _compress_records(records: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
        compact = []
        for row in records[:max_items]:
            compact.append(
                {
                    "product_name": row.get("product_name"),
                    "brand": row.get("brand"),
                    "purchase_model": row.get("purchase_model"),
                    "purchase_spec": row.get("purchase_spec"),
                    "final_purchase_price": row.get("final_purchase_price"),
                    "selling_price": row.get("selling_price"),
                    "date": row.get("date"),
                    "tax_included": row.get("tax_included"),
                }
            )
        return compact

    @staticmethod
    def _is_product_related(raw_text: str) -> bool:
        text = (raw_text or "").strip().lower()
        if not text:
            return False
        product_keywords = [
            "商品",
            "产品",
            "仪器",
            "设备",
            "实验室",
            "检测",
            "分析仪",
            "色谱",
            "光谱",
            "质谱",
            "离心机",
            "显微镜",
            "品牌",
            "型号",
            "规格",
            "采购",
            "售价",
            "报价",
            "估价",
            "价格",
            "含税",
            "税率",
            "安捷伦",
            "agilent",
            "thermo",
            "赛默飞",
            "shimadzu",
            "岛津",
            "waters",
            "perkinelmer",
        ]
        return any(keyword in text for keyword in product_keywords)

    @staticmethod
    def _fallback_sql_plan(item: dict[str, str], limit: int = settings.MAX_INPUT_ITEMS) -> dict[str, Any]:
        conditions = ["final_purchase_price IS NOT NULL", "final_purchase_price > 0", "date >= :date_from"]
        params: dict[str, Any] = {"limit": limit}
        from datetime import datetime, timedelta

        params["date_from"] = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        if (item.get("product_name") or "").strip() not in {"", "未知"}:
            conditions.append("product_name LIKE :product_name_prefix")
            params["product_name_prefix"] = f"{item['product_name'].strip()}%"
        if (item.get("brand") or "").strip() not in {"", "未知"}:
            conditions.append("brand = :brand")
            params["brand"] = item["brand"].strip()
        if (item.get("purchase_model") or "").strip() not in {"", "未知"}:
            conditions.append("purchase_model = :purchase_model")
            params["purchase_model"] = item["purchase_model"].strip()
        if (item.get("purchase_spec") or "").strip() not in {"", "未知"}:
            conditions.append("purchase_spec LIKE :purchase_spec")
            params["purchase_spec"] = f"%{item['purchase_spec'].strip()}%"

        where_sql = " AND ".join(conditions) if conditions else "1=1"
        return {
            "sql": (
                "SELECT id, brand, purchase_spec, supplier_name, shop_name, date, purchase_model, "
                "product_name, unit, bill_quantity, final_purchase_price, selling_price, "
                "settlement_unit_price, settlement_amount, gross_profit_margin, tax_included, "
                "order_no, invoice_type, tax_rate, product_link "
                f"FROM purchase_records WHERE {where_sql} ORDER BY date DESC LIMIT :limit"
            ),
            "params": params,
            "limit": params["limit"],
            "reason": "规则兜底SQL计划",
            "source": "fallback_rule",
        }

    @staticmethod
    def _compact_context_for_followup(context: dict[str, Any]) -> dict[str, Any]:
        requirements = context.get("requirements", {}) if isinstance(context.get("requirements"), dict) else {}
        items = requirements.get("items", []) if isinstance(requirements.get("items"), list) else []
        compact_items = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            compact_items.append(
                {
                    "product_name": item.get("product_name", "未知"),
                    "brand": item.get("brand", "未知"),
                    "purchase_model": item.get("purchase_model", "未知"),
                    "purchase_spec": item.get("purchase_spec", "未知"),
                    "unit": item.get("unit", "未知"),
                }
            )

        return {
            "requirements": {
                "intent": requirements.get("intent", "valuation"),
                "items": compact_items,
                "confidence": requirements.get("confidence", 0),
            },
            "query_summary": str(context.get("query_summary", ""))[:1200],
            "final_answer": str(context.get("final_answer", ""))[:1200],
            "reasoning_contract": context.get("reasoning_contract", {}),
        }

    @staticmethod
    def _log_pretty(title: str, payload: dict[str, Any]) -> None:
        try:
            pretty = json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception:
            pretty = str(payload)
        logger.info("\n%s\n%s\n%s", f"========== {title} ==========", pretty, "=" * (24 + len(title)))


llm_service = LLMService()
