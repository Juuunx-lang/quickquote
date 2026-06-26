import React, { DragEvent, useRef, useState } from "react";
import {
  FileSpreadsheet,
  FileText,
  Image as ImageIcon,
  Loader2,
  Paperclip,
  Search,
  Send,
  UploadCloud,
  X,
} from "lucide-react";
import { parseExcelToItems } from "../lib/excelParser";
import { cn } from "../lib/utils";

function stripExcelRowsFromText(text: string, excelRows: string[]): string {
  if (excelRows.length === 0) return text.trim();

  const parsedRows = new Set(excelRows.map((row) => row.trim()).filter(Boolean));
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !parsedRows.has(line))
    .join("\n")
    .trim();
}

function getFileIcon(fileName: string) {
  const normalized = fileName.toLowerCase();
  if (/\.(xlsx|xls)$/i.test(normalized)) return FileSpreadsheet;
  if (/\.(jpg|jpeg|png|webp)$/i.test(normalized)) return ImageIcon;
  return FileText;
}

interface ChatInputProps {
  onSend: (text: string, files: File[], excelRows: string[], enableFuzzyCodeMatch: boolean) => void;
  disabled?: boolean;
  compact?: boolean;
}

export function ChatInput({ onSend, disabled, compact = false }: ChatInputProps) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [excelRows, setExcelRows] = useState<string[]>([]);
  const [enableFuzzyCodeMatch, setEnableFuzzyCodeMatch] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const hasContent = text.trim().length > 0 || files.length > 0 || excelRows.length > 0;

  const submit = () => {
    const outgoingText = stripExcelRowsFromText(text, excelRows);
    if (!outgoingText && files.length === 0 && excelRows.length === 0) return;

    onSend(outgoingText, files, excelRows, enableFuzzyCodeMatch);
    setText("");
    setFiles([]);
    setExcelRows([]);
    setEnableFuzzyCodeMatch(false);
  };

  const processFiles = async (incomingFiles: File[]) => {
    if (incomingFiles.length === 0) return;
    setFiles((prev) => [...prev, ...incomingFiles]);

    const excelFiles = incomingFiles.filter((file) => /\.(xlsx|xls)$/i.test(file.name));
    if (excelFiles.length === 0) return;

    setIsParsing(true);
    try {
      const parsedGroups = await Promise.all(
        excelFiles.map(async (file) => {
          try {
            return await parseExcelToItems(file);
          } catch (error) {
            console.error(`Excel parse failed: ${file.name}`, error);
            return [];
          }
        })
      );

      const parsedItems = Array.from(new Set(parsedGroups.flat().map((item) => item.trim()).filter(Boolean)));
      if (parsedItems.length > 0) {
        setExcelRows((prev) => Array.from(new Set([...prev, ...parsedItems])));
        setText(parsedItems.join("\n"));
      }
    } finally {
      setIsParsing(false);
    }
  };

  const removeFile = (index: number) => {
    setFiles((prev) => {
      const removed = prev[index];
      const next = prev.filter((_, i) => i !== index);
      const removedExcel = removed && /\.(xlsx|xls)$/i.test(removed.name);
      const hasExcelLeft = next.some((file) => /\.(xlsx|xls)$/i.test(file.name));

      if (removedExcel && !hasExcelLeft) {
        setExcelRows([]);
        setText((current) => stripExcelRowsFromText(current, excelRows));
      }

      return next;
    });
  };

  const onDrop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    await processFiles(Array.from(event.dataTransfer.files || []));
  };

  return (
    <section
      className={cn(
        "quote-composer relative overflow-hidden border border-zinc-200 bg-white shadow-[0_28px_90px_-60px_rgba(25,28,33,0.55)]",
        compact ? "rounded-2xl p-3" : "rounded-[1.75rem] p-4 sm:p-5"
      )}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        accept=".txt,.pdf,.xlsx,.xls,.jpg,.jpeg,.png,.webp"
        onChange={async (event) => {
          await processFiles(Array.from(event.target.files || []));
          if (fileInputRef.current) fileInputRef.current.value = "";
        }}
      />

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setIsDragging(false);
        }}
        onDrop={onDrop}
        className={cn(
          "rounded-[1.25rem] border border-dashed p-3 transition duration-300",
          isDragging ? "border-teal-500 bg-teal-50/70" : "border-zinc-200 bg-zinc-50/70",
          disabled ? "pointer-events-none opacity-60" : ""
        )}
      >
        <label className="mb-2 block text-xs font-semibold tracking-[0.16em] text-zinc-500">
          报价材料
        </label>
        <textarea
          value={text}
          disabled={disabled || isParsing}
          rows={compact ? 3 : 8}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={isParsing ? "正在读取表格内容" : "输入商品名称、型号、规格、数量，或拖入图片、PDF、Excel"}
          className="min-h-[120px] w-full resize-none bg-transparent text-[15px] leading-7 text-zinc-900 outline-none placeholder:text-zinc-400"
        />

        {excelRows.length > 0 && (
          <div className="mt-3 border-t border-zinc-200 pt-3 text-xs text-zinc-500">
            已从表格识别 {excelRows.length} 条商品行
          </div>
        )}
      </div>

      {files.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {files.map((file, index) => {
            const Icon = getFileIcon(file.name);
            return (
              <div
                key={`${file.name}-${index}`}
                className="group flex max-w-full items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-2 text-xs text-zinc-700"
              >
                <Icon size={15} className="shrink-0 text-teal-700" />
                <span className="max-w-[180px] truncate">{file.name}</span>
                <button
                  type="button"
                  onClick={() => removeFile(index)}
                  className="rounded-md p-0.5 text-zinc-400 transition hover:bg-zinc-200 hover:text-zinc-800 focus:outline-none focus:ring-2 focus:ring-teal-500"
                  aria-label={`移除 ${file.name}`}
                >
                  <X size={14} />
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || isParsing}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-zinc-200 bg-white px-3.5 py-2.5 text-sm font-medium text-zinc-700 transition hover:border-zinc-300 hover:bg-zinc-50 active:translate-y-px focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Paperclip size={17} />
            选择文件
          </button>
          <button
            type="button"
            role="switch"
            aria-checked={enableFuzzyCodeMatch}
            onClick={() => setEnableFuzzyCodeMatch((value) => !value)}
            disabled={disabled || isParsing}
            className={cn(
              "inline-flex items-center justify-center gap-2 rounded-xl border px-3.5 py-2.5 text-sm font-medium transition active:translate-y-px focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:cursor-not-allowed disabled:opacity-50",
              enableFuzzyCodeMatch
                ? "border-teal-600 bg-teal-50 text-teal-800"
                : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50"
            )}
          >
            <Search size={17} />
            编码模糊
          </button>
        </div>

        <div className="flex items-center gap-2">
          <div className="hidden items-center gap-1.5 text-xs text-zinc-500 sm:flex">
            <UploadCloud size={15} />
            Ctrl / Cmd + Enter 提交
          </div>
          <button
            type="button"
            onClick={submit}
            disabled={disabled || isParsing || !hasContent}
            className={cn(
              "inline-flex min-w-[116px] items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition active:translate-y-px focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2",
              disabled || isParsing || !hasContent
                ? "cursor-not-allowed bg-zinc-200 text-zinc-500"
                : "bg-zinc-950 text-white hover:bg-zinc-800"
            )}
          >
            {isParsing ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
            提交报价
          </button>
        </div>
      </div>
    </section>
  );
}
