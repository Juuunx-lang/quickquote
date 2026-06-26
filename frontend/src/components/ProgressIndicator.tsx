import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import { StageName } from "../api";
import { useChatStore } from "../store/useChatStore";
import { cn } from "../lib/utils";

const stageItems: Array<{ key: StageName; label: string; caption: string }> = [
  { key: "extract_stage", label: "材料解析", caption: "文本、图片与表格归一化" },
  { key: "multi_source_match_stage", label: "多源匹配", caption: "并行查询聚水潭、订单库与采购库" },
  { key: "purchase_route_stage", label: "采购路径", caption: "区分内采库存与外采历史" },
  { key: "result_stage", label: "结果生成", caption: "整理候选价格与追问上下文" },
];

export function ProgressIndicator() {
  const { streamStatus, stages, querySummary } = useChatStore();

  if (streamStatus === "idle") {
    return (
      <div className="rounded-2xl border border-zinc-200 bg-white/70 p-4">
        <div className="text-sm font-semibold text-zinc-900">工作流待命</div>
        <div className="mt-1 text-xs leading-5 text-zinc-500">提交材料后会显示每个后端节点的实时状态。</div>
      </div>
    );
  }

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white/85 p-4 shadow-[0_20px_60px_-48px_rgba(25,28,33,0.55)]">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-zinc-950">处理链路</h2>
          <p className="mt-1 text-xs text-zinc-500">
            {streamStatus === "running" ? "后端正在流式返回进度" : streamStatus === "done" ? "本轮报价已完成" : "本轮报价中断"}
          </p>
        </div>
        <span
          className={cn(
            "rounded-md px-2 py-1 text-xs font-semibold",
            streamStatus === "running"
              ? "bg-teal-100 text-teal-800"
              : streamStatus === "done"
                ? "bg-zinc-900 text-white"
                : "bg-red-100 text-red-700"
          )}
        >
          {streamStatus === "running" ? "运行中" : streamStatus === "done" ? "完成" : "异常"}
        </span>
      </div>

      <div className="space-y-3">
        {stageItems.map((item, index) => {
          const isDone = stages[item.key];
          const previousDone = index === 0 ? true : stages[stageItems[index - 1].key];
          const isActive = previousDone && !isDone && streamStatus === "running";

          return (
            <div key={item.key} className="grid grid-cols-[28px_1fr] gap-3">
              <div className="relative flex justify-center">
                {index < stageItems.length - 1 && <div className="absolute top-7 h-full w-px bg-zinc-200" />}
                <div
                  className={cn(
                    "relative z-[1] flex h-7 w-7 items-center justify-center rounded-full border bg-white",
                    isDone ? "border-teal-600 text-teal-700" : isActive ? "border-zinc-900 text-zinc-900" : "border-zinc-200 text-zinc-300"
                  )}
                >
                  {isDone ? <CheckCircle2 size={16} /> : isActive ? <Loader2 size={15} className="animate-spin" /> : <Circle size={13} />}
                </div>
              </div>
              <div className="pb-1">
                <div className={cn("text-sm font-semibold", isDone || isActive ? "text-zinc-950" : "text-zinc-400")}>
                  {item.label}
                </div>
                <div className="mt-0.5 text-xs leading-5 text-zinc-500">{item.caption}</div>
              </div>
            </div>
          );
        })}
      </div>

      {querySummary && (
        <div className="mt-4 rounded-xl border border-zinc-200 bg-zinc-50 p-3">
          <div className="mb-1 text-xs font-semibold tracking-[0.14em] text-zinc-500">SUMMARY</div>
          <pre className="whitespace-pre-wrap font-mono text-xs leading-5 text-zinc-700">{querySummary}</pre>
        </div>
      )}
    </section>
  );
}
