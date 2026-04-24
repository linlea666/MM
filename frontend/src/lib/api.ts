import axios, { type AxiosInstance } from "axios";
import type {
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
