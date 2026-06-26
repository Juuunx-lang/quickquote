import { Bot, UserRound } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Message } from "../store/useChatStore";
import { cn } from "../lib/utils";

interface MessageItemProps {
  message: Message;
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === "user";

  return (
    <article className={cn("grid grid-cols-[34px_1fr] gap-3", isUser ? "items-start" : "items-start")}>
      <div
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded-lg",
          isUser ? "bg-zinc-900 text-white" : "border border-teal-200 bg-teal-50 text-teal-800"
        )}
      >
        {isUser ? <UserRound size={16} /> : <Bot size={16} />}
      </div>
      <div className={cn("min-w-0 rounded-2xl px-4 py-3", isUser ? "bg-zinc-100" : "border border-zinc-200 bg-white")}>
        <div className="mb-1 text-xs font-semibold tracking-[0.14em] text-zinc-500">
          {isUser ? "REQUEST" : "ASSISTANT"}
        </div>
        <div className="break-words text-sm leading-7 text-zinc-800">
          {isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <div className="prose prose-zinc prose-sm max-w-none prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-pre:my-3 prose-code:rounded prose-code:bg-zinc-100 prose-code:px-1 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || (message.isStreaming ? "正在整理结果" : "")}</ReactMarkdown>
            </div>
          )}
          {message.isStreaming && <span className="ml-1 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse bg-teal-600" />}
        </div>
      </div>
    </article>
  );
}
