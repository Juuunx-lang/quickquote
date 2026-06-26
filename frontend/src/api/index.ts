export type StageName =
  | "extract_stage"
  | "multi_source_match_stage"
  | "jushuitan_match_stage"
  | "purchase_route_stage"
  | "result_stage"
  | "parse"
  | "db_query"
  | "jushuitan_query"
  | "merge_results"
  | "reasoning"
  | "table"
  | "sql_query";

export type StageStatus = "running" | "done" | "error";

export interface DatabaseRecord {
  id: number;
  brand: string | null;
  purchase_spec: string | null;
  supplier_name: string;
  shop_name: string;
  date: string | null;
  purchase_model: string;
  product_name: string;
  unit: string;
  bill_quantity: number | null;
  final_purchase_price: number | null;
  selling_price: number | null;
  settlement_unit_price: number | null;
  settlement_amount: number | null;
  gross_profit_margin: number | null;
  tax_included: string | null;
  order_no: string;
  invoice_type: string | null;
  tax_rate: number | null;
  product_link: string | null;
}

export interface JushuitanRecord {
  sku: string;
  product_code: string;
  product_name: string;
  brand: string;
  purchase_model: string;
  purchase_spec: string;
  stock_qty: number | null;
  lead_time_days: number | null;
  supplier_type: string;
  order_link: string;
  cost_price?: number | null;
  purchase_price?: number | null;
  sale_price?: number | null;
  latest_purchase_price: number | null;
  raw?: unknown;
}

export interface MergedMatchGroup {
  idx: number;
  item: Partial<ItemFeature>;
  db_matches: DatabaseRecord[];
  jushuitan_matches: JushuitanRecord[];
  matches: Array<DatabaseRecord | JushuitanRecord>;
  summary: string;
  db_status: string;
  jushuitan_status: string;
  jushuitan_error: string;
}

export interface ItemFeature {
  product_name: string;
  brand: string;
  purchase_model: string;
  purchase_spec: string;
  unit: string;
  sku: string;
  product_code: string;
}

export interface ParseNodeOutput {
  request_id: string;
  intent: string;
  user_question: string;
  normalized_text: string;
  chunks: string[];
  ocr_text: string;
  ocr_structured: unknown;
  items: ItemFeature[];
  constraints: unknown;
  missing_fields: string[];
  confidence: number;
  raw_evidence: string[];
  requirements: unknown;
  sources: unknown[];
}

export interface InternalCandidate {
  item_type: "internal";
  sku_id: string;
  sku_code?: string | null;
  product_code?: string | null;
  product_name: string;
  brand?: string | null;
  purchase_model?: string | null;
  purchase_spec?: string | null;
  supplier_name?: string | null;
  jushuitan_supplier_name?: string | null;
  shop_name?: string | null;
  unit?: string | null;
  source?: string;
  matched_sources?: string[];
  match_score?: number;
  outer_oi_id?: string;
  raw_so_id?: string;
  order_no?: string;
  stock_qty: number | null;
  cost_price: number | null;
  purchase_price?: number | null;
  sale_price?: number | null;
  latest_dynamic_cost_price?: number | null;
  latest_dynamic_cost_date?: string | null;
  latest_dynamic_cost_supplier?: string | null;
  dynamic_cost_records?: DynamicCostRecord[];
  modified?: string | null;
  date?: string | null;
  supplier_quote_supplier_name?: string | null;
  supplier_quote_brand_code?: string | null;
  supplier_quote_item_code?: string | null;
  supplier_quote_model?: string | null;
  supplier_quote_factory_model?: string | null;
  supplier_quote_price?: number | null;
  supplier_quote_retail_price?: number | null;
  supplier_quote_discount_price?: number | null;
  supplier_quote_currency?: string | null;
  supplier_quote_sales_status?: string | null;
  supplier_quote_remark?: string | null;
  supplier_quote_updated_at?: string | null;
  supplier_quote_records?: unknown[];
  bill_quantity?: number | null;
  final_purchase_price?: number | null;
  selling_price?: number | null;
  settlement_unit_price?: number | null;
  settlement_amount?: number | null;
  gross_profit_margin?: number | null;
  tax_included?: string | null;
  invoice_type?: string | null;
  tax_rate?: number | null;
  product_link?: string | null;
  history_records?: unknown[];
  matched_source?: string;
  provider_error: string;
}

export interface ExternalCandidate {
  item_type: "external";
  sku_id: string;
  sku_code?: string | null;
  product_code?: string | null;
  product_name: string;
  brand?: string | null;
  purchase_model?: string | null;
  purchase_spec?: string | null;
  supplier_name?: string | null;
  jushuitan_supplier_name?: string | null;
  shop_name?: string | null;
  unit?: string | null;
  source?: string;
  matched_sources?: string[];
  match_score?: number;
  matched_source?: string;
  stock_qty?: number | null;
  cost_price?: number | null;
  purchase_price?: number | null;
  sale_price?: number | null;
  latest_dynamic_cost_price?: number | null;
  latest_dynamic_cost_date?: string | null;
  latest_dynamic_cost_supplier?: string | null;
  dynamic_cost_records?: DynamicCostRecord[];
  modified?: string | null;
  date?: string | null;
  supplier_quote_supplier_name?: string | null;
  supplier_quote_brand_code?: string | null;
  supplier_quote_item_code?: string | null;
  supplier_quote_model?: string | null;
  supplier_quote_factory_model?: string | null;
  supplier_quote_price?: number | null;
  supplier_quote_retail_price?: number | null;
  supplier_quote_discount_price?: number | null;
  supplier_quote_currency?: string | null;
  supplier_quote_sales_status?: string | null;
  supplier_quote_remark?: string | null;
  supplier_quote_updated_at?: string | null;
  supplier_quote_records?: unknown[];
  bill_quantity: number | null;
  final_purchase_price: number | null;
  selling_price: number | null;
  settlement_unit_price?: number | null;
  settlement_amount?: number | null;
  gross_profit_margin: number | null;
  tax_included: string | null;
  order_no: string;
  invoice_type: string | null;
  tax_rate: number | null;
  product_link: string;
  history_records: unknown[];
  provider_error: string;
}

export interface SupplierQuoteCandidate {
  item_type: "supplier_quote";
  sku_id: string;
  sku_code?: string | null;
  product_code?: string | null;
  product_name: string;
  brand?: string | null;
  purchase_model?: string | null;
  purchase_spec?: string | null;
  supplier_name?: string | null;
  jushuitan_supplier_name?: string | null;
  shop_name?: string | null;
  unit?: string | null;
  source?: string;
  matched_sources?: string[];
  match_score?: number;
  matched_source?: string;
  stock_qty?: number | null;
  cost_price?: number | null;
  purchase_price?: number | null;
  sale_price?: number | null;
  latest_dynamic_cost_price?: number | null;
  latest_dynamic_cost_date?: string | null;
  latest_dynamic_cost_supplier?: string | null;
  dynamic_cost_records?: DynamicCostRecord[];
  modified?: string | null;
  date?: string | null;
  bill_quantity?: number | null;
  final_purchase_price?: number | null;
  selling_price?: number | null;
  settlement_unit_price?: number | null;
  settlement_amount?: number | null;
  gross_profit_margin?: number | null;
  tax_included?: string | null;
  order_no?: string;
  invoice_type?: string | null;
  tax_rate?: number | null;
  product_link?: string | null;
  history_records?: unknown[];
  supplier_quote_supplier_name?: string | null;
  supplier_quote_brand_code?: string | null;
  supplier_quote_item_code?: string | null;
  supplier_quote_model?: string | null;
  supplier_quote_factory_model?: string | null;
  supplier_quote_price?: number | null;
  supplier_quote_retail_price?: number | null;
  supplier_quote_discount_price?: number | null;
  supplier_quote_currency?: string | null;
  supplier_quote_sales_status?: string | null;
  supplier_quote_remark?: string | null;
  supplier_quote_updated_at?: string | null;
  supplier_quote_records?: unknown[];
  provider_error: string;
}

export type Candidate = InternalCandidate | ExternalCandidate | SupplierQuoteCandidate;

export interface DynamicCostRecord {
  sku_id: string;
  product_name?: string | null;
  properties_value?: string | null;
  io_date?: string | null;
  supplier_name?: string | null;
  qty?: number | null;
  cost_price?: number | null;
  cost_amount?: number | null;
  io_id?: string | number | null;
  po_id?: string | number | null;
  warehouse?: string | null;
  status?: string | null;
}

export interface ValuationItem {
  input_text: string;
  product_name: string;
  product_model: string;
  query_status: "matched" | "no_match";
  candidates: Candidate[];
}

export type StreamEvent =
  | { event: "stage"; data: { name: StageName; status: StageStatus; summary?: string } }
  | { event: "answer"; data: { chunk: string } }
  | { event: "job"; data: { job_id: string; status: "queued" | "running" | "done" } }
  | { event: "error"; data: { message: string } }
  | {
      event: "done";
      data: {
        context_id: string;
        request_id: string;
        items: ValuationItem[];
        errors: unknown[];
        query_summary: string;
        extract_failed_fallback_used: boolean;
      };
    };

export interface AskResponse {
  code: number;
  msg: string;
  data: {
    context_id: string;
    answer: string;
  };
}

export interface HealthResponse {
  code: number;
  msg: string;
  data: null;
}

interface ApiEnvelope<T> {
  code: number;
  msg: string;
  data: T;
}

interface JobCreateData {
  job_id: string;
  status: string;
  threshold: number;
}

const API_BASE = import.meta.env.VITE_API_BASE || "/api/v1";
const JOB_MODE_ITEM_THRESHOLD = 100;

function parseSSEEvent(rawEvent: string): StreamEvent | null {
  const lines = rawEvent.split(/\r?\n/);
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLines = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());

  if (!eventLine || dataLines.length === 0) {
    return null;
  }

  const event = eventLine.slice(6).trim();
  const dataStr = dataLines.join("\n");

  try {
    const data = JSON.parse(dataStr);
    return { event: event as StreamEvent["event"], data } as StreamEvent;
  } catch (err) {
    console.error("Failed to parse event data", err, dataStr);
    return null;
  }
}

function buildQuoteForm(
  productInfo: string,
  files: File[],
  excelRows: string[],
  enableFuzzyCodeMatch = false
): FormData {
  const form = new FormData();
  form.append("product_info", productInfo || "");
  form.append("excel_rows", JSON.stringify(excelRows || []));
  form.append("input_text", "");
  form.append("enable_fuzzy_code_match", enableFuzzyCodeMatch ? "true" : "false");

  files.forEach((file) => {
    const name = file.name.toLowerCase();
    const isImage = [".jpg", ".jpeg", ".png", ".webp"].some((ext) => name.endsWith(ext));
    const isExcel = [".xlsx", ".xls"].some((ext) => name.endsWith(ext));

    if (isImage) {
      form.append("images", file);
    } else if (!isExcel) {
      form.append("files", file);
      form.append("raw_files", file);
    }
  });

  return form;
}

async function consumeSSE(resp: Response, onEvent: (evt: StreamEvent) => void): Promise<void> {
  if (!resp.ok) {
    throw new Error(`流式请求失败：${resp.status}`);
  }

  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const payload = (await resp.json()) as ApiEnvelope<unknown>;
    throw new Error(payload?.msg || "流式请求失败");
  }

  if (!resp.body) {
    throw new Error("流式响应为空");
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let gotDoneEvent = false;
  let errorMessage = "";

  const handleRawEvent = (rawEvent: string) => {
    const parsed = parseSSEEvent(rawEvent);
    if (!parsed) return;
    if (parsed.event === "done") gotDoneEvent = true;
    if (parsed.event === "error") errorMessage = parsed.data.message || "Stream returned an error event";
    onEvent(parsed);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? "";
    parts.forEach(handleRawEvent);
  }

  if (buffer.trim()) {
    handleRawEvent(buffer);
  }

  if (errorMessage) {
    throw new Error(errorMessage);
  }
  if (!gotDoneEvent) {
    throw new Error("流式响应未返回完成事件");
  }
}

async function createQuoteJob(
  productInfo: string,
  files: File[],
  excelRows: string[],
  enableFuzzyCodeMatch: boolean
): Promise<string> {
  const resp = await fetch(`${API_BASE}/chat/jobs`, {
    method: "POST",
    body: buildQuoteForm(productInfo, files, excelRows, enableFuzzyCodeMatch),
  });

  if (!resp.ok) {
    throw new Error(`后台任务创建失败：${resp.status}`);
  }

  const payload = (await resp.json()) as ApiEnvelope<JobCreateData>;
  if (!payload.data?.job_id) {
    throw new Error(payload.msg || "后台任务创建失败：缺少 job_id");
  }
  return payload.data.job_id;
}

async function streamQuoteJob(jobId: string, onEvent: (evt: StreamEvent) => void): Promise<void> {
  const resp = await fetch(`${API_BASE}/chat/jobs/${jobId}/stream`);
  await consumeSSE(resp, onEvent);
}

export async function streamQuote(
  productInfo: string,
  files: File[],
  excelRows: string[],
  enableFuzzyCodeMatch: boolean,
  onEvent: (evt: StreamEvent) => void
) {
  if ((excelRows || []).length >= JOB_MODE_ITEM_THRESHOLD) {
    const jobId = await createQuoteJob(productInfo, files, excelRows, enableFuzzyCodeMatch);
    onEvent({ event: "job", data: { job_id: jobId, status: "queued" } });
    await streamQuoteJob(jobId, onEvent);
    return;
  }

  const resp = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    body: buildQuoteForm(productInfo, files, excelRows, enableFuzzyCodeMatch),
  });
  await consumeSSE(resp, onEvent);
}

export async function askQuestion(contextId: string, question: string): Promise<AskResponse> {
  const resp = await fetch(`${API_BASE}/chat/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      context_id: contextId,
      question,
    }),
  });

  if (!resp.ok) {
    throw new Error(`追问失败：${resp.status}`);
  }

  return resp.json();
}

export async function checkHealth(): Promise<HealthResponse> {
  const resp = await fetch(`${API_BASE}/health`);
  if (!resp.ok) {
    throw new Error(`健康检查失败：${resp.status}`);
  }
  return resp.json();
}
