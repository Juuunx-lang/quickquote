import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CircleGauge,
  Database,
  Layers3,
  type LucideIcon,
  Plus,
  ReceiptText,
  RefreshCw,
} from "lucide-react";
import { ChatInput } from "../components/ChatInput";
import { DatabaseRecords } from "../components/DatabaseRecords";
import { ProgressIndicator } from "../components/ProgressIndicator";
import { QuoteExportPanel } from "../components/QuoteExportPanel";
import { Candidate, checkHealth, StageName, streamQuote } from "../api";
import { useChatStore } from "../store/useChatStore";
import { cn } from "../lib/utils";

const KNOWN_STAGES: StageName[] = [
  "extract_stage",
  "multi_source_match_stage",
  "jushuitan_match_stage",
  "purchase_route_stage",
  "result_stage",
  "parse",
  "db_query",
  "jushuitan_query",
  "merge_results",
  "reasoning",
  "table",
  "sql_query",
];

type RecordFilter = "all" | "purchase" | "quote";

function isKnownStage(stage: string): stage is StageName {
  return KNOWN_STAGES.includes(stage as StageName);
}

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return !Number.isNaN(value);
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function hasPurchaseRecord(candidate: Candidate): boolean {
  const hasJushuitanSource =
    candidate.source?.includes("jushuitan") || candidate.matched_sources?.includes("jushuitan") || false;
  return hasJushuitanSource || candidate.matched_sources?.includes("purchase_records") || false;
}

function hasSupplierQuote(candidate: Candidate): boolean {
  return [
    candidate.supplier_quote_supplier_name,
    candidate.supplier_quote_price,
    candidate.supplier_quote_updated_at,
    candidate.supplier_quote_item_code,
    candidate.supplier_quote_model,
    candidate.supplier_quote_factory_model,
  ].some(hasValue) || (Array.isArray(candidate.supplier_quote_records) && candidate.supplier_quote_records.length > 0);
}

export function Chat() {
  const {
    streamStatus,
    valuationItems,
    setStreamStatus,
    setStage,
    setQuerySummary,
    setContextId,
    setValuationItems,
    setExtractFailedFallbackUsed,
    resetStream,
    resetAll,
  } = useChatStore();
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");
  const [recordFilter, setRecordFilter] = useState<RecordFilter>("all");

  const metrics = useMemo(() => {
    const items = valuationItems || [];
    const candidates = items.flatMap((item) => item.candidates);
    return {
      items: items.length,
      matched: items.filter((item) => item.query_status === "matched").length,
      candidates: candidates.length,
      purchase: candidates.filter(hasPurchaseRecord).length,
      quote: candidates.filter(hasSupplierQuote).length,
    };
  }, [valuationItems]);

  useEffect(() => {
    let cancelled = false;
    checkHealth()
      .then((response) => {
        if (!cancelled) setBackendStatus(response.code === 200 ? "online" : "offline");
      })
      .catch(() => {
        if (!cancelled) setBackendStatus("offline");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleNewQuote = () => {
    if (streamStatus === "running") return;
    resetAll();
  };

  const handleRetry = () => {
    setStreamStatus("idle");
  };

  const handleSend = async (text: string, files: File[], excelRows: string[], enableFuzzyCodeMatch: boolean) => {
    setStreamStatus("running");

    resetStream();
    setStreamStatus("running");
    try {
      await streamQuote(text, files, excelRows, enableFuzzyCodeMatch, (event) => {
        if (event.event === "stage") {
          if (isKnownStage(event.data.name)) {
            setStage(event.data.name, event.data.status === "done");
          }
          if (event.data.summary) {
            setQuerySummary(event.data.summary);
          }
        }

        if (event.event === "job") {
          setQuerySummary(`后台任务 ${event.data.job_id}：${event.data.status}`);
        }

        if (event.event === "answer") {
          return;
        }

        if (event.event === "error") {
          setQuerySummary(`请求失败：${event.data.message}`);
          setStreamStatus("error");
        }

        if (event.event === "done") {
          setContextId(event.data.context_id);
          setQuerySummary(event.data.query_summary || "");
          setValuationItems(event.data.items || []);
          setExtractFailedFallbackUsed(Boolean(event.data.extract_failed_fallback_used));
          setStreamStatus("done");
        }
      });
    } catch (error) {
      setQuerySummary(`流式请求中断：${error instanceof Error ? error.message : "未知错误"}`);
      setStreamStatus("error");
    }
  };

  return (
    <div className="min-h-[100dvh] bg-[#f4f5f1] text-zinc-950">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_10%_10%,rgba(20,184,166,0.12),transparent_26%),radial-gradient(circle_at_90%_0%,rgba(39,39,42,0.08),transparent_24%)]" />
      <div className="noise-overlay" />

      <header className="relative mx-auto flex max-w-[1500px] items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-950 text-white shadow-[0_14px_40px_-22px_rgba(24,24,27,0.7)]">
            <CircleGauge size={20} />
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-tight text-zinc-950">QuickQuote 智能报价工作台</h1>
            <p className="mt-0.5 text-xs text-zinc-500">候选价格优先 · 进度和对话辅助</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <BackendBadge status={backendStatus} />
          <button
            type="button"
            onClick={handleNewQuote}
            disabled={streamStatus === "running"}
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-white/80 px-3 py-2 text-sm font-semibold text-zinc-800 shadow-sm backdrop-blur transition hover:bg-white active:translate-y-px focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={16} />
            新报价
          </button>
        </div>
      </header>

      <main className="relative mx-auto grid max-w-[1500px] grid-cols-1 gap-4 px-4 pb-6 sm:px-6 lg:grid-cols-[380px_minmax(0,1fr)] lg:px-8">
        <aside className="space-y-4 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-32px)] lg:overflow-y-auto">
          <ChatInput onSend={handleSend} disabled={streamStatus === "running"} compact />

          <section className="grid grid-cols-3 gap-2 p-1">
            <MetricTile
              icon={Database}
              label="候选记录"
              value={String(metrics.candidates)}
              active={recordFilter === "all"}
              onClick={() => setRecordFilter("all")}
            />
            <MetricTile
              icon={ReceiptText}
              label="采购记录"
              value={String(metrics.purchase)}
              active={recordFilter === "purchase"}
              onClick={() => setRecordFilter("purchase")}
            />
            <MetricTile
              icon={Layers3}
              label="报价列表"
              value={String(metrics.quote)}
              active={recordFilter === "quote"}
              onClick={() => setRecordFilter("quote")}
            />
          </section>

          <ProgressIndicator />

          {streamStatus === "error" && (
            <section className="flex items-center gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <AlertCircle size={17} />
              <span>连接中断或后端返回错误。</span>
              <button
                type="button"
                onClick={handleRetry}
                className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-red-100 px-2 py-1 font-semibold text-red-800 transition hover:bg-red-200 active:translate-y-px"
              >
                <RefreshCw size={14} />
                重试
              </button>
            </section>
          )}
        </aside>

        <section className="min-h-[calc(100dvh-112px)] rounded-[1.75rem] border border-zinc-200 bg-white/78 p-4 shadow-[0_32px_120px_-70px_rgba(25,28,33,0.55)] backdrop-blur sm:p-5">
          <div className="mb-4 flex justify-end border-b border-zinc-200 pb-4">
            <div
              className={cn(
                "inline-flex w-fit rounded-lg px-3 py-2 text-sm font-semibold",
                streamStatus === "running"
                  ? "bg-teal-100 text-teal-800"
                  : streamStatus === "error"
                    ? "bg-red-100 text-red-700"
                    : "bg-zinc-100 text-zinc-700"
              )}
            >
              {streamStatus === "idle" ? "等待提交" : streamStatus === "running" ? "正在检索" : streamStatus === "done" ? "本轮结束" : "需要重试"}
            </div>
          </div>

          <QuoteExportPanel items={valuationItems} />
          <DatabaseRecords filter={recordFilter} />
        </section>
      </main>
    </div>
  );
}

function BackendBadge({ status }: { status: "checking" | "online" | "offline" }) {
  return (
    <div
      className={cn(
        "hidden items-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold backdrop-blur sm:flex",
        status === "online"
          ? "border-teal-200 bg-teal-50 text-teal-800"
          : status === "offline"
            ? "border-red-200 bg-red-50 text-red-700"
            : "border-zinc-200 bg-white/80 text-zinc-500"
      )}
    >
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          status === "online" ? "bg-teal-600" : status === "offline" ? "bg-red-500" : "bg-zinc-300"
        )}
      />
      {status === "online" ? "后端在线" : status === "offline" ? "后端离线" : "检测中"}
    </div>
  );
}

function MetricTile({
  icon: Icon,
  label,
  value,
  active = false,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-2xl border p-4 text-left shadow-sm backdrop-blur transition active:translate-y-px focus:outline-none focus:ring-2 focus:ring-teal-500",
        active ? "border-teal-300 bg-teal-50/90" : "border-zinc-200 bg-white/75 hover:bg-white"
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span className={cn("text-xs font-semibold", active ? "text-teal-800" : "text-zinc-500")}>{label}</span>
        <Icon size={16} className={active ? "text-teal-800" : "text-teal-700"} />
      </div>
      <div className="mt-3 font-mono text-2xl font-semibold tabular-nums text-zinc-950">{value}</div>
    </button>
  );
}
