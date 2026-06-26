import { Search, Package } from "lucide-react";
import { useChatStore } from "../store/useChatStore";

export function ExtractionResults() {
  const { valuationItems } = useChatStore();

  if (!valuationItems || valuationItems.length === 0) return null;

  return (
    <div className="mt-4 border border-blue-100 rounded-xl bg-white overflow-hidden shadow-sm">
      <div className="px-4 py-3 bg-blue-50/50 border-b border-blue-100 flex items-center gap-2">
        <Search size={16} className="text-blue-600" />
        <h3 className="text-sm font-semibold text-gray-800">已识别商品</h3>
      </div>

      <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        {valuationItems.map((item, idx) => (
          <div key={`${item.product_name}-${idx}`} className="p-3 bg-gray-50 rounded-lg border border-gray-100">
            <div className="flex items-center gap-2 mb-2">
              <Package size={14} className="text-gray-400" />
              <span className="text-xs font-bold text-gray-700">项目 #{idx + 1}</span>
            </div>
            <DetailRow label="商品名称" value={item.product_name} />
            <DetailRow label="型号规格" value={item.product_model} />
            <DetailRow label="匹配状态" value={item.query_status === "matched" ? "已匹配" : "未匹配"} />
          </div>
        ))}
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start text-xs mt-1.5">
      <span className="w-16 shrink-0 text-gray-500">{label}:</span>
      <span className="font-medium text-gray-800">{value || "未提供"}</span>
    </div>
  );
}
