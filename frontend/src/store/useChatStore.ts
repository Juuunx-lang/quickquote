import { create } from "zustand";
import { ValuationItem } from "../api";

export type StreamStatus = "idle" | "running" | "done" | "error";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
}

export interface ChatState {
  streamStatus: StreamStatus;
  stages: {
    extract_stage: boolean;
    multi_source_match_stage: boolean;
    jushuitan_match_stage: boolean;
    purchase_route_stage: boolean;
    result_stage: boolean;
    parse: boolean;
    db_query: boolean;
    jushuitan_query: boolean;
    merge_results: boolean;
    reasoning: boolean;
    table: boolean;
    sql_query: boolean; // 保留 sql_query 以向后兼容
  };
  messages: Message[];
  contextId: string | null;
  querySummary: string | null;
  valuationItems: ValuationItem[] | null;
  extractFailedFallbackUsed: boolean;

  setStreamStatus: (status: StreamStatus) => void;
  setStage: (stage: keyof ChatState["stages"], done: boolean) => void;
  addMessage: (msg: Message) => void;
  updateMessage: (id: string, update: Partial<Message>) => void;
  appendStreamToMessage: (id: string, chunk: string) => void;
  setContextId: (id: string) => void;
  setQuerySummary: (summary: string) => void;
  setValuationItems: (items: ValuationItem[]) => void;
  setExtractFailedFallbackUsed: (used: boolean) => void;
  resetStream: () => void;
  resetAll: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  streamStatus: "idle",
  stages: {
    extract_stage: false,
    multi_source_match_stage: false,
    jushuitan_match_stage: false,
    purchase_route_stage: false,
    result_stage: false,
    parse: false,
    db_query: false,
    jushuitan_query: false,
    merge_results: false,
    reasoning: false,
    table: false,
    sql_query: false,
  },
  messages: [],
  contextId: null,
  querySummary: null,
  valuationItems: null,
  extractFailedFallbackUsed: false,

  setStreamStatus: (status) => set({ streamStatus: status }),
  setStage: (stage, done) =>
    set((state) => ({
      stages: {
        ...state.stages,
        [stage]: done,
      },
    })),
  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),
  updateMessage: (id, update) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...update } : m)),
    })),
  appendStreamToMessage: (id, chunk) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, content: m.content + chunk } : m
      ),
    })),
  setContextId: (id) => set({ contextId: id }),
  setQuerySummary: (summary) => set({ querySummary: summary }),
  setValuationItems: (items) => set({ valuationItems: items }),
  setExtractFailedFallbackUsed: (used) => set({ extractFailedFallbackUsed: used }),
  resetStream: () =>
    set({
      streamStatus: "idle",
      stages: {
        extract_stage: false,
        multi_source_match_stage: false,
        jushuitan_match_stage: false,
        purchase_route_stage: false,
        result_stage: false,
        parse: false,
        db_query: false,
        jushuitan_query: false,
        merge_results: false,
        reasoning: false,
        table: false,
        sql_query: false,
      },
      querySummary: null,
      valuationItems: null,
      extractFailedFallbackUsed: false,
    }),
  resetAll: () =>
    set({
      streamStatus: "idle",
      stages: {
        extract_stage: false,
        multi_source_match_stage: false,
        jushuitan_match_stage: false,
        purchase_route_stage: false,
        result_stage: false,
        parse: false,
        db_query: false,
        jushuitan_query: false,
        merge_results: false,
        reasoning: false,
        table: false,
        sql_query: false,
      },
      messages: [],
      contextId: null,
      querySummary: null,
      valuationItems: null,
      extractFailedFallbackUsed: false,
    }),
}));
