import { useEffect, useMemo, useState } from "react";
import { CheckSquare, ChevronDown, Download, FileSpreadsheet, Square } from "lucide-react";
import * as XLSX from "xlsx";
import { Candidate, ValuationItem } from "../api";
import { cn } from "../lib/utils";

type ExportField = {
  key: string;
  label: string;
  group: string;
  getValue: (item: ValuationItem, candidate: Candidate, itemIndex: number, candidateIndex: number) => unknown;
};

const EMPTY_TEXT = "无";

const EXPORT_FIELDS: ExportField[] = [
  { key: "source_item", label: "候选记录", group: "基本字段", getValue: (item) => item.product_name || item.input_text },
  { key: "source_model", label: "需求型号", group: "基本字段", getValue: (item) => item.product_model },
  { key: "product_name", label: "产品名", group: "基本字段", getValue: (_, candidate) => candidate.product_name },
  { key: "brand", label: "品牌", group: "基本字段", getValue: (_, candidate) => candidate.brand },
  { key: "sku_id", label: "型号（sku_id）", group: "基本字段", getValue: (_, candidate) => candidate.sku_id || candidate.sku_code || candidate.product_code },
  { key: "purchase_spec", label: "规格", group: "基本字段", getValue: (_, candidate) => candidate.purchase_spec || candidate.purchase_model },
  { key: "matched_sources", label: "匹配来源", group: "基本字段", getValue: (_, candidate) => (candidate.matched_sources || []).join("、") || candidate.source },
  { key: "match_score", label: "匹配分", group: "基本字段", getValue: (_, candidate) => candidate.match_score },

  { key: "purchase_date", label: "采购日期", group: "采购历史记录", getValue: (_, candidate) => candidate.date },
  { key: "bill_quantity", label: "数量", group: "采购历史记录", getValue: (_, candidate) => candidate.bill_quantity },
  { key: "final_purchase_price", label: "采购价", group: "采购历史记录", getValue: (_, candidate) => candidate.final_purchase_price },
  { key: "selling_price", label: "售价", group: "采购历史记录", getValue: (_, candidate) => candidate.selling_price },
  { key: "settlement_unit_price", label: "结算单价", group: "采购历史记录", getValue: (_, candidate) => candidate.settlement_unit_price },
  { key: "settlement_amount", label: "结算金额", group: "采购历史记录", getValue: (_, candidate) => candidate.settlement_amount },
  { key: "purchase_supplier", label: "采购供应商", group: "采购历史记录", getValue: (_, candidate) => candidate.supplier_name },
  { key: "shop_name", label: "店铺名", group: "采购历史记录", getValue: (_, candidate) => candidate.shop_name },
  { key: "order_no", label: "订单号", group: "采购历史记录", getValue: (_, candidate) => candidate.order_no },
  { key: "tax_included", label: "是否含税", group: "采购历史记录", getValue: (_, candidate) => candidate.tax_included },
  { key: "invoice_type", label: "发票类型", group: "采购历史记录", getValue: (_, candidate) => candidate.invoice_type },
  { key: "tax_rate", label: "税率", group: "采购历史记录", getValue: (_, candidate) => candidate.tax_rate },
  { key: "product_link", label: "商品链接", group: "采购历史记录", getValue: (_, candidate) => candidate.product_link },

  { key: "stock_qty", label: "库存", group: "聚水潭来源", getValue: (_, candidate) => candidate.stock_qty },
  { key: "cost_price", label: "最新成本价", group: "聚水潭来源", getValue: (_, candidate) => candidate.latest_dynamic_cost_price ?? candidate.cost_price },
  { key: "latest_cost_date", label: "成本价日期", group: "聚水潭来源", getValue: (_, candidate) => candidate.latest_dynamic_cost_date ?? candidate.modified },
  { key: "latest_cost_supplier", label: "成本价供应商", group: "聚水潭来源", getValue: (_, candidate) => candidate.latest_dynamic_cost_supplier },
  { key: "jushuitan_supplier", label: "聚水潭供应商", group: "聚水潭来源", getValue: (_, candidate) => candidate.jushuitan_supplier_name },
  { key: "modified", label: "资料修改时间", group: "聚水潭来源", getValue: (_, candidate) => candidate.modified },

  { key: "supplier_quote_supplier_name", label: "报价供应商", group: "供应商报价", getValue: (_, candidate) => candidate.supplier_quote_supplier_name },
  { key: "supplier_quote_price", label: "报价", group: "供应商报价", getValue: (_, candidate) => candidate.supplier_quote_price },
  { key: "supplier_quote_updated_at", label: "报价更新时间", group: "供应商报价", getValue: (_, candidate) => candidate.supplier_quote_updated_at },
  { key: "supplier_quote_item_code", label: "报价表商品编码", group: "供应商报价", getValue: (_, candidate) => candidate.supplier_quote_item_code },
  { key: "supplier_quote_model", label: "报价表型号", group: "供应商报价", getValue: (_, candidate) => candidate.supplier_quote_model },
  { key: "supplier_quote_factory_model", label: "报价表厂商型号", group: "供应商报价", getValue: (_, candidate) => candidate.supplier_quote_factory_model },
];

const DEFAULT_FIELD_KEYS = new Set([
  "source_item",
  "product_name",
  "brand",
  "sku_id",
  "purchase_spec",
  "purchase_date",
  "bill_quantity",
  "final_purchase_price",
  "selling_price",
  "settlement_unit_price",
  "settlement_amount",
  "purchase_supplier",
  "shop_name",
  "stock_qty",
  "cost_price",
  "latest_cost_date",
  "supplier_quote_supplier_name",
  "supplier_quote_price",
  "supplier_quote_updated_at",
]);

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return !Number.isNaN(value);
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function cellValue(value: unknown): unknown {
  if (!hasValue(value)) return EMPTY_TEXT;
  if (Array.isArray(value)) return value.join("、");
  return value;
}

function candidateKey(itemIndex: number, candidateIndex: number): string {
  return `${itemIndex}:${candidateIndex}`;
}

function buildInitialSelection(items: ValuationItem[]): Set<string> {
  const keys = new Set<string>();
  items.forEach((item, itemIndex) => {
    (item.candidates || []).forEach((_, candidateIndex) => keys.add(candidateKey(itemIndex, candidateIndex)));
  });
  return keys;
}

function safeFileTimestamp(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
}

export function QuoteExportPanel({ items }: { items: ValuationItem[] | null }) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedCandidates, setSelectedCandidates] = useState<Set<string>>(() => buildInitialSelection(items || []));
  const [selectedFields, setSelectedFields] = useState<Set<string>>(() => new Set(DEFAULT_FIELD_KEYS));

  const candidateCount = useMemo(() => (items || []).reduce((total, item) => total + (item.candidates || []).length, 0), [items]);
  const selectedCandidateCount = selectedCandidates.size;
  const selectedFieldCount = selectedFields.size;

  useEffect(() => {
    setSelectedCandidates(buildInitialSelection(items || []));
  }, [items]);

  if (!items || items.length === 0 || candidateCount === 0) return null;

  const toggleCandidate = (key: string) => {
    setSelectedCandidates((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleItem = (itemIndex: number) => {
    const keys = (items[itemIndex]?.candidates || []).map((_, candidateIndex) => candidateKey(itemIndex, candidateIndex));
    const allSelected = keys.length > 0 && keys.every((key) => selectedCandidates.has(key));
    setSelectedCandidates((current) => {
      const next = new Set(current);
      keys.forEach((key) => {
        if (allSelected) next.delete(key);
        else next.add(key);
      });
      return next;
    });
  };

  const toggleField = (key: string) => {
    setSelectedFields((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleFieldGroup = (group: string) => {
    const keys = EXPORT_FIELDS.filter((field) => field.group === group).map((field) => field.key);
    const allSelected = keys.every((key) => selectedFields.has(key));
    setSelectedFields((current) => {
      const next = new Set(current);
      keys.forEach((key) => {
        if (allSelected) next.delete(key);
        else next.add(key);
      });
      return next;
    });
  };

  const selectAllCandidates = () => setSelectedCandidates(buildInitialSelection(items));
  const clearCandidates = () => setSelectedCandidates(new Set());
  const selectDefaultFields = () => setSelectedFields(new Set(DEFAULT_FIELD_KEYS));
  const selectAllFields = () => setSelectedFields(new Set(EXPORT_FIELDS.map((field) => field.key)));

  const exportExcel = () => {
    const fields = EXPORT_FIELDS.filter((field) => selectedFields.has(field.key));
    const rows: Record<string, unknown>[] = [];

    items.forEach((item, itemIndex) => {
      (item.candidates || []).forEach((candidate, candidateIndex) => {
        if (!selectedCandidates.has(candidateKey(itemIndex, candidateIndex))) return;
        const row: Record<string, unknown> = {};
        fields.forEach((field) => {
          row[field.label] = cellValue(field.getValue(item, candidate, itemIndex, candidateIndex));
        });
        rows.push(row);
      });
    });

    if (rows.length === 0 || fields.length === 0) return;

    const worksheet = XLSX.utils.json_to_sheet(rows, { header: fields.map((field) => field.label) });
    worksheet["!cols"] = fields.map((field) => ({ wch: Math.max(12, Math.min(32, field.label.length + 8)) }));
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "报价候选记录");
    XLSX.writeFile(workbook, `QuickQuote报价_${safeFileTimestamp()}.xlsx`);
  };

  const fieldGroups = Array.from(new Set(EXPORT_FIELDS.map((field) => field.group)));
  const canExport = selectedCandidateCount > 0 && selectedFieldCount > 0;

  return (
    <section className="mb-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white/90 shadow-sm">
      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        className="grid w-full grid-cols-[1fr_auto] items-center gap-3 px-4 py-3 text-left transition hover:bg-zinc-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-teal-500"
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-teal-50 text-teal-800">
            <FileSpreadsheet size={20} />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-zinc-950">Excel 导出</div>
            <div className="mt-1 text-xs text-zinc-500">
              已选 {selectedCandidateCount} / {candidateCount} 个产品，{selectedFieldCount} 个字段
            </div>
          </div>
        </div>
        <ChevronDown size={18} className={cn("text-zinc-400 transition", isOpen ? "rotate-180" : "")} />
      </button>

      {isOpen && (
        <div className="space-y-4 border-t border-zinc-100 bg-zinc-50/70 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              <SmallButton onClick={selectAllCandidates}>全选产品</SmallButton>
              <SmallButton onClick={clearCandidates}>清空产品</SmallButton>
              <SmallButton onClick={selectDefaultFields}>默认字段</SmallButton>
              <SmallButton onClick={selectAllFields}>全选字段</SmallButton>
            </div>
            <button
              type="button"
              onClick={exportExcel}
              disabled={!canExport}
              className="inline-flex items-center gap-2 rounded-xl bg-zinc-950 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-zinc-800 active:translate-y-px focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:cursor-not-allowed disabled:bg-zinc-300"
            >
              <Download size={16} />
              导出 Excel
            </button>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
            <div className="rounded-xl border border-zinc-200 bg-white p-3">
              <div className="mb-3 text-sm font-semibold text-zinc-950">候选记录与具体产品</div>
              <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
                {items.map((item, itemIndex) => {
                  const keys = (item.candidates || []).map((_, candidateIndex) => candidateKey(itemIndex, candidateIndex));
                  const checkedCount = keys.filter((key) => selectedCandidates.has(key)).length;
                  const allSelected = keys.length > 0 && checkedCount === keys.length;
                  return (
                    <div key={`${item.product_name || item.input_text || "item"}-${itemIndex}`} className="rounded-lg border border-zinc-100 bg-zinc-50 p-3">
                      <button
                        type="button"
                        onClick={() => toggleItem(itemIndex)}
                        className="flex w-full items-start gap-2 text-left focus:outline-none focus:ring-2 focus:ring-teal-500"
                      >
                        <SelectionIcon checked={allSelected} partial={!allSelected && checkedCount > 0} />
                        <div className="min-w-0">
                          <div className="break-words text-sm font-semibold text-zinc-950">{item.product_name || item.input_text || EMPTY_TEXT}</div>
                          <div className="mt-1 text-xs text-zinc-500">{checkedCount} / {keys.length} 个产品已选</div>
                        </div>
                      </button>
                      <div className="mt-3 space-y-2 pl-6">
                        {(item.candidates || []).map((candidate, candidateIndex) => {
                          const key = candidateKey(itemIndex, candidateIndex);
                          const checked = selectedCandidates.has(key);
                          return (
                            <button
                              key={`${candidate.sku_id || candidate.product_name || "candidate"}-${candidateIndex}`}
                              type="button"
                              onClick={() => toggleCandidate(key)}
                              className="grid w-full grid-cols-[auto_1fr] gap-2 rounded-lg px-2 py-2 text-left transition hover:bg-white focus:outline-none focus:ring-2 focus:ring-teal-500"
                            >
                              <SelectionIcon checked={checked} />
                              <div className="min-w-0">
                                <div className="break-words text-sm font-medium text-zinc-900">{candidate.product_name || EMPTY_TEXT}</div>
                                <div className="mt-1 break-words font-mono text-xs text-zinc-500">
                                  {candidate.sku_id || candidate.sku_code || candidate.product_code || EMPTY_TEXT}
                                </div>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="rounded-xl border border-zinc-200 bg-white p-3">
              <div className="mb-3 text-sm font-semibold text-zinc-950">导出字段</div>
              <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
                {fieldGroups.map((group) => {
                  const fields = EXPORT_FIELDS.filter((field) => field.group === group);
                  const checkedCount = fields.filter((field) => selectedFields.has(field.key)).length;
                  const allSelected = checkedCount === fields.length;
                  return (
                    <div key={group} className="rounded-lg border border-zinc-100 bg-zinc-50 p-3">
                      <button
                        type="button"
                        onClick={() => toggleFieldGroup(group)}
                        className="flex w-full items-center gap-2 text-left focus:outline-none focus:ring-2 focus:ring-teal-500"
                      >
                        <SelectionIcon checked={allSelected} partial={!allSelected && checkedCount > 0} />
                        <span className="text-sm font-semibold text-zinc-950">{group}</span>
                      </button>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        {fields.map((field) => {
                          const checked = selectedFields.has(field.key);
                          return (
                            <button
                              key={field.key}
                              type="button"
                              onClick={() => toggleField(field.key)}
                              className="flex items-start gap-2 rounded-lg px-2 py-2 text-left transition hover:bg-white focus:outline-none focus:ring-2 focus:ring-teal-500"
                            >
                              <SelectionIcon checked={checked} />
                              <span className="break-words text-sm text-zinc-800">{field.label}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function SmallButton({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs font-semibold text-zinc-700 transition hover:bg-zinc-50 active:translate-y-px focus:outline-none focus:ring-2 focus:ring-teal-500"
    >
      {children}
    </button>
  );
}

function SelectionIcon({ checked, partial = false }: { checked: boolean; partial?: boolean }) {
  if (checked) return <CheckSquare size={16} className="mt-0.5 shrink-0 text-teal-700" />;
  if (partial) return <CheckSquare size={16} className="mt-0.5 shrink-0 text-amber-600 opacity-80" />;
  return <Square size={16} className="mt-0.5 shrink-0 text-zinc-400" />;
}
