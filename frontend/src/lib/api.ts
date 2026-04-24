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
