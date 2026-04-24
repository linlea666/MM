// 与 backend/models.py 一一对应的 TS 类型。后端变更时需同步。

// ─── 基础类型 ────────────────────────────────────────

export type KlineSource = "binance" | "okx" | "hfd";

export type PhaseLabel =
  | "底部吸筹震荡"
  | "高位派发震荡"
  | "真突破启动"
  | "趋势延续"
  | "假突破猎杀"
  | "趋势耗竭"
  | "黑洞加速"
  | "无序震荡";

export type BehaviorMain =
  | "强吸筹"
  | "弱吸筹"
  | "强派发"
  | "弱派发"
  | "横盘震荡"
  | "趋势反转"
  | "无主导";

export type BehaviorAlertType =
  | "共振爆发"
  | "诱多"
  | "诱空"
  | "衰竭"
  | "变盘临近"
  | "护盘中"
  | "压盘中"
  | "猎杀进行中";

export type ParticipationLevel =
  | "主力真参与"
  | "局部参与"
  | "疑似散户"
  | "垃圾时间";

export type LevelStrength = "strong" | "medium" | "weak";
export type LevelFit = "first_test_good" | "worn_out" | "can_break" | "observe";

export type TradeAction =
  | "追多"
  | "追空"
  | "回踩做多"
  | "反弹做空"
  | "反手"
  | "观望";
export type PositionSize = "轻仓" | "标仓" | "重仓";
export type MagnetSide = "above" | "below";
export type Severity = "info" | "warning" | "alert";

// ─── DashboardSnapshot 结构 ────────────────────────

export interface CapabilityScore {
  name: string;
  score: number;
  confidence: number;
  evidences: string[];
  notes?: string | null;
}

export interface BehaviorAlert {
  type: BehaviorAlertType;
  strength: number;
}

export interface BehaviorScore {
  main: BehaviorMain;
  main_score: number;
  sub_scores: Record<string, number>;
  alerts: BehaviorAlert[];
}

export interface PhaseState {
  current: PhaseLabel;
  current_score: number;
  prev_phase?: PhaseLabel | null;
  next_likely?: PhaseLabel | null;
  unstable: boolean;
  bars_in_phase: number;
}

export interface ParticipationGate {
  level: ParticipationLevel;
  confidence: number;
  evidence: string[];
}

export interface Level {
  price: number;
  sources: string[];
  strength: LevelStrength;
  test_count: number;
  decay_pct: number;
  fit: LevelFit;
  score: number;
}

export interface LevelLadder {
  r3?: Level | null;
  r2?: Level | null;
  r1?: Level | null;
  current_price: number;
  s1?: Level | null;
  s2?: Level | null;
  s3?: Level | null;
}

export interface LiquidityTarget {
  side: MagnetSide;
  price: number;
  distance_pct: number;
  intensity: number;
  source: string;
}

export interface LiquidityCompass {
  above_targets: LiquidityTarget[];
  below_targets: LiquidityTarget[];
  nearest_side?: MagnetSide | null;
  nearest_distance_pct?: number | null;
}

export interface TradingPlan {
  label: "A" | "B" | "C";
  action: TradeAction;
  stars: number;
  entry?: [number, number] | null;
  stop?: number | null;
  take_profit: number[];
  position_size?: PositionSize | null;
  premise: string;
  invalidation: string;
}

export interface AIEvidence {
  indicator: string;
  field: string;
  value: number | string;
  note: string;
}

export interface AIObservation {
  type: "opportunity_candidate" | "conflict_warning";
  attention_level: "low" | "medium" | "high";
  headline: string;
  description: string;
  evidences: AIEvidence[];
}

export interface HeroStrip {
  main_behavior: string;
  market_structure: string;
  risk_status: string;
  action_conclusion: string;
  stars: number;
  invalidation: string;
}

export interface TimelineEvent {
  ts: number;
  kind: string;
  headline: string;
  detail?: string | null;
  severity: Severity;
}

export interface DashboardHealth {
  fresh: boolean;
  last_collector_ts?: number | null;
  stale_seconds?: number | null;
  warnings: string[];
}

export interface DashboardSnapshot {
  timestamp: number;
  symbol: string;
  tf: string;
  current_price: number;
  hero: HeroStrip;
  behavior: BehaviorScore;
  phase: PhaseState;
  participation: ParticipationGate;
  levels: LevelLadder;
  liquidity: LiquidityCompass;
  plans: TradingPlan[];
  ai_observations: AIObservation[];
  capability_scores: CapabilityScore[];
  recent_events: TimelineEvent[];
  health: DashboardHealth;
}

// ─── 订阅 / 系统 ─────────────────────────────────────

export interface Subscription {
  symbol: string;
  display_order: number;
  active: boolean;
  added_at: number;
  last_viewed_at?: number | null;
}

export interface SystemHealth {
  status: string;
  ts: number;
  uptime_seconds: number;
  app_name: string;
  app_version: string;
  env: string;
  active_symbols: string[];
  inactive_symbols: string[];
  scheduler_running: boolean;
  scheduler_jobs: number;
  circuits: Record<string, unknown>[];
}

// ─── 日志 ───────────────────────────────────────────

export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR";

export interface LogEntry {
  id?: number | null;
  ts: string;
  level: LogLevel;
  logger: string;
  message: string;
  tags: string[];
  context: Record<string, unknown>;
  traceback?: string | null;
}

export interface LogsQueryResp {
  items: LogEntry[];
  count: number;
  offset: number;
  limit: number;
  has_more: boolean;
  next_offset: number | null;
}

export interface LogsSummary {
  total: number;
  last_1h: Record<LogLevel, number>;
  last_24h: Record<LogLevel, number>;
  top_loggers_24h: { logger: string; count: number }[];
}

export interface LogsMeta {
  levels: LogLevel[];
  tags: string[];
  logger_prefixes: string[];
}

// ─── 配置 ───────────────────────────────────────────

export type ConfigValue =
  | number
  | string
  | boolean
  | number[]
  | string[]
  | null;

export type ConfigItemType =
  | "number"
  | "int"
  | "percent"
  | "weight"
  | "bool"
  | "string"
  | "enum"
  | "array";

export interface ConfigItemMeta {
  type: ConfigItemType;
  group: string;
  subgroup?: string;
  label: string;
  help?: string;
  impact?: string;
  danger?: boolean;
  readonly?: boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: (string | number)[];
  item_type?: ConfigItemType;
}

export interface ConfigGroupMeta {
  id: string;
  label: string;
  description?: string;
}

export interface ConfigMetaResp {
  groups: ConfigGroupMeta[];
  items: Record<string, ConfigItemMeta>;
}

export interface ConfigOverrideRow {
  key: string;
  value: ConfigValue;
  value_type?: string;
  updated_by: string;
  reason?: string | null;
  updated_at: number;
}

export interface ConfigSnapshotResp {
  /** 嵌套 dict（default+override 合并后的真源） */
  values: Record<string, unknown>;
  overrides: ConfigOverrideRow[];
}

export interface ConfigItemResp {
  key: string;
  value: ConfigValue;
  is_overridden: boolean;
  override_value: ConfigValue | null;
  meta: ConfigItemMeta;
}

export interface ConfigPatchReq {
  items: Record<string, ConfigValue>;
  updated_by?: string;
  reason?: string;
}

export interface ConfigPatchResp {
  applied: Record<string, ConfigValue>;
  count: number;
}

export interface ConfigPreviewResp {
  snapshot_before: Record<string, unknown>;
  snapshot_after: Record<string, unknown>;
}

export interface ConfigResetResp {
  scope: "all" | "single";
  removed: number | boolean;
  key?: string;
  value_after?: ConfigValue;
}

export interface ConfigAuditEntry {
  id: number;
  key: string;
  old_value: ConfigValue | null;
  new_value: ConfigValue | null;
  updated_by: string;
  reason: string | null;
  updated_at: number;
}

export interface ConfigAuditResp {
  items: ConfigAuditEntry[];
  total: number;
}

// ─── WS 消息 ────────────────────────────────────────

export type WsDashboardMsg =
  | { type: "hello"; channel: "dashboard" }
  | { type: "subscribed"; symbol: string; tf: string }
  | { type: "unsubscribed" }
  | { type: "pong" }
  | { type: "snapshot"; symbol: string; tf: string; data: DashboardSnapshot }
  | { type: "error"; code: string; message?: string; symbol?: string; tf?: string };

export type WsLogMsg =
  | { type: "hello"; channel: "logs" }
  | { type: "subscribed"; levels: string[]; loggers: string[] }
  | { type: "pong" }
  | { type: "log"; data: LogEntry }
  | { type: "error"; code: string };
