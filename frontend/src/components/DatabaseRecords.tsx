import { useMemo, useState } from "react";
import {
  AlertCircle,
  Boxes,
  ChevronDown,
  ExternalLink,
  Layers3,
  Lock,
  PackageSearch,
  ReceiptText,
  TrendingUp,
  Warehouse,
} from "lucide-react";
import { Candidate, ValuationItem } from "../api";
import { useChatStore } from "../store/useChatStore";
import { cn } from "../lib/utils";

const EMPTY_TEXT = "无";

type RecordFilter = "all" | "purchase" | "quote";
type SourcePanelKey = "purchase" | "jushuitan" | "supplier";

interface DatabaseRecordsProps {
  filter: RecordFilter;
}

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return !Number.isNaN(value);
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function textOrEmpty(value: unknown): string {
  return hasValue(value) ? String(value) : EMPTY_TEXT;
}

function formatNumber(value: number | null | undefined): string {
  if (!hasValue(value)) return EMPTY_TEXT;
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatCurrency(value: number | null | undefined): string {
  if (!hasValue(value)) return EMPTY_TEXT;
  return `¥${Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function formatDate(value: string | null | undefined): string {
  if (!hasValue(value)) return EMPTY_TEXT;
  return String(value).slice(0, 10);
}

function isHttpUrl(value: string | null | undefined): boolean {
  return Boolean(value && /^https?:\/\//i.test(value.trim()));
}

function hasJushuitanSource(candidate: Candidate): boolean {
  return candidate.source?.includes("jushuitan") || candidate.matched_sources?.includes("jushuitan") || false;
}

function jushuitanCostPrice(candidate: Candidate): number | null | undefined {
  return hasJushuitanSource(candidate) ? candidate.cost_price : null;
}

function hasPurchaseSource(candidate: Candidate): boolean {
  return candidate.matched_sources?.includes("purchase_records") || hasJushuitanSource(candidate);
}

function hasSupplierQuoteData(candidate: Candidate): boolean {
  return [
    candidate.supplier_quote_supplier_name,
    candidate.supplier_quote_price,
    candidate.supplier_quote_updated_at,
    candidate.supplier_quote_item_code,
    candidate.supplier_quote_model,
    candidate.supplier_quote_factory_model,
  ].some(hasValue) || Boolean(candidate.supplier_quote_records?.length);
}

function matchesFilter(candidate: Candidate, filter: RecordFilter): boolean {
  if (filter === "all") return true;
  if (filter === "purchase") return hasPurchaseSource(candidate);
  return hasSupplierQuoteData(candidate);
}

function displayItems(items: ValuationItem[], filter: RecordFilter): ValuationItem[] {
  return items
    .map((item) => ({
      ...item,
      candidates: (item.candidates || []).filter((candidate) => matchesFilter(candidate, filter)),
    }))
    .filter((item) => item.candidates.length > 0);
}

export function DatabaseRecords({ filter }: DatabaseRecordsProps) {
  const { valuationItems, extractFailedFallbackUsed } = useChatStore();
  const [expanded, setExpanded] = useState<Record<number, boolean>>({ 0: true });

  const filteredItems = useMemo(() => displayItems(valuationItems || [], filter), [valuationItems, filter]);

  if (!valuationItems || valuationItems.length === 0) {
    return (
      <section className="rounded-2xl border border-zinc-200 bg-white/80 p-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-100 text-zinc-500">
            <PackageSearch size={20} />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-zinc-950">候选记录</h2>
            <p className="mt-1 text-xs text-zinc-500">无</p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      {extractFailedFallbackUsed && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <AlertCircle size={18} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">部分商品识别不完整</div>
            <div className="mt-1 text-xs leading-5 text-amber-800">后端已使用原始文本做兜底检索，结果需要人工复核。</div>
          </div>
        </div>
      )}

      {filteredItems.length === 0 ? (
        <div className="rounded-2xl border border-zinc-200 bg-white/90 px-4 py-10 text-center text-sm text-zinc-500">无</div>
      ) : (
        filteredItems.map((item, index) => {
          const isOpen = expanded[index] ?? index === 0;
          return (
            <article key={`${item.product_name || item.input_text || "item"}-${index}`} className="overflow-hidden rounded-2xl border border-zinc-200 bg-white/90 shadow-[0_24px_80px_-56px_rgba(25,28,33,0.45)]">
              <button
                type="button"
                onClick={() => setExpanded((current) => ({ ...current, [index]: !isOpen }))}
                className="grid w-full grid-cols-[1fr_auto] gap-3 px-4 py-4 text-left transition hover:bg-zinc-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-teal-500"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="min-w-0 break-words text-sm font-semibold text-zinc-950">{textOrEmpty(item.product_name || item.input_text)}</h3>
                    <span className="rounded-md bg-teal-100 px-2 py-0.5 text-xs font-semibold text-teal-800">
                      {item.candidates.length} 条
                    </span>
                  </div>
                  <div className="mt-1 font-mono text-xs text-zinc-500">{textOrEmpty(item.product_model)}</div>
                </div>
                <ChevronDown size={18} className={cn("mt-1 text-zinc-400 transition-transform", isOpen ? "rotate-180" : "")} />
              </button>

              {isOpen && (
                <div className="space-y-3 border-t border-zinc-100 bg-zinc-50/70 p-3">
                  {item.candidates.map((candidate, candidateIndex) => (
                    <CandidateCard key={`${candidate.sku_id || "sku"}-${candidateIndex}`} candidate={candidate} defaultOpen={candidateIndex === 0} />
                  ))}
                </div>
              )}
            </article>
          );
        })
      )}
    </section>
  );
}

function CandidateCard({ candidate, defaultOpen }: { candidate: Candidate; defaultOpen: boolean }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [costOpen, setCostOpen] = useState(false);
  const hasDynamicCostRecords = Boolean(candidate.dynamic_cost_records?.length);
  const latestCostValue = candidate.latest_dynamic_cost_price ?? jushuitanCostPrice(candidate);
  const latestCostDate = candidate.latest_dynamic_cost_date ?? candidate.modified;
  const latestCostDateLabel = candidate.latest_dynamic_cost_date ? "入库日期" : "资料修改时间";
  const hasPurchaseData = candidate.matched_sources?.includes("purchase_records") || [
    candidate.date,
    candidate.bill_quantity,
    candidate.final_purchase_price,
    candidate.selling_price,
    candidate.settlement_unit_price,
    candidate.settlement_amount,
    candidate.supplier_name,
    candidate.shop_name,
    candidate.product_link,
  ].some(hasValue);
  const hasJushuitanData = [
    candidate.stock_qty,
    latestCostValue,
    candidate.latest_dynamic_cost_date,
    candidate.latest_dynamic_cost_supplier,
    candidate.modified,
  ].some(hasValue) || hasDynamicCostRecords;
  const hasSupplierData = hasSupplierQuoteData(candidate);
  const firstAvailablePanel: SourcePanelKey | null = hasPurchaseData ? "purchase" : hasJushuitanData ? "jushuitan" : hasSupplierData ? "supplier" : null;
  const [openPanel, setOpenPanel] = useState<SourcePanelKey | null>(firstAvailablePanel);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm">
      <div className={cn("grid gap-3 md:grid-cols-[1fr_1fr_1fr_1fr_auto]", isOpen ? "border-b border-zinc-100 pb-3" : "")}>
        <BasicField label="产品名" value={candidate.product_name} />
        <BasicField label="品牌" value={candidate.brand} />
        <BasicField label="型号" value={candidate.sku_id || candidate.sku_code || candidate.product_code} mono />
        <BasicField label="规格" value={candidate.purchase_spec || candidate.purchase_model} />
        <button
          type="button"
          onClick={() => setIsOpen((value) => !value)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-500 transition hover:bg-zinc-50 focus:outline-none focus:ring-2 focus:ring-teal-500"
          aria-label={isOpen ? "收起候选详情" : "展开候选详情"}
        >
          <ChevronDown size={17} className={cn("transition", isOpen ? "rotate-180" : "")} />
        </button>
      </div>

      {isOpen && <div className="mt-4 space-y-2">
        <SourcePanel
          icon={ReceiptText}
          title="最新采购信息"
          hasContent={hasPurchaseData}
          isOpen={openPanel === "purchase"}
          onToggle={() => setOpenPanel((value) => (value === "purchase" ? null : "purchase"))}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <InfoRow label="日期" value={formatDate(candidate.date)} />
            <InfoRow label="数量" value={formatNumber(candidate.bill_quantity)} />
            <InfoRow label="采购价" value={formatCurrency(candidate.final_purchase_price)} strong={hasValue(candidate.final_purchase_price)} />
            <InfoRow label="售价" value={formatCurrency(candidate.selling_price)} />
            <InfoRow label="结算单价" value={formatCurrency(candidate.settlement_unit_price)} />
            <InfoRow label="结算金额" value={formatCurrency(candidate.settlement_amount)} />
            <InfoRow label="供应商" value={textOrEmpty(candidate.supplier_name)} />
            <InfoRow label="店铺名" value={textOrEmpty(candidate.shop_name)} />
          </div>
          <ExternalLinkMask productLink={candidate.product_link} />
        </SourcePanel>

        <SourcePanel
          icon={Warehouse}
          title="聚水潭来源"
          hasContent={hasJushuitanData}
          isOpen={openPanel === "jushuitan"}
          onToggle={() => setOpenPanel((value) => (value === "jushuitan" ? null : "jushuitan"))}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <InfoRow label="库存" value={formatNumber(candidate.stock_qty)} strong={hasValue(candidate.stock_qty) && Number(candidate.stock_qty) > 0} />
            <div className="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-2 text-sm">
              <span className="text-zinc-500">最新成本价</span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="group relative inline-flex">
                    <span className={cn("font-mono", hasValue(latestCostValue) ? "font-semibold text-zinc-950" : "text-zinc-700")}>
                      {formatCurrency(latestCostValue)}
                    </span>
                    {hasValue(latestCostValue) && hasValue(latestCostDate) && (
                      <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-max max-w-56 -translate-x-1/2 rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs font-medium text-zinc-600 shadow-lg group-hover:block">
                        {latestCostDateLabel}：{String(latestCostDate)}
                      </span>
                    )}
                  </span>
                  <span className="group relative inline-flex">
                    <button
                      type="button"
                      onClick={() => setCostOpen((value) => !value)}
                      disabled={!hasDynamicCostRecords}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-teal-500",
                        hasDynamicCostRecords
                          ? "border-teal-200 bg-teal-50 text-teal-800 hover:bg-teal-100"
                          : "cursor-not-allowed border-zinc-200 bg-zinc-100 text-zinc-400"
                      )}
                    >
                      <TrendingUp size={13} />
                      成本波动
                      <ChevronDown size={13} className={cn("transition", costOpen ? "rotate-180" : "")} />
                    </button>
                    {!hasDynamicCostRecords && (
                      <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-max max-w-48 -translate-x-1/2 rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs font-medium text-zinc-600 shadow-lg group-hover:block">
                        近30天无采购入库记录
                      </span>
                    )}
                  </span>
                </div>
              </div>
            </div>
          </div>
          {costOpen && <DynamicCostPanel candidate={candidate} />}
        </SourcePanel>

        <SourcePanel
          icon={Layers3}
          title="供应商报价"
          hasContent={hasSupplierData}
          isOpen={openPanel === "supplier"}
          onToggle={() => setOpenPanel((value) => (value === "supplier" ? null : "supplier"))}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <InfoRow label="供应商" value={textOrEmpty(candidate.supplier_quote_supplier_name)} />
            <InfoRow label="报价" value={formatCurrency(candidate.supplier_quote_price)} strong={hasValue(candidate.supplier_quote_price)} />
            <InfoRow label="更新时间" value={formatDate(candidate.supplier_quote_updated_at)} />
          </div>
        </SourcePanel>
      </div>}
    </div>
  );
}

function BasicField({ label, value, mono = false }: { label: string; value: unknown; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-xs font-semibold text-zinc-500">{label}</div>
      <div className={cn("break-words text-sm font-semibold text-zinc-950", mono ? "font-mono" : "")}>{textOrEmpty(value)}</div>
    </div>
  );
}

function SectionTitle({ icon: Icon, title }: { icon: typeof Warehouse; title: string }) {
  return (
    <div className="flex items-center gap-2 text-sm font-semibold text-zinc-950">
      <Icon size={15} className="text-teal-700" />
      {title}
    </div>
  );
}

function SourcePanel({
  icon: Icon,
  title,
  hasContent,
  isOpen,
  onToggle,
  children,
}: {
  icon: typeof Warehouse;
  title: string;
  hasContent: boolean;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("rounded-lg border bg-zinc-50", hasContent ? "border-zinc-200" : "border-zinc-100 text-zinc-400")}>
      <button
        type="button"
        onClick={hasContent ? onToggle : undefined}
        disabled={!hasContent}
        className={cn(
          "grid w-full grid-cols-[1fr_auto] items-center gap-3 px-3 py-3 text-left",
          hasContent ? "cursor-pointer hover:bg-zinc-100 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-teal-500" : "cursor-default"
        )}
      >
        <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-zinc-950">
          <Icon size={15} className={hasContent ? "text-teal-700" : "text-zinc-400"} />
          <span>{title}</span>
        </div>
        {hasContent ? (
          <ChevronDown size={16} className={cn("text-zinc-400 transition", isOpen ? "rotate-180" : "")} />
        ) : (
          <span className="text-sm text-zinc-400">无</span>
        )}
      </button>
      {hasContent && isOpen && <div className="border-t border-zinc-200 px-3 py-3">{children}</div>}
    </section>
  );
}

function InfoRow({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-2 text-sm">
      <span className="text-zinc-500">{label}</span>
      <span className={cn("min-w-0 break-words font-mono", strong ? "font-semibold text-zinc-950" : "text-zinc-700")}>{value}</span>
    </div>
  );
}

function ExternalLinkMask({ productLink }: { productLink?: string | null }) {
  return (
    <div className="mt-3 rounded-lg border border-dashed border-zinc-300 bg-white/70 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold text-zinc-600">
        <Lock size={13} />
        外购链接自动拉取
      </div>
      <div className="mt-2 flex items-center gap-2 text-xs text-zinc-500">
        <Boxes size={13} />
        <span className="min-w-0 break-words">{isHttpUrl(productLink) ? "已存在链接，后续自动接入" : "预留接入位置"}</span>
      </div>
      {isHttpUrl(productLink) && (
        <a
          href={productLink || ""}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-teal-700 hover:text-teal-900"
        >
          打开链接 <ExternalLink size={12} />
        </a>
      )}
    </div>
  );
}

function DynamicCostPanel({ candidate }: { candidate: Candidate }) {
  const records = candidate.dynamic_cost_records || [];
  if (!records.length) return null;

  return (
    <div className="mt-3 space-y-2 rounded-lg border border-zinc-200 bg-white p-2">
      {records.slice(0, 8).map((record, index) => (
        <div key={`${record.io_id || record.po_id || record.io_date}-${index}`} className="border-b border-zinc-100 pb-2 last:border-0 last:pb-0">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-xs font-semibold text-zinc-950">{formatCurrency(record.cost_price)}</span>
            <span className="text-xs text-zinc-500">{formatDate(record.io_date)}</span>
          </div>
          <div className="mt-1 text-xs text-zinc-600">{textOrEmpty(record.supplier_name)}</div>
          <div className="mt-1 font-mono text-[11px] text-zinc-500">
            数量 {formatNumber(record.qty)} · 入库单 {textOrEmpty(record.io_id)}
          </div>
        </div>
      ))}
    </div>
  );
}
