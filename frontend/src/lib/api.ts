import axios, { type AxiosInstance } from "axios";
import type {
  AIObserverFeedItem,
  AIObserverSummary,
  ConfigAuditResp,
  ConfigItemResp,
  ConfigMetaResp,
  ConfigPatchReq,
  ConfigPatchResp,
  ConfigPreviewResp,
  ConfigResetResp,
  ConfigSnapshotResp,
  ConfigValue,
  DashboardSnapshot,
  LogsMeta,
  LogsQueryResp,
  LogsSummary,
  Subscription,
  SystemHealth,
} from "./types";

const baseURL = (import.meta as ImportMeta & { env: { VITE_API_BASE?: string } })
  .env.VITE_API_BASE ?? "";

const http: AxiosInstance = axios.create({
  baseURL,
  timeout: 15_000,
});

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const detail = err?.response?.data?.detail ?? err?.message ?? "网络异常";
    err.friendly = typeof detail === "string" ? detail : JSON.stringify(detail);
    return Promise.reject(err);
  },
);

// ─── Dashboard ───────────────────────────────────

export async function fetchDashboard(params: {
  symbol?: string;
  tf?: string;
}): Promise<DashboardSnapshot> {
  const r = await http.get<DashboardSnapshot>("/api/dashboard", { params });
  return r.data;
}

// ─── Subscriptions ───────────────────────────────

export async function listSubscriptions(): Promise<Subscription[]> {
  const r = await http.get<Subscription[]>("/api/subscriptions");
  return r.data;
}

export async function createSubscription(
  symbol: string,
  active: boolean | null = true,
): Promise<Subscription> {
  const r = await http.post<Subscription>("/api/subscriptions", { symbol, active });
  return r.data;
}

export async function updateSubscription(
  symbol: string,
  patch: { active?: boolean; display_order?: number },
): Promise<Subscription> {
  const r = await http.patch<Subscription>(
    `/api/subscriptions/${encodeURIComponent(symbol)}`,
    patch,
  );
  return r.data;
}

export async function deleteSubscription(symbol: string): Promise<void> {
  await http.delete(`/api/subscriptions/${encodeURIComponent(symbol)}`);
}

// ─── System ──────────────────────────────────────

export async function fetchSystemHealth(): Promise<SystemHealth> {
  const r = await http.get<SystemHealth>("/api/system/health");
  return r.data;
}

// ─── Logs ────────────────────────────────────────

export interface LogsQueryParams {
  levels?: string[];
  loggers?: string[];
  keyword?: string;
  symbol?: string;
  from_ts?: string;
  to_ts?: string;
  limit?: number;
  offset?: number;
}

export async function queryLogs(params: LogsQueryParams): Promise<LogsQueryResp> {
  const r = await http.get<LogsQueryResp>("/api/logs", {
    params,
    paramsSerializer: { indexes: null },
  });
  return r.data;
}

export async function fetchLogsSummary(): Promise<LogsSummary> {
  const r = await http.get<LogsSummary>("/api/logs/summary");
  return r.data;
}

export async function fetchLogsMeta(): Promise<LogsMeta> {
  const r = await http.get<LogsMeta>("/api/logs/meta");
  return r.data;
}

// ─── Config ──────────────────────────────────────

export async function fetchConfigMeta(): Promise<ConfigMetaResp> {
  const r = await http.get<ConfigMetaResp>("/api/config/meta");
  return r.data;
}

export async function fetchConfigSnapshot(): Promise<ConfigSnapshotResp> {
  const r = await http.get<ConfigSnapshotResp>("/api/config");
  return r.data;
}

export async function fetchConfigItem(key: string): Promise<ConfigItemResp> {
  const r = await http.get<ConfigItemResp>(
    `/api/config/item/${encodeURIComponent(key)}`,
  );
  return r.data;
}

export async function patchConfig(body: ConfigPatchReq): Promise<ConfigPatchResp> {
  const r = await http.patch<ConfigPatchResp>("/api/config", body);
  return r.data;
}

export async function previewConfig(
  overrides: Record<string, ConfigValue>,
): Promise<ConfigPreviewResp> {
  const r = await http.post<ConfigPreviewResp>("/api/config/preview", {
    overrides,
  });
  return r.data;
}

export async function resetConfig(body: {
  key?: string | null;
  updated_by?: string;
  reason?: string;
}): Promise<ConfigResetResp> {
  const r = await http.post<ConfigResetResp>("/api/config/reset", body);
  return r.data;
}

export async function fetchConfigAudit(params: {
  key?: string;
  limit?: number;
}): Promise<ConfigAuditResp> {
  const r = await http.get<ConfigAuditResp>("/api/config/audit", { params });
  return r.data;
}

// ─── V1.1 · Phase 9 · AI 观察 ────────────────────

export interface AIStatusResp {
  config: {
    enabled: boolean;
    provider: string;
    api_key: string; // mask
    base_url: string;
    // V1.1 · 统一模型 + 思维模式开关
    model_tier: "flash" | "pro";
    thinking_enabled: boolean;
    flash_model: string;
    pro_model: string;
    proxy: string;
    min_interval_seconds: number;
    cache_ttl_seconds: number;
    auto_trade_plan: boolean;
    auto_trend_confidence: number;
    auto_money_flow_confidence: number;
    timeout_s_flash: number;
    timeout_s_pro: number;
    history_ring_size: number;
    jsonl_relpath: string;
  };
  provider_kind: string;
  history_size: number;
  has_latest: boolean;
  latest_ts: number | null;
  latest_anchor_ts: number | null;
}

export async function fetchAIStatus(): Promise<AIStatusResp> {
  const r = await http.get<AIStatusResp>("/api/ai/status");
  return r.data;
}

export interface AITestResp {
  ok: boolean;
  reason?: string;
  provider: string;
  flash_model?: string;
  pro_model?: string;
  base_url?: string;
  error?: string | null;
}

export async function testAIConnection(): Promise<AITestResp> {
  const r = await http.post<AITestResp>("/api/ai/test");
  return r.data;
}

export interface AIObservationsListResp {
  items: AIObserverFeedItem[];
  size: number;
  limit: number;
}

export async function fetchAIObservations(
  limit = 20,
): Promise<AIObservationsListResp> {
  const r = await http.get<AIObservationsListResp>("/api/ai/observations", {
    params: { limit },
  });
  return r.data;
}

export interface AIObservationsRunReq {
  symbol?: string;
  tf?: string;
  force_trade_plan?: boolean;
}

export interface AIObservationsRunResp {
  item: AIObserverFeedItem;
  summary: AIObserverSummary;
}

export async function runAIObservation(
  body: AIObservationsRunReq,
): Promise<AIObservationsRunResp> {
  const r = await http.post<AIObservationsRunResp>(
    "/api/ai/observations/run",
    body,
    { timeout: 60_000 }, // 手动触发，允许 60s（Pro 模型较慢）
  );
  return r.data;
}

// ─── Indicators 全景 ──────────────────────────────

/**
 * 指标全景：直接返回 ``FeatureSnapshot.model_dump()``，体积较大。
 * 前端用 ``Record<string, unknown>`` 接住，按分类映射表渲染。
 */
export type IndicatorsPanorama = Record<string, unknown>;

export async function fetchIndicatorsPanorama(
  symbol: string,
  tf: string,
): Promise<IndicatorsPanorama> {
  const r = await http.get<IndicatorsPanorama>("/api/indicators", {
    params: { symbol, tf },
  });
  return r.data;
}

// ─── AI 深度分析报告 ──────────────────────────────

export interface AIRawPayload {
  layer: string;            // "trend" | "money_flow" | "trade_plan" | "deep_analyze"
  system_prompt: string;
  user_prompt: string;
  raw_response: string;
  model: string;
  tokens_total: number;
  latency_ms: number;
}

export interface AIAnalysisReport {
  id: string;                  // 形如 "20260425T024058-BTC-1h"
  ts: number;                  // ms
  symbol: string;
  tf: string;
  model_tier: "flash" | "pro";
  thinking_enabled: boolean;
  status: "ok" | "error";
  error_reason?: string | null;
  total_tokens: number;
  total_latency_ms: number;
  // 一句话摘要（hero 用）
  one_line: string;
  // markdown 完整报告（含分章节：判定 / 资金面 / 计划 / 风险 / 复盘）
  report_md: string;
  // 每层 raw 三段（system / user / raw_response）
  raw_payloads: AIRawPayload[];
  // 跨模型对照"纯数据切片"：剥掉规则/指令的纯指标 JSON 字符串，便于复制给其他 AI
  data_slice: string;
}

export interface AIReportsListItem {
  id: string;
  ts: number;
  symbol: string;
  tf: string;
  model_tier: "flash" | "pro";
  thinking_enabled: boolean;
  status: "ok" | "error";
  total_tokens: number;
  total_latency_ms: number;
  one_line: string;
}

export interface AIReportsListResp {
  items: AIReportsListItem[];
  size: number;
  limit: number;
}

export interface AIAnalyzeReq {
  symbol?: string;
  tf?: string;
}

export async function fetchAIReports(limit = 10): Promise<AIReportsListResp> {
  const r = await http.get<AIReportsListResp>("/api/ai/reports", {
    params: { limit },
  });
  return r.data;
}

export async function fetchAIReport(id: string): Promise<AIAnalysisReport> {
  const r = await http.get<{ report: AIAnalysisReport }>(`/api/ai/reports/${id}`);
  return r.data.report;
}

export async function runAIAnalyze(
  body: AIAnalyzeReq,
): Promise<AIAnalysisReport> {
  const r = await http.post<{ report: AIAnalysisReport }>(
    "/api/ai/analyze",
    body,
    { timeout: 180_000 }, // 深度分析允许 3 分钟（pro+thinking 兜底）
  );
  return r.data.report;
}
