import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSymbolStore } from "@/stores/symbol-store";
import { fetchIndicatorsPanorama } from "@/lib/api";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import {
  AlertTriangle,
  Layers,
  TrendingUp,
  Waves,
  Crown,
  Loader2,
  RefreshCw,
  ArrowUp,
  ArrowDown,
  Flame,
} from "lucide-react";

// ─────────────────────────────────────────────────────
// 分类元信息
// ─────────────────────────────────────────────────────

type CategoryKey =
  | "trend"
  | "value"
  | "liquidity"
  | "structure"
  | "main_force";

const CATEGORIES: {
  key: CategoryKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  hint: string;
}[] = [
  {
    key: "trend",
    label: "趋势族",
    icon: TrendingUp,
    hint: "趋势纯度 / CVD 累积 / POC 漂移 / 饱和度 / 衰竭 / 波段四维",
  },
  {
    key: "value",
    label: "价值带族",
    icon: Layers,
    hint: "HVN 节点 / Volume Profile / 绝对区域 / 订单块 / 微观 POC / 移动 VWAP",
  },
  {
    key: "liquidity",
    label: "流动性族",
    icon: Waves,
    hint: "真空带 / 爆仓热力 / 爆仓燃料 / 连环爆仓 / 散户止损（按上下方分组）",
  },
  {
    key: "structure",
    label: "结构事件",
    icon: AlertTriangle,
    hint: "CHoCH 破位 / 流动性扫荡 / 能量失衡 / 趋势衰竭近窗",
  },
  {
    key: "main_force",
    label: "主力族",
    icon: Crown,
    hint: "聪明钱成本 / 跨所共振 / 巨鲸方向 / 时间热力图",
  },
];

// ─────────────────────────────────────────────────────
// 通用工具
// ─────────────────────────────────────────────────────

const fmt = (v: unknown, suffix = ""): string => {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    if (Math.abs(v) >= 1) return v.toLocaleString(undefined, { maximumFractionDigits: 4 }) + suffix;
    return v.toFixed(4) + suffix;
  }
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "是" : "否";
  return JSON.stringify(v);
};

const fmtInt = (v: unknown): string => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString();
};

const fmtPctSafe = (v: unknown): string => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return formatPct(v);
};

const fmtPrice = (v: unknown): string => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return formatPrice(v);
};

/** ms 时间戳 → "MM-DD HH:mm"。无效返回 "—"。 */
const fmtTime = (v: unknown): string => {
  if (typeof v !== "number" || !Number.isFinite(v) || v <= 0) return "—";
  const d = new Date(v);
  if (isNaN(d.getTime())) return "—";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi}`;
};

/** ms 时间戳 → "X 小时前/后" 或 "X 天前/后"。 */
const fmtRelTime = (v: unknown): string => {
  if (typeof v !== "number" || !Number.isFinite(v) || v <= 0) return "—";
  const diff = v - Date.now();
  const abs = Math.abs(diff);
  const sign = diff >= 0 ? "后" : "前";
  if (abs < 60 * 60 * 1000) return `${Math.round(abs / 60000)} 分钟${sign}`;
  if (abs < 24 * 60 * 60 * 1000) return `${(abs / 3600000).toFixed(1)} 小时${sign}`;
  return `${(abs / 86400000).toFixed(1)} 天${sign}`;
};

/** distance_pct 是 0-1 的小数（0.0214 = 2.14%）。 */
const distanceTone = (pct: number | undefined | null): "above" | "below" | "neutral" => {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return "neutral";
  if (pct > 0.0001) return "above";
  if (pct < -0.0001) return "below";
  return "neutral";
};

const fmtDistance = (pct: number | undefined | null): string => {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${(pct * 100).toFixed(2)}%`;
};

// ─────────────────────────────────────────────────────
// 可视化原子组件
// ─────────────────────────────────────────────────────

/** 横向进度条，value/max 自动 clamp 到 [0,1]，支持 tone 染色。 */
function ProgressBar({
  value,
  max = 1,
  tone = "primary",
  className,
}: {
  value: number | null | undefined;
  max?: number;
  tone?: "primary" | "good" | "bad" | "warn";
  className?: string;
}) {
  const v = typeof value === "number" && Number.isFinite(value) ? value : 0;
  const m = max > 0 ? max : 1;
  const ratio = Math.max(0, Math.min(1, v / m));
  const toneClass =
    tone === "good"
      ? "bg-emerald-400"
      : tone === "bad"
        ? "bg-rose-400"
        : tone === "warn"
          ? "bg-amber-400"
          : "bg-primary";
  return (
    <div
      className={cn(
        "relative h-1.5 w-full overflow-hidden rounded-full bg-secondary/40",
        className,
      )}
    >
      <div
        className={cn("absolute inset-y-0 left-0 rounded-full", toneClass)}
        style={{ width: `${(ratio * 100).toFixed(2)}%` }}
      />
    </div>
  );
}

/** 强度点：[●●●○○]，count = 多少个填充。 */
function IntensityDots({
  count,
  max = 5,
  tone = "warn",
}: {
  count: number;
  max?: number;
  tone?: "warn" | "bad" | "good";
}) {
  const dots = Array.from({ length: max });
  const filled = Math.max(0, Math.min(max, count));
  const fillTone =
    tone === "bad"
      ? "bg-rose-400"
      : tone === "good"
        ? "bg-emerald-400"
        : "bg-amber-400";
  return (
    <span className="inline-flex items-center gap-0.5">
      {dots.map((_, i) => (
        <span
          key={i}
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            i < filled ? fillTone : "bg-border/60",
          )}
        />
      ))}
    </span>
  );
}

// ─────────────────────────────────────────────────────
// 卡片基类
// ─────────────────────────────────────────────────────

interface IndicatorCardProps {
  title: string;
  hint?: string;
  empty?: boolean;
  emptyText?: string;
  rows?: { label: string; value: React.ReactNode; tone?: "good" | "bad" | "neutral" | "warn" }[];
  children?: React.ReactNode;
  className?: string;
}

function IndicatorCard({
  title,
  hint,
  empty,
  emptyText,
  rows,
  children,
  className,
}: IndicatorCardProps) {
  return (
    <div className={cn("panel-glass rounded-lg p-4", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            {title}
          </div>
          {hint && (
            <div className="mt-0.5 text-[11px] text-muted-foreground/70">
              {hint}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 space-y-1.5 text-sm">
        {empty ? (
          <div className="text-muted-foreground">{emptyText ?? "暂无数据"}</div>
        ) : (
          <>
            {rows?.map((r, i) => (
              <div
                key={i}
                className="flex items-baseline justify-between gap-3"
              >
                <span className="text-xs text-muted-foreground">{r.label}</span>
                <span
                  className={cn(
                    "num font-medium",
                    r.tone === "good" && "text-emerald-400",
                    r.tone === "bad" && "text-rose-400",
                    r.tone === "warn" && "text-amber-400",
                  )}
                >
                  {r.value}
                </span>
              </div>
            ))}
            {children}
          </>
        )}
      </div>
    </div>
  );
}

/** 价位带行：价位 + 距现价% + side 染色 + 强度（可选）+ 备注（可选）。 */
function BandRow({
  price,
  rangeBottom,
  rangeTop,
  distancePct,
  side,
  intensity,
  intensityMax = 5,
  extra,
}: {
  price?: number;
  rangeBottom?: number;
  rangeTop?: number;
  distancePct?: number;
  side?: string;
  intensity?: number;
  intensityMax?: number;
  extra?: React.ReactNode;
}) {
  const tone = distanceTone(distancePct);
  const sideTone =
    side === "long_fuel" || side === "buy" || side === "bullish"
      ? "text-emerald-400"
      : side === "short_fuel" || side === "sell" || side === "bearish"
        ? "text-rose-400"
        : "text-muted-foreground";
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5 text-xs">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="num font-medium text-foreground/90">
          {rangeBottom !== undefined && rangeTop !== undefined
            ? `${fmtPrice(rangeBottom)} → ${fmtPrice(rangeTop)}`
            : fmtPrice(price)}
        </span>
        {distancePct !== undefined && (
          <span
            className={cn(
              "num text-[11px]",
              tone === "above" && "text-rose-300",
              tone === "below" && "text-emerald-300",
              tone === "neutral" && "text-muted-foreground",
            )}
          >
            {fmtDistance(distancePct)}
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-2 text-muted-foreground">
        {intensity !== undefined && (
          <IntensityDots count={intensity} max={intensityMax} tone="warn" />
        )}
        {side && <span className={cn("num", sideTone)}>{side}</span>}
        {extra}
      </div>
    </div>
  );
}

/** 上方/下方分栏布局。bands 按 distance_pct 已分组传入。 */
function BandSplitView({
  above,
  below,
  renderRow,
  emptyText = "暂无",
}: {
  above: Record<string, unknown>[];
  below: Record<string, unknown>[];
  renderRow: (b: Record<string, unknown>, i: number) => React.ReactNode;
  emptyText?: string;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div className="rounded-md border border-rose-500/20 bg-rose-500/5 p-2">
        <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-rose-300">
          <ArrowUp className="h-3 w-3" /> 上方 ({above.length})
        </div>
        <div className="max-h-72 space-y-0.5 overflow-auto pr-1">
          {above.length === 0 ? (
            <div className="text-xs text-muted-foreground">{emptyText}</div>
          ) : (
            above.map(renderRow)
          )}
        </div>
      </div>
      <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 p-2">
        <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-emerald-300">
          <ArrowDown className="h-3 w-3" /> 下方 ({below.length})
        </div>
        <div className="max-h-72 space-y-0.5 overflow-auto pr-1">
          {below.length === 0 ? (
            <div className="text-xs text-muted-foreground">{emptyText}</div>
          ) : (
            below.map(renderRow)
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────
// snapshot 访问助手
// ─────────────────────────────────────────────────────

interface SnapAccess {
  raw: Record<string, unknown>;
  get: <T = unknown>(key: string) => T | undefined;
  list: <T = Record<string, unknown>>(key: string) => T[];
  lastPrice: number | undefined;
}

function makeAccess(raw: Record<string, unknown>): SnapAccess {
  return {
    raw,
    get: <T = unknown,>(key: string) => raw[key] as T | undefined,
    list: <T = Record<string, unknown>,>(key: string) =>
      (Array.isArray(raw[key]) ? (raw[key] as T[]) : []) as T[],
    lastPrice:
      typeof raw["last_price"] === "number" && Number.isFinite(raw["last_price"] as number)
        ? (raw["last_price"] as number)
        : undefined,
  };
}

/** 计算 (price - lastPrice)/lastPrice，无效返回 undefined。 */
function distPct(price: unknown, lastPrice: number | undefined): number | undefined {
  if (
    typeof price !== "number" ||
    !Number.isFinite(price) ||
    typeof lastPrice !== "number" ||
    !Number.isFinite(lastPrice) ||
    lastPrice <= 0
  )
    return undefined;
  return (price - lastPrice) / lastPrice;
}

/** 把 BandView/HeatmapBand/LiquidationFuelBand/VacuumBand/Cascade/Retail 等
 * 单元归一化到 {center, distance, side?, intensity?, raw}，统一上下方分组。 */
type BandLike = {
  center: number;
  bottom?: number;
  top?: number;
  distance?: number;
  side?: string;
  intensity?: number;
  raw: Record<string, unknown>;
};

function partition(bands: BandLike[]): { above: BandLike[]; below: BandLike[] } {
  const above = bands
    .filter((b) => (b.distance ?? 0) > 0)
    .sort((a, b) => (a.distance ?? 0) - (b.distance ?? 0));
  const below = bands
    .filter((b) => (b.distance ?? 0) <= 0)
    .sort((a, b) => (b.distance ?? 0) - (a.distance ?? 0));
  return { above, below };
}

// ─────────────────────────────────────────────────────
// Tab 1 · 趋势族
// ─────────────────────────────────────────────────────

function TrendTab({ snap }: { snap: SnapAccess }) {
  const purity = snap.get<Record<string, unknown>>("trend_purity_last");
  const sat = snap.get<Record<string, unknown>>("trend_saturation");
  const cvd_sign = snap.get<string>("cvd_slope_sign");
  const exh_streak = snap.get<number>("exhaustion_streak") ?? 0;
  const exh_type = snap.get<string>("exhaustion_streak_type");
  const exh_last = snap.get<Record<string, unknown>>("trend_exhaustion_last");
  const sp = snap.get<Record<string, unknown>>("segment_portrait");
  const last_price = snap.lastPrice;

  return (
    <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
      {/* 趋势纯度 */}
      <IndicatorCard
        title="趋势纯度（trend_purity）"
        hint="纯度 ∈ [0,100]：越高代表筹码方向越纯净"
        empty={!purity}
        emptyText="该周期无趋势纯度段"
      >
        {purity && (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">类型</span>
              <span
                className={cn(
                  "num font-medium",
                  purity.type === "Accumulation"
                    ? "text-emerald-400"
                    : "text-rose-400",
                )}
              >
                {fmt(purity.type)}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">纯度</span>
              <span className="num font-medium">
                {fmt(purity.purity)} / 100
              </span>
            </div>
            <ProgressBar
              value={Number(purity.purity ?? 0)}
              max={100}
              tone={Number(purity.purity ?? 0) >= 60 ? "good" : "warn"}
              className="mb-2"
            />
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">段均价</span>
              <span className="num">{fmtPrice(purity.avg_price)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">总成交量</span>
              <span className="num">{fmtInt(purity.total_vol)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">起始</span>
              <span className="num text-[11px] text-muted-foreground">
                {fmtTime(purity.start_time)}
              </span>
            </div>
          </>
        )}
      </IndicatorCard>

      {/* 趋势饱和度 */}
      <IndicatorCard
        title="趋势饱和度（trend_saturation）"
        hint="progress ≥ 0.85 信号降一档；≥ 0.9 只能定 weak"
        empty={!sat}
        emptyText="无饱和度数据"
      >
        {sat && (() => {
          const progress = Number(sat.progress ?? 0);
          const tone = progress >= 0.9 ? "bad" : progress >= 0.85 ? "warn" : "good";
          return (
            <>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">类型</span>
                <span
                  className={cn(
                    "num font-medium",
                    sat.type === "Accumulation"
                      ? "text-emerald-400"
                      : "text-rose-400",
                  )}
                >
                  {fmt(sat.type)}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">饱和度</span>
                <span
                  className={cn(
                    "num font-medium",
                    tone === "bad" && "text-rose-400",
                    tone === "warn" && "text-amber-400",
                    tone === "good" && "text-emerald-400",
                  )}
                >
                  {fmtPctSafe(progress)}
                </span>
              </div>
              <ProgressBar value={progress} max={1} tone={tone} className="mb-2" />
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">当前 / 平均量</span>
                <span className="num">
                  {fmtInt(sat.current_vol)} / {fmtInt(sat.avg_vol)}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">起始</span>
                <span className="num text-[11px] text-muted-foreground">
                  {fmtTime(sat.start_time)}
                </span>
              </div>
            </>
          );
        })()}
      </IndicatorCard>

      {/* CVD 累积 */}
      <IndicatorCard
        title="CVD 累积（cvd_slope）"
        hint="lookback 窗内净买盘累积；converge 越小越收敛（多空对冲）"
      >
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">斜率方向</span>
          <span
            className={cn(
              "num font-medium",
              cvd_sign === "up" && "text-emerald-400",
              cvd_sign === "down" && "text-rose-400",
            )}
          >
            {fmt(cvd_sign)}
          </span>
        </div>
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">斜率值</span>
          <span className="num">{fmtInt(snap.get("cvd_slope"))}</span>
        </div>
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">收敛比</span>
          <span className="num">{fmtPctSafe(snap.get("cvd_converge_ratio"))}</span>
        </div>
        <ProgressBar
          value={Number(snap.get("cvd_converge_ratio") ?? 0)}
          max={1}
          tone="primary"
          className="mb-2"
        />
        <div className="mt-2 grid grid-cols-2 gap-2">
          <div>
            <div className="flex items-baseline justify-between text-[11px]">
              <span className="text-emerald-400/80">imb 绿</span>
              <span className="num">{fmtPctSafe(snap.get("imbalance_green_ratio"))}</span>
            </div>
            <ProgressBar
              value={Number(snap.get("imbalance_green_ratio") ?? 0)}
              tone="good"
            />
          </div>
          <div>
            <div className="flex items-baseline justify-between text-[11px]">
              <span className="text-rose-400/80">imb 红</span>
              <span className="num">{fmtPctSafe(snap.get("imbalance_red_ratio"))}</span>
            </div>
            <ProgressBar
              value={Number(snap.get("imbalance_red_ratio") ?? 0)}
              tone="bad"
            />
          </div>
        </div>
      </IndicatorCard>

      {/* POC 漂移 + VWAP 偏离 */}
      <IndicatorCard
        title="POC 漂移 / VWAP 偏离"
        hint="价值中枢方向 + 当前价相对公允价的乖离"
      >
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">POC 漂移</span>
          <span
            className={cn(
              "num font-medium",
              snap.get<string>("poc_shift_trend") === "up" && "text-emerald-400",
              snap.get<string>("poc_shift_trend") === "down" && "text-rose-400",
            )}
          >
            {fmt(snap.get("poc_shift_trend"))}
          </span>
        </div>
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">百分比变化</span>
          <span className="num">{fmtPctSafe(snap.get("poc_shift_delta_pct"))}</span>
        </div>
        <div className="mt-2 border-t border-border/30 pt-2">
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">VWAP 价位</span>
            <span className="num">{fmtPrice(snap.get("vwap_last"))}</span>
          </div>
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">VWAP 斜率</span>
            <span className="num">{fmtPctSafe(snap.get("vwap_slope"))}</span>
          </div>
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">乖离</span>
            <span
              className={cn(
                "num font-medium",
                Number(snap.get("fair_value_delta_pct") ?? 0) > 0
                  ? "text-rose-400"
                  : "text-emerald-400",
              )}
            >
              {fmtPctSafe(snap.get("fair_value_delta_pct"))}
            </span>
          </div>
        </div>
      </IndicatorCard>

      {/* 趋势衰竭 */}
      <IndicatorCard
        title="趋势衰竭（trend_exhaustion）"
        hint="官方口径：连续 ≥3 根 → 衰竭警报"
      >
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">Streak</span>
          <span
            className={cn(
              "num font-medium",
              exh_streak >= 3 && "text-rose-400",
            )}
          >
            {fmtInt(exh_streak)} 根 · {fmt(exh_type)}
          </span>
        </div>
        <ProgressBar
          value={Math.min(exh_streak, 5)}
          max={5}
          tone={exh_streak >= 3 ? "bad" : "warn"}
          className="mb-2"
        />
        {exh_last ? (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">最近一条 type</span>
              <span
                className={cn(
                  "num",
                  exh_last.type === "Accumulation"
                    ? "text-emerald-400"
                    : "text-rose-400",
                )}
              >
                {fmt(exh_last.type)}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">衰竭值</span>
              <span className="num">{fmt(exh_last.exhaustion)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">时间</span>
              <span className="num text-[11px] text-muted-foreground">
                {fmtTime(exh_last.ts)}
              </span>
            </div>
          </>
        ) : (
          <div className="text-xs text-muted-foreground">无最新衰竭事件</div>
        )}
      </IndicatorCard>

      {/* 趋势 ROI 耗尽 */}
      <IndicatorCard
        title="趋势 ROI 耗尽（roi_segment）"
        hint="历史大数据驱动的目标价 + 距现价 %"
        empty={!sp || (sp.roi_limit_avg_price === undefined && sp.roi_limit_max_price === undefined)}
      >
        {sp && (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">T1 平均目标</span>
              <span className="num">
                {fmtPrice(sp.roi_limit_avg_price)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(sp.roi_limit_avg_price, last_price))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">T2 极限目标</span>
              <span className="num">
                {fmtPrice(sp.roi_limit_max_price)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(sp.roi_limit_max_price, last_price))}
                </span>
              </span>
            </div>
            <div className="mt-2 border-t border-border/30 pt-2">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">至均根数</span>
                <span className="num">{fmt(sp.bars_to_avg)}</span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">至亡线根数</span>
                <span
                  className={cn(
                    "num",
                    typeof sp.bars_to_max === "number" &&
                      (sp.bars_to_max as number) <= 3 &&
                      "text-rose-400",
                  )}
                >
                  {fmt(sp.bars_to_max)}
                </span>
              </div>
            </div>
          </>
        )}
      </IndicatorCard>

      {/* 最大回撤容忍 */}
      <IndicatorCard
        title="最大回撤容忍（dd_tolerance）"
        hint="护城河 + 击穿次数（黄色图钉）"
        empty={!sp || sp.dd_trailing_current === undefined}
      >
        {sp && (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">护城河当前</span>
              <span className="num font-medium">
                {fmtPrice(sp.dd_trailing_current)}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">距现价</span>
              <span className="num">
                {fmtDistance(distPct(sp.dd_trailing_current, last_price))}
              </span>
            </div>
            <div className="mt-2 border-t border-border/30 pt-2">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">允许最大回撤</span>
                <span className="num">{fmtPctSafe(sp.dd_limit_pct)}</span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">击穿次数</span>
                <span
                  className={cn(
                    "num font-medium",
                    Number(sp.dd_pierce_count ?? 0) > 0 && "text-amber-400",
                  )}
                >
                  {fmtInt(sp.dd_pierce_count)}
                </span>
              </div>
            </div>
          </>
        )}
      </IndicatorCard>

      {/* 时间耗尽窗口 */}
      <IndicatorCard
        title="时间耗尽窗口（time_exhaustion）"
        hint="本波段绝对时间锚点：到平均寿命 / 死亡线"
        empty={!sp || (sp.time_avg_ts === undefined && sp.time_max_ts === undefined)}
      >
        {sp && (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">至平均寿命</span>
              <span className="num">{fmtTime(sp.time_avg_ts)}</span>
            </div>
            <div className="text-right text-[11px] text-muted-foreground">
              {fmtRelTime(sp.time_avg_ts)}
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">至死亡线</span>
              <span
                className={cn(
                  "num font-medium",
                  typeof sp.time_max_ts === "number" &&
                    sp.time_max_ts < Date.now() + 6 * 3600 * 1000 &&
                    "text-rose-400",
                )}
              >
                {fmtTime(sp.time_max_ts)}
              </span>
            </div>
            <div className="text-right text-[11px] text-muted-foreground">
              {fmtRelTime(sp.time_max_ts)}
            </div>
            <div className="mt-2 border-t border-border/30 pt-2">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">极限洗盘价</span>
                <span className="num font-medium">
                  {fmtPrice(sp.pain_max_price)}
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">距现价</span>
                <span className="num">
                  {fmtDistance(distPct(sp.pain_max_price, last_price))}
                </span>
              </div>
            </div>
          </>
        )}
      </IndicatorCard>
    </div>
  );
}

// ─────────────────────────────────────────────────────
// Tab 2 · 价值带族
// ─────────────────────────────────────────────────────

function ValueTab({ snap }: { snap: SnapAccess }) {
  const hvn = snap.list<Record<string, unknown>>("hvn_nodes");
  const az = snap.list<Record<string, unknown>>("absolute_zones");
  const ob = snap.list<Record<string, unknown>>("order_blocks");
  const micro = snap.list<Record<string, unknown>>("micro_pocs");
  const vp = snap.get<Record<string, unknown>>("volume_profile");
  const vwap = snap.get<Record<string, unknown>>("trailing_vwap_last");
  const last_price = snap.lastPrice;

  const hvnMaxVol = useMemo(
    () =>
      hvn.reduce(
        (m, n) => Math.max(m, Number(n.volume) || 0),
        0,
      ),
    [hvn],
  );
  const microMaxVol = useMemo(
    () =>
      micro.reduce(
        (m, n) => Math.max(m, Number(n.volume) || 0),
        0,
      ),
    [micro],
  );

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* HVN 节点 */}
      <IndicatorCard
        title={`HVN 节点（hvn_nodes · ${hvn.length}）`}
        hint="高成交量价位 = 成本中枢，按 rank 排列"
        empty={hvn.length === 0}
      >
        <div className="mt-1 max-h-72 space-y-1.5 overflow-auto pr-1">
          {hvn.slice(0, 12).map((n, i) => (
            <div key={i}>
              <div className="flex items-baseline justify-between text-xs">
                <span className="flex items-baseline gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    #{fmt(n.rank)}
                  </span>
                  <span className="num font-medium">{fmtPrice(n.price)}</span>
                  <span className="text-[11px] text-muted-foreground">
                    {fmtDistance(distPct(n.price, last_price))}
                  </span>
                </span>
                <span className="text-[11px] text-muted-foreground">
                  vol={fmtInt(n.volume)}
                </span>
              </div>
              <ProgressBar
                value={Number(n.volume) || 0}
                max={hvnMaxVol || 1}
                tone="primary"
              />
            </div>
          ))}
        </div>
      </IndicatorCard>

      {/* Volume Profile */}
      <IndicatorCard
        title="筹码分布（volume_profile）"
        hint="POC + Value Area + Top 节点；越纯越有压制力"
        empty={!vp}
      >
        {vp && (
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">价位位置</span>
              <span
                className={cn(
                  "num font-medium",
                  vp.last_price_position === "above_va" && "text-rose-300",
                  vp.last_price_position === "below_va" && "text-emerald-300",
                  vp.last_price_position === "in_va" && "text-amber-300",
                )}
              >
                {fmt(vp.last_price_position)}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">POC</span>
              <span className="num font-medium">
                {fmtPrice(vp.poc_price)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(Number(vp.poc_distance_pct))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">VA High</span>
              <span className="num">
                {fmtPrice(vp.value_area_high)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(vp.value_area_high, last_price))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">VA Low</span>
              <span className="num">
                {fmtPrice(vp.value_area_low)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(vp.value_area_low, last_price))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">VA 占比</span>
              <span className="num">{fmtPctSafe(vp.value_area_volume_ratio)}</span>
            </div>
            <ProgressBar
              value={Number(vp.value_area_volume_ratio ?? 0)}
              max={1}
              tone="good"
              className="mb-2"
            />
            <div className="border-t border-border/30 pt-2 text-[11px] text-muted-foreground">
              Top 节点：
            </div>
            <div className="space-y-0.5">
              {(vp.top_nodes as Record<string, unknown>[] | undefined)
                ?.slice(0, 5)
                .map((p, i) => (
                  <div
                    key={i}
                    className="flex items-baseline justify-between text-xs"
                  >
                    <span className="num">
                      {fmtPrice(p.price)}
                      <span className="ml-2 text-[11px] text-muted-foreground">
                        {fmtDistance(distPct(p.price, last_price))}
                      </span>
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      <span
                        className={cn(
                          p.dominant_side === "buy" && "text-emerald-400",
                          p.dominant_side === "sell" && "text-rose-400",
                        )}
                      >
                        {fmt(p.dominant_side)}
                      </span>
                      {" · "}
                      纯度 {fmtPctSafe(p.purity_ratio)}
                    </span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </IndicatorCard>

      {/* Absolute Zones */}
      <IndicatorCard
        title={`绝对区域（absolute_zones · ${az.length}）`}
        hint="高时间框架强支撑/压力，bottom→top 区间"
        empty={az.length === 0}
      >
        <div className="mt-1 max-h-72 space-y-0.5 overflow-auto pr-1">
          {az.slice(0, 14).map((z, i) => {
            const center =
              (Number(z.bottom_price) + Number(z.top_price)) / 2;
            return (
              <BandRow
                key={i}
                rangeBottom={Number(z.bottom_price)}
                rangeTop={Number(z.top_price)}
                distancePct={distPct(center, last_price)}
                side={String(z.type)}
              />
            );
          })}
        </div>
      </IndicatorCard>

      {/* Order Blocks */}
      <IndicatorCard
        title={`订单块（order_blocks · ${ob.length}）`}
        hint="机构订单块（单价位段：avg_price + volume + type）"
        empty={ob.length === 0}
      >
        <div className="mt-1 max-h-72 space-y-0.5 overflow-auto pr-1">
          {ob.slice(0, 14).map((z, i) => (
            <div
              key={i}
              className="flex items-baseline justify-between gap-2 text-xs"
            >
              <span className="flex items-baseline gap-2">
                <span className="num font-medium">{fmtPrice(z.avg_price)}</span>
                <span className="text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(z.avg_price, last_price))}
                </span>
              </span>
              <span className="text-[11px] text-muted-foreground">
                <span
                  className={cn(
                    z.type === "Accumulation" && "text-emerald-400",
                    z.type === "Distribution" && "text-rose-400",
                  )}
                >
                  {fmt(z.type)}
                </span>
                {" · vol="}
                {fmtInt(z.volume)}
              </span>
            </div>
          ))}
        </div>
      </IndicatorCard>

      {/* 微观 POC */}
      <IndicatorCard
        title={`微观 POC（micro_pocs · ${micro.length}）`}
        hint="本轮 K 线集中成交价，按 vol 横向条形对比"
        empty={micro.length === 0}
      >
        <div className="mt-1 max-h-72 space-y-1.5 overflow-auto pr-1">
          {micro.slice(0, 12).map((m, i) => (
            <div key={i}>
              <div className="flex items-baseline justify-between text-xs">
                <span className="num font-medium">
                  {fmtPrice(m.poc_price)}
                  <span className="ml-2 text-[11px] text-muted-foreground">
                    {fmtDistance(distPct(m.poc_price, last_price))}
                  </span>
                </span>
                <span className="text-[11px] text-muted-foreground">
                  <span
                    className={cn(
                      m.type === "Accumulation" && "text-emerald-400",
                      m.type === "Distribution" && "text-rose-400",
                    )}
                  >
                    {fmt(m.type)}
                  </span>
                  {" · vol="}
                  {fmtInt(m.volume)}
                </span>
              </div>
              <ProgressBar
                value={Number(m.volume) || 0}
                max={microMaxVol || 1}
                tone={m.type === "Accumulation" ? "good" : "bad"}
              />
            </div>
          ))}
        </div>
      </IndicatorCard>

      {/* 移动 VWAP */}
      <IndicatorCard
        title="移动 VWAP（trailing_vwap）"
        hint="Anchor 后的 VWAP 推移：support / resistance 双线"
        empty={!vwap}
      >
        {vwap && (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">阻力（resistance）</span>
              <span className="num font-medium text-rose-300">
                {fmtPrice(vwap.resistance)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(vwap.resistance, last_price))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">支撑（support）</span>
              <span className="num font-medium text-emerald-300">
                {fmtPrice(vwap.support)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(vwap.support, last_price))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">事件时间</span>
              <span className="num text-[11px] text-muted-foreground">
                {fmtTime(vwap.ts)}
              </span>
            </div>
            <div className="mt-2 border-t border-border/30 pt-2">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted-foreground">价 vs VWAP</span>
                <span
                  className={cn(
                    "num",
                    Number(snap.get("fair_value_delta_pct") ?? 0) > 0
                      ? "text-rose-400"
                      : "text-emerald-400",
                  )}
                >
                  {fmtPctSafe(snap.get("fair_value_delta_pct"))}
                </span>
              </div>
            </div>
          </>
        )}
      </IndicatorCard>
    </div>
  );
}

// ─────────────────────────────────────────────────────
// Tab 3 · 流动性族（爆仓带类按上下方分组）
// ─────────────────────────────────────────────────────

function LiquidityTab({ snap }: { snap: SnapAccess }) {
  const last_price = snap.lastPrice;
  const vacs = snap.list<Record<string, unknown>>("vacuums");
  const heat = snap.list<Record<string, unknown>>("heatmap");
  const fuel = snap.list<Record<string, unknown>>("liquidation_fuel");
  const cascade = snap.list<Record<string, unknown>>("cascade_bands");
  const retail = snap.list<Record<string, unknown>>("retail_stop_bands");

  // 真空带：低成交量穿越快，单元 = {low, high}
  const vacBands: BandLike[] = useMemo(
    () =>
      vacs.map((v) => {
        const lo = Number(v.low);
        const hi = Number(v.high);
        const center = (lo + hi) / 2;
        return {
          center,
          bottom: lo,
          top: hi,
          distance: distPct(center, last_price),
          raw: v,
        };
      }),
    [vacs, last_price],
  );

  // 爆仓热力：单价位 + intensity
  const heatBands: BandLike[] = useMemo(
    () =>
      heat.map((h) => ({
        center: Number(h.price),
        distance: distPct(h.price, last_price),
        side: String(h.type),
        intensity: Math.round(Number(h.intensity ?? 0) * 5),
        raw: h,
      })),
    [heat, last_price],
  );

  // 爆仓燃料：bottom → top + fuel
  const fuelMaxFuel = useMemo(
    () => fuel.reduce((m, f) => Math.max(m, Number(f.fuel) || 0), 0),
    [fuel],
  );
  const fuelBands: BandLike[] = useMemo(
    () =>
      fuel.map((f) => {
        const bot = Number(f.bottom);
        const top = Number(f.top);
        const center = (bot + top) / 2;
        return {
          center,
          bottom: bot,
          top: top,
          distance: distPct(center, last_price),
          raw: f,
        };
      }),
    [fuel, last_price],
  );

  // 连环爆仓 / 散户止损：BandView，已含 distance_pct + signal_count + side
  const toBandLike = (b: Record<string, unknown>): BandLike => ({
    center: Number(b.avg_price),
    bottom: Number(b.bottom_price),
    top: Number(b.top_price),
    distance:
      typeof b.distance_pct === "number"
        ? (b.distance_pct as number)
        : distPct(b.avg_price, last_price),
    side: String(b.side ?? ""),
    intensity:
      typeof b.signal_count === "number" ? (b.signal_count as number) : undefined,
    raw: b,
  });
  const cascadeBands = useMemo(() => cascade.map(toBandLike), [cascade, last_price]);
  const retailBands = useMemo(() => retail.map(toBandLike), [retail, last_price]);

  const vacSplit = partition(vacBands);
  const heatSplit = partition(heatBands);
  const fuelSplit = partition(fuelBands);
  const cascadeSplit = partition(cascadeBands);
  const retailSplit = partition(retailBands);

  return (
    <div className="grid gap-4">
      {/* 连环爆仓带 — 用户最关心，置顶 */}
      <IndicatorCard
        title={`连环爆仓带（cascade · ${cascade.length}）`}
        hint="2/4/8 倍连环触发位；上方 = 空头燃料，下方 = 多头燃料；💣 = signal_count 强度"
        empty={cascade.length === 0}
      >
        <BandSplitView
          above={cascadeSplit.above.map((b) => b.raw)}
          below={cascadeSplit.below.map((b) => b.raw)}
          renderRow={(b, i) => (
            <BandRow
              key={i}
              price={Number(b.avg_price)}
              distancePct={
                typeof b.distance_pct === "number"
                  ? (b.distance_pct as number)
                  : distPct(b.avg_price, last_price)
              }
              side={String(b.side ?? "")}
              intensity={
                typeof b.signal_count === "number"
                  ? (b.signal_count as number)
                  : undefined
              }
              intensityMax={5}
              extra={
                <span className="text-[10px] text-muted-foreground">
                  {fmtPrice(b.bottom_price)} → {fmtPrice(b.top_price)}
                </span>
              }
            />
          )}
        />
      </IndicatorCard>

      {/* 散户止损带 */}
      <IndicatorCard
        title={`散户止损带（retail_stop · ${retail.length}）`}
        hint="磁吸方向 = 主力扫货目标；距 POC < 0.3% 易被率先扫损"
        empty={retail.length === 0}
      >
        <BandSplitView
          above={retailSplit.above.map((b) => b.raw)}
          below={retailSplit.below.map((b) => b.raw)}
          renderRow={(b, i) => (
            <BandRow
              key={i}
              price={Number(b.avg_price)}
              distancePct={
                typeof b.distance_pct === "number"
                  ? (b.distance_pct as number)
                  : distPct(b.avg_price, last_price)
              }
              side={String(b.side ?? "")}
              extra={
                <span className="text-[10px] text-muted-foreground">
                  vol={fmtInt(b.volume)}
                </span>
              }
            />
          )}
        />
      </IndicatorCard>

      {/* 爆仓热力 */}
      <IndicatorCard
        title={`爆仓热力（heatmap · ${heat.length}）`}
        hint="清算预测密度；intensity ∈ [0,1]，越高越密"
        empty={heat.length === 0}
      >
        <BandSplitView
          above={heatSplit.above.map((b) => b.raw)}
          below={heatSplit.below.map((b) => b.raw)}
          renderRow={(b, i) => (
            <div
              key={i}
              className="flex items-baseline justify-between gap-2 py-0.5 text-xs"
            >
              <span className="flex items-baseline gap-2">
                <span className="num font-medium">{fmtPrice(b.price)}</span>
                <span className="text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(b.price, last_price))}
                </span>
              </span>
              <span className="flex items-baseline gap-2">
                <IntensityDots
                  count={Math.round(Number(b.intensity ?? 0) * 5)}
                  max={5}
                  tone="bad"
                />
                <span className="text-[11px] text-muted-foreground">
                  <span
                    className={cn(
                      b.type === "Accumulation" && "text-emerald-400",
                      b.type === "Distribution" && "text-rose-400",
                    )}
                  >
                    {fmt(b.type)}
                  </span>
                </span>
              </span>
            </div>
          )}
        />
      </IndicatorCard>

      {/* 爆仓燃料 */}
      <IndicatorCard
        title={`爆仓燃料（liquidation_fuel · ${fuel.length}）`}
        hint="累积清算能量（fuel）；与最大值横向对比"
        empty={fuel.length === 0}
      >
        <BandSplitView
          above={fuelSplit.above.map((b) => b.raw)}
          below={fuelSplit.below.map((b) => b.raw)}
          renderRow={(b, i) => {
            const bot = Number(b.bottom);
            const top = Number(b.top);
            const center = (bot + top) / 2;
            return (
              <div key={i} className="py-0.5">
                <div className="flex items-baseline justify-between text-xs">
                  <span className="num">
                    {fmtPrice(bot)} → {fmtPrice(top)}
                    <span className="ml-2 text-[11px] text-muted-foreground">
                      {fmtDistance(distPct(center, last_price))}
                    </span>
                  </span>
                  <span className="flex items-baseline gap-1 text-[11px] text-muted-foreground">
                    <Flame className="h-3 w-3 text-amber-400" />
                    {fmtInt(b.fuel)}
                  </span>
                </div>
                <ProgressBar
                  value={Number(b.fuel) || 0}
                  max={fuelMaxFuel || 1}
                  tone="warn"
                />
              </div>
            );
          }}
        />
      </IndicatorCard>

      {/* 真空带 */}
      <IndicatorCard
        title={`真空带（vacuums · ${vacs.length}）`}
        hint="低成交量区间 → 价格穿越极快"
        empty={vacs.length === 0}
      >
        <BandSplitView
          above={vacSplit.above.map((b) => b.raw)}
          below={vacSplit.below.map((b) => b.raw)}
          renderRow={(b, i) => {
            const lo = Number(b.low);
            const hi = Number(b.high);
            const center = (lo + hi) / 2;
            return (
              <BandRow
                key={i}
                rangeBottom={lo}
                rangeTop={hi}
                distancePct={distPct(center, last_price)}
                extra={
                  <span className="text-[10px] text-muted-foreground">
                    宽 {fmtPctSafe((hi - lo) / lo)}
                  </span>
                }
              />
            );
          }}
        />
      </IndicatorCard>
    </div>
  );
}

// ─────────────────────────────────────────────────────
// Tab 4 · 结构事件族
// ─────────────────────────────────────────────────────

function StructureTab({ snap }: { snap: SnapAccess }) {
  const last_price = snap.lastPrice;
  const choch_latest = snap.get<Record<string, unknown>>("choch_latest");
  const choch = snap.list<Record<string, unknown>>("choch_recent");
  const sweep_last = snap.get<Record<string, unknown>>("sweep_last");
  const sweep_count = snap.get<number>("sweep_count_recent") ?? 0;
  const pi_recent = snap.list<Record<string, unknown>>("power_imbalance_recent");
  const pi_streak = snap.get<number>("power_imbalance_streak") ?? 0;
  const pi_side = snap.get<string>("power_imbalance_streak_side");
  const exh_recent = snap.list<Record<string, unknown>>("trend_exhaustion_recent");
  const exh_streak = snap.get<number>("exhaustion_streak") ?? 0;
  const exh_type = snap.get<string>("exhaustion_streak_type");

  const piMaxRatio = useMemo(
    () =>
      pi_recent.reduce(
        (m, p) => Math.max(m, Math.abs(Number(p.ratio) || 0)),
        0,
      ),
    [pi_recent],
  );
  const exhMaxVal = useMemo(
    () =>
      exh_recent.reduce(
        (m, e) => Math.max(m, Number(e.exhaustion) || 0),
        0,
      ),
    [exh_recent],
  );

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* CHoCH 最新 + 近期列表 */}
      <IndicatorCard
        title="CHoCH 破位（最新）"
        hint="机构破坏 (CHoCH) / 突破延续 (BOS)；bars_since 越小越新鲜"
        empty={!choch_latest}
        emptyText="本周期暂无 CHoCH 事件"
      >
        {choch_latest && (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">事件类型</span>
              <span
                className={cn(
                  "num font-medium",
                  choch_latest.kind === "CHoCH" && "text-amber-400",
                )}
              >
                {fmt(choch_latest.kind)}_{fmt(choch_latest.direction)}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">触发价</span>
              <span className="num">{fmtPrice(choch_latest.price)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">破坏的水平</span>
              <span className="num">
                {fmtPrice(choch_latest.level_price)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(Number(choch_latest.distance_pct))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">距今</span>
              <span
                className={cn(
                  "num",
                  Number(choch_latest.bars_since) <= 6
                    ? "text-amber-400 font-medium"
                    : "text-muted-foreground",
                )}
              >
                {fmt(choch_latest.bars_since)} 根
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">事件时间</span>
              <span className="num text-[11px] text-muted-foreground">
                {fmtTime(choch_latest.ts)}
              </span>
            </div>
          </>
        )}
        {choch.length > 1 && (
          <div className="mt-3 border-t border-border/30 pt-2">
            <div className="text-[11px] text-muted-foreground">
              最近 {Math.min(choch.length - 1, 6)} 条历史：
            </div>
            <div className="mt-1 max-h-40 space-y-0.5 overflow-auto pr-1">
              {choch.slice(1, 7).map((c, i) => (
                <div
                  key={i}
                  className="flex items-baseline justify-between text-xs"
                >
                  <span className="num">{fmtPrice(c.level_price)}</span>
                  <span className="text-[11px] text-muted-foreground">
                    {fmt(c.kind)}_{fmt(c.direction)} · {fmt(c.bars_since)} 根前
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </IndicatorCard>

      {/* 流动性扫荡 */}
      <IndicatorCard
        title="流动性扫荡（liquidity_sweep）"
        hint="近窗扫损次数 + 最新事件方向"
      >
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">近窗次数</span>
          <span
            className={cn(
              "num font-medium",
              sweep_count >= 3 && "text-amber-400",
            )}
          >
            {fmtInt(sweep_count)}
          </span>
        </div>
        <ProgressBar
          value={Math.min(sweep_count, 10)}
          max={10}
          tone={sweep_count >= 3 ? "warn" : "primary"}
          className="mb-2"
        />
        {sweep_last ? (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">最新方向</span>
              <span
                className={cn(
                  "num font-medium",
                  sweep_last.type === "bullish_sweep" && "text-emerald-400",
                  sweep_last.type === "bearish_sweep" && "text-rose-400",
                )}
              >
                {fmt(sweep_last.type)}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">价位</span>
              <span className="num">
                {fmtPrice(sweep_last.price)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(sweep_last.price, last_price))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">成交量</span>
              <span className="num">{fmtInt(sweep_last.volume)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">时间</span>
              <span className="num text-[11px] text-muted-foreground">
                {fmtTime(sweep_last.ts)}
              </span>
            </div>
          </>
        ) : (
          <div className="text-xs text-muted-foreground">无最新扫荡事件</div>
        )}
      </IndicatorCard>

      {/* 能量失衡 */}
      <IndicatorCard
        title={`能量失衡（power_imbalance · 近 ${pi_recent.length}）`}
        hint="官方：连续 ≥3 根同向 → 行情发动"
      >
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">Streak</span>
          <span
            className={cn(
              "num font-medium",
              pi_streak >= 3 && "text-rose-400",
            )}
          >
            {fmtInt(pi_streak)} 根 ·{" "}
            <span
              className={cn(
                pi_side === "buy" && "text-emerald-400",
                pi_side === "sell" && "text-rose-400",
              )}
            >
              {fmt(pi_side)}
            </span>
          </span>
        </div>
        <ProgressBar
          value={Math.min(pi_streak, 5)}
          max={5}
          tone={pi_streak >= 3 ? "bad" : "warn"}
          className="mb-2"
        />
        {pi_recent.length > 0 ? (
          <div className="mt-2 max-h-56 space-y-1 overflow-auto border-t border-border/30 pt-2 pr-1">
            {pi_recent.slice(0, 12).map((p, i) => {
              const r = Number(p.ratio) || 0;
              return (
                <div key={i}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="num">{r.toFixed(3)}</span>
                    <span className="text-[11px] text-muted-foreground">
                      买 {fmtInt(p.buy_vol)} / 卖 {fmtInt(p.sell_vol)}
                      {" · "}
                      {fmtTime(p.ts)}
                    </span>
                  </div>
                  <ProgressBar
                    value={Math.abs(r)}
                    max={piMaxRatio || 1}
                    tone={r >= 0 ? "good" : "bad"}
                  />
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">无近窗事件</div>
        )}
      </IndicatorCard>

      {/* 趋势衰竭近窗 */}
      <IndicatorCard
        title={`趋势衰竭近窗（trend_exhaustion · ${exh_recent.length}）`}
        hint="逐根衰竭值序列；连续 ≥3 根 → 衰竭警报"
      >
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">Streak</span>
          <span
            className={cn(
              "num font-medium",
              exh_streak >= 3 && "text-rose-400",
            )}
          >
            {fmtInt(exh_streak)} 根 ·{" "}
            <span
              className={cn(
                exh_type === "Accumulation" && "text-emerald-400",
                exh_type === "Distribution" && "text-rose-400",
              )}
            >
              {fmt(exh_type)}
            </span>
          </span>
        </div>
        {exh_recent.length > 0 ? (
          <div className="mt-2 max-h-56 space-y-1 overflow-auto border-t border-border/30 pt-2 pr-1">
            {exh_recent.slice(0, 12).map((e, i) => (
              <div key={i}>
                <div className="flex items-baseline justify-between text-xs">
                  <span className="num">{fmt(e.exhaustion)}</span>
                  <span className="text-[11px] text-muted-foreground">
                    <span
                      className={cn(
                        e.type === "Accumulation" && "text-emerald-400",
                        e.type === "Distribution" && "text-rose-400",
                      )}
                    >
                      {fmt(e.type)}
                    </span>
                    {" · "}
                    {fmtTime(e.ts)}
                  </span>
                </div>
                <ProgressBar
                  value={Number(e.exhaustion) || 0}
                  max={exhMaxVal || 1}
                  tone={e.type === "Accumulation" ? "good" : "bad"}
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">无近窗衰竭事件</div>
        )}
      </IndicatorCard>
    </div>
  );
}

// ─────────────────────────────────────────────────────
// Tab 5 · 主力族
// ─────────────────────────────────────────────────────

function MainForceTab({ snap }: { snap: SnapAccess }) {
  const last_price = snap.lastPrice;
  const sm_ongoing = snap.get<Record<string, unknown>>("smart_money_ongoing");
  const sm_all = snap.list<Record<string, unknown>>("smart_money_all");
  const reso_recent = snap.list<Record<string, unknown>>("resonance_recent");
  const reso_buy = snap.get<number>("resonance_buy_count") ?? 0;
  const reso_sell = snap.get<number>("resonance_sell_count") ?? 0;
  const whale = snap.get<string>("whale_net_direction");
  const heat = snap.get<Record<string, unknown>>("time_heatmap_view");

  const peakHours = (heat?.peak_hours as number[] | undefined) ?? [];
  const deadHours = (heat?.dead_hours as number[] | undefined) ?? [];
  const currentHour = Number(heat?.current_hour ?? -1);
  const currentRank = Number(heat?.current_rank ?? 0);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* 聪明钱成本 */}
      <IndicatorCard
        title="聪明钱成本（smart_money）"
        hint="主力建仓段及成本均价；ongoing = 进行中段"
        empty={!sm_ongoing && sm_all.length === 0}
      >
        {sm_ongoing && (
          <div className="rounded-md border border-primary/30 bg-primary/5 p-2">
            <div className="text-[11px] uppercase tracking-wider text-primary/80">
              进行中段
            </div>
            <div className="mt-1 flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">类型</span>
              <span
                className={cn(
                  "num font-medium",
                  sm_ongoing.type === "Accumulation"
                    ? "text-emerald-400"
                    : "text-rose-400",
                )}
              >
                {fmt(sm_ongoing.type)}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">建仓均价</span>
              <span className="num font-medium">
                {fmtPrice(sm_ongoing.avg_price)}
                <span className="ml-2 text-[11px] text-muted-foreground">
                  {fmtDistance(distPct(sm_ongoing.avg_price, last_price))}
                </span>
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">起始</span>
              <span className="num text-[11px] text-muted-foreground">
                {fmtTime(sm_ongoing.start_time)}
              </span>
            </div>
          </div>
        )}
        {sm_all.length > 0 && (
          <div className="mt-3 border-t border-border/30 pt-2">
            <div className="text-[11px] text-muted-foreground">
              历史段（共 {sm_all.length}，按时间倒序前 8 条）
            </div>
            <div className="mt-1 max-h-40 space-y-0.5 overflow-auto pr-1">
              {sm_all.slice(0, 8).map((s, i) => (
                <div
                  key={i}
                  className="flex items-baseline justify-between text-xs"
                >
                  <span className="num">
                    {fmtPrice(s.avg_price)}
                    <span className="ml-2 text-[11px] text-muted-foreground">
                      {fmtDistance(distPct(s.avg_price, last_price))}
                    </span>
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    <span
                      className={cn(
                        s.type === "Accumulation" && "text-emerald-400",
                        s.type === "Distribution" && "text-rose-400",
                      )}
                    >
                      {fmt(s.type)}
                    </span>
                    {" · "}
                    {fmtTime(s.start_time)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </IndicatorCard>

      {/* 跨所共振 + 巨鲸方向 */}
      <IndicatorCard
        title={`跨所共振（resonance · 近 ${reso_recent.length}）`}
        hint="多平台同向异常大单 + 巨鲸净方向"
      >
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">巨鲸净方向</span>
          <span
            className={cn(
              "num font-medium",
              whale === "buy" && "text-emerald-400",
              whale === "sell" && "text-rose-400",
            )}
          >
            {fmt(whale)}
          </span>
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <div>
            <div className="flex items-baseline justify-between text-[11px]">
              <span className="text-emerald-400/80">买盘共振</span>
              <span className="num">{fmtInt(reso_buy)}</span>
            </div>
            <ProgressBar
              value={reso_buy}
              max={Math.max(reso_buy + reso_sell, 1)}
              tone="good"
            />
          </div>
          <div>
            <div className="flex items-baseline justify-between text-[11px]">
              <span className="text-rose-400/80">卖盘共振</span>
              <span className="num">{fmtInt(reso_sell)}</span>
            </div>
            <ProgressBar
              value={reso_sell}
              max={Math.max(reso_buy + reso_sell, 1)}
              tone="bad"
            />
          </div>
        </div>
        {reso_recent.length > 0 && (
          <div className="mt-3 border-t border-border/30 pt-2">
            <div className="text-[11px] text-muted-foreground">
              最近 {Math.min(reso_recent.length, 6)} 条：
            </div>
            <div className="mt-1 max-h-40 space-y-0.5 overflow-auto pr-1">
              {reso_recent.slice(0, 6).map((r, i) => (
                <div
                  key={i}
                  className="flex items-baseline justify-between text-xs"
                >
                  <span className="num">
                    {fmtPrice(r.price)}
                    <span className="ml-2 text-[11px] text-muted-foreground">
                      {fmtDistance(distPct(r.price, last_price))}
                    </span>
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    <span
                      className={cn(
                        r.direction === "buy" && "text-emerald-400",
                        r.direction === "sell" && "text-rose-400",
                      )}
                    >
                      {fmt(r.direction)}
                    </span>
                    {" · ×"}
                    {fmt(r.count)}
                    {" · "}
                    {fmtTime(r.ts)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </IndicatorCard>

      {/* 时间热力图 24h */}
      <IndicatorCard
        title="时间热力图（time_heatmap · 24h）"
        hint="UTC 24 小时活跃度；rank 越小越活跃，1 = 当日最活跃"
        empty={!heat}
        className="lg:col-span-2"
      >
        {heat && (
          <>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">当前小时（UTC）</span>
              <span
                className={cn(
                  "num font-medium",
                  heat.is_active_session ? "text-emerald-400" : "text-amber-400",
                )}
              >
                {currentHour >= 0 ? `${currentHour}:00` : "—"}
                {" · "}
                rank #{currentRank}
                {" · "}
                {heat.is_active_session ? "活跃" : "垃圾时段"}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">当前活跃度</span>
              <span className="num">
                {fmtPctSafe(heat.current_activity)}
              </span>
            </div>
            <ProgressBar
              value={Number(heat.current_activity ?? 0)}
              max={1}
              tone={heat.is_active_session ? "good" : "warn"}
              className="mb-3"
            />

            {/* 24 小时迷你热力 */}
            <div className="text-[11px] text-muted-foreground">24h 分布：</div>
            <div className="mt-1 grid grid-cols-12 gap-0.5">
              {Array.from({ length: 24 }).map((_, h) => {
                const isPeak = peakHours.includes(h);
                const isDead = deadHours.includes(h);
                const isCurrent = h === currentHour;
                return (
                  <div
                    key={h}
                    className={cn(
                      "flex h-6 items-center justify-center rounded-sm text-[9px]",
                      isPeak && "bg-emerald-500/30 text-emerald-200",
                      isDead && "bg-rose-500/20 text-rose-300",
                      !isPeak && !isDead && "bg-secondary/30 text-muted-foreground",
                      isCurrent && "ring-1 ring-primary",
                    )}
                  >
                    {h}
                  </div>
                );
              })}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
              <span>
                Peak：
                <span className="text-emerald-400">
                  {peakHours.length > 0 ? peakHours.join(", ") : "—"}
                </span>
              </span>
              <span>
                Dead：
                <span className="text-rose-400">
                  {deadHours.length > 0 ? deadHours.join(", ") : "—"}
                </span>
              </span>
            </div>
          </>
        )}
      </IndicatorCard>
    </div>
  );
}

// ─────────────────────────────────────────────────────
// 白话总结派生（纯前端，不调 LLM）
// ─────────────────────────────────────────────────────

type BriefingTone = "good" | "bad" | "warn" | "neutral";

interface Briefing {
  tone: BriefingTone;
  headline: string;
  lines: string[];   // 每条独立要点
}

/** 把数字百分比 (0.0212 → "+2.12%") 直观化 */
const pctText = (v: number | undefined | null, withSign = true): string => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  const sign = withSign && v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(2)}%`;
};

/** 整体市场白话总结。融合 5 类核心信号，挑出最有意义的 4-5 句。 */
function marketBriefing(snap: SnapAccess): Briefing {
  const lp = snap.lastPrice;
  const purity = snap.get<Record<string, unknown>>("trend_purity_last");
  const sat = snap.get<Record<string, unknown>>("trend_saturation");
  const cvdSign = snap.get<string>("cvd_slope_sign");
  const fvDelta = snap.get<number>("fair_value_delta_pct");
  const exhStreak = snap.get<number>("exhaustion_streak") ?? 0;
  const choch = snap.get<Record<string, unknown>>("choch_latest");
  const ns = snap.get<number>("nearest_support_price");
  const nsDist = snap.get<number>("nearest_support_distance_pct");
  const nr = snap.get<number>("nearest_resistance_price");
  const nrDist = snap.get<number>("nearest_resistance_distance_pct");
  const whale = snap.get<string>("whale_net_direction");
  const heat = snap.get<Record<string, unknown>>("time_heatmap_view");
  const smart = snap.get<Record<string, unknown>>("smart_money_ongoing");

  // 综合方向倾向（粗糙启发式）
  let bullishVote = 0;
  let bearishVote = 0;
  if (purity?.type === "Accumulation") bullishVote += 1;
  if (purity?.type === "Distribution") bearishVote += 1;
  if (cvdSign === "up") bullishVote += 1;
  if (cvdSign === "down") bearishVote += 1;
  if (typeof fvDelta === "number") {
    if (fvDelta > 0.005) bullishVote += 1;
    else if (fvDelta < -0.005) bearishVote += 1;
  }
  if (whale === "buy") bullishVote += 1;
  if (whale === "sell") bearishVote += 1;
  const direction =
    bullishVote > bearishVote + 1
      ? "偏多"
      : bearishVote > bullishVote + 1
        ? "偏空"
        : "中性";
  const tone: BriefingTone =
    direction === "偏多" ? "good" : direction === "偏空" ? "bad" : "warn";

  const lines: string[] = [];

  // 1. 趋势画像
  if (purity || sat) {
    const purityVal =
      typeof purity?.purity === "number" ? (purity.purity as number) : null;
    const satProg =
      typeof sat?.progress === "number" ? (sat.progress as number) : null;
    const stage =
      purity?.type === "Accumulation"
        ? "吸筹/上行段"
        : purity?.type === "Distribution"
          ? "派发/下行段"
          : "无明显段";
    const satWord =
      satProg === null ? "" : satProg >= 0.9 ? "已饱和" : satProg >= 0.85 ? "接近饱和" : "饱和度健康";
    lines.push(
      `当前阶段：${stage}${
        purityVal !== null ? `（纯度 ${purityVal.toFixed(0)}/100）` : ""
      }${satProg !== null ? `，饱和度 ${(satProg * 100).toFixed(1)}% ${satWord}` : ""}。`,
    );
  }

  // 2. 价位 vs VWAP
  if (typeof fvDelta === "number" && Number.isFinite(fvDelta)) {
    const direction2 = fvDelta > 0 ? "高于" : "低于";
    lines.push(
      `价格 ${direction2} VWAP 公允价 ${pctText(fvDelta)}${
        Math.abs(fvDelta) > 0.02 ? "（乖离偏大）" : ""
      }；CVD 方向 ${cvdSign ?? "—"}。`,
    );
  }

  // 3. 关键位
  const supportLine =
    typeof ns === "number" && typeof nsDist === "number"
      ? `下方支撑 \`${formatPrice(ns)}\`（${pctText(nsDist)}）`
      : null;
  const resistLine =
    typeof nr === "number" && typeof nrDist === "number"
      ? `上方阻力 \`${formatPrice(nr)}\`（${pctText(nrDist)}）`
      : null;
  if (supportLine || resistLine) {
    lines.push(
      `${[resistLine, supportLine].filter(Boolean).join("，")}${
        lp ? `；当前价 \`${formatPrice(lp)}\`` : ""
      }。`,
    );
  }

  // 4. CHoCH 警报
  if (choch) {
    const dir =
      choch.direction === "bullish" ? "向上" : choch.direction === "bearish" ? "向下" : "—";
    const bs = typeof choch.bars_since === "number" ? `${choch.bars_since} 根前` : "近期";
    lines.push(
      `${bs}发生 ${choch.kind ?? "CHoCH/BOS"} ${dir}破位，触发价 \`${formatPrice(choch.price as number)}\`。`,
    );
  }

  // 5. 衰竭警报
  if (exhStreak >= 3) {
    lines.push(
      `**趋势衰竭警报**：连续 ${exhStreak} 根（${
        snap.get<string>("exhaustion_streak_type") ?? "—"
      }），动能耗尽。`,
    );
  }

  // 6. 主力 / 时间
  const sessionFlag = heat?.is_active_session;
  const sessionStr =
    sessionFlag === true ? "活跃时段" : sessionFlag === false ? "**垃圾时段**" : "";
  const smartType = smart?.type;
  if (smartType || whale || sessionStr) {
    const parts: string[] = [];
    if (smartType)
      parts.push(`聪明钱进行中段：${smartType === "Accumulation" ? "吸筹" : "派发"}`);
    if (whale && whale !== "neutral")
      parts.push(`巨鲸方向 ${whale === "buy" ? "买" : "卖"}`);
    if (sessionStr) parts.push(sessionStr);
    if (parts.length > 0) lines.push(`${parts.join("，")}。`);
  }

  return {
    tone,
    headline: `综合判断：${direction}`,
    lines,
  };
}

function trendBriefing(snap: SnapAccess): Briefing {
  const purity = snap.get<Record<string, unknown>>("trend_purity_last");
  const sat = snap.get<Record<string, unknown>>("trend_saturation");
  const cvdSign = snap.get<string>("cvd_slope_sign");
  const cvdConv = snap.get<number>("cvd_converge_ratio");
  const fvDelta = snap.get<number>("fair_value_delta_pct");
  const pocTrend = snap.get<string>("poc_shift_trend");
  const exhStreak = snap.get<number>("exhaustion_streak") ?? 0;

  const lines: string[] = [];
  if (purity) {
    const stage =
      purity.type === "Accumulation"
        ? "吸筹/多头主导"
        : purity.type === "Distribution"
          ? "派发/空头主导"
          : "—";
    lines.push(
      `**段类型**：${stage}（纯度 ${
        typeof purity.purity === "number" ? (purity.purity as number).toFixed(0) : "—"
      }/100）。`,
    );
  }
  if (sat) {
    const prog = Number(sat.progress ?? 0);
    const word = prog >= 0.9 ? "已饱和（信号降级）" : prog >= 0.85 ? "接近饱和" : "健康";
    lines.push(`**饱和度**：${(prog * 100).toFixed(1)}% — ${word}。`);
  }
  if (typeof fvDelta === "number") {
    lines.push(
      `**VWAP 乖离**：${pctText(fvDelta)} — 价${fvDelta > 0 ? "高于" : "低于"}公允价${
        Math.abs(fvDelta) > 0.02 ? "（偏大）" : ""
      }。`,
    );
  }
  const cvdWord =
    typeof cvdConv === "number"
      ? cvdConv < 0.05
        ? "极度收敛（多空对冲）"
        : cvdConv < 0.3
          ? "弱方向"
          : "明确方向"
      : "—";
  lines.push(`**CVD 方向**：${cvdSign ?? "—"}（收敛比 ${pctText(cvdConv)} · ${cvdWord}）。`);
  if (pocTrend) lines.push(`**POC 漂移方向**：${pocTrend}。`);
  if (exhStreak >= 3) {
    lines.push(`**衰竭警报**：连续 ${exhStreak} 根 — 动能耗尽。`);
  }

  const tone: BriefingTone =
    purity?.type === "Accumulation" && cvdSign === "up"
      ? "good"
      : purity?.type === "Distribution" && cvdSign === "down"
        ? "bad"
        : exhStreak >= 3
          ? "warn"
          : "neutral";
  return {
    tone,
    headline: "趋势画像",
    lines,
  };
}

function valueBriefing(snap: SnapAccess): Briefing {
  const vp = snap.get<Record<string, unknown>>("volume_profile");
  const hvn = snap.list("hvn_nodes");
  const ob = snap.list("order_blocks");
  const az = snap.list("absolute_zones");
  const ns = snap.get<number>("nearest_support_price");
  const nsDist = snap.get<number>("nearest_support_distance_pct");
  const nr = snap.get<number>("nearest_resistance_price");
  const nrDist = snap.get<number>("nearest_resistance_distance_pct");

  const lines: string[] = [];
  if (vp) {
    const pos =
      vp.last_price_position === "in_va"
        ? "**Value Area 内**（公允区间，关注突破）"
        : vp.last_price_position === "above_va"
          ? "**Value Area 上方**（高位，警惕回归）"
          : "**Value Area 下方**（低位，关注反弹）";
    lines.push(`价位位置：${pos}。`);
    if (typeof vp.poc_distance_pct === "number") {
      lines.push(
        `POC \`${formatPrice(vp.poc_price as number)}\` 距现价 ${pctText(
          vp.poc_distance_pct as number,
        )}。`,
      );
    }
  }
  if (typeof nr === "number" && typeof nrDist === "number") {
    lines.push(`上方最近阻力：\`${formatPrice(nr)}\`（${pctText(nrDist)}）。`);
  }
  if (typeof ns === "number" && typeof nsDist === "number") {
    lines.push(`下方最近支撑：\`${formatPrice(ns)}\`（${pctText(nsDist)}）。`);
  }
  lines.push(
    `**关键位规模**：HVN ${hvn.length} 节点 · 订单块 ${ob.length} 段 · 绝对区域 ${az.length} 段。`,
  );

  const tone: BriefingTone =
    vp?.last_price_position === "in_va" ? "neutral" : "warn";
  return { tone, headline: "价值带画像", lines };
}

function liquidityBriefing(snap: SnapAccess): Briefing {
  const cascades = snap.list<Record<string, unknown>>("cascade_bands");
  const retails = snap.list<Record<string, unknown>>("retail_stop_bands");
  const vacuums = snap.list<Record<string, unknown>>("vacuums");
  const heat = snap.list<Record<string, unknown>>("heatmap");
  const fuel = snap.list<Record<string, unknown>>("liquidation_fuel");

  const above = (xs: Record<string, unknown>[]) =>
    xs.filter((b) => Number(b.distance_pct ?? 0) > 0).length;
  const below = (xs: Record<string, unknown>[]) =>
    xs.filter((b) => Number(b.distance_pct ?? 0) <= 0).length;

  const lines: string[] = [];

  // 最近的爆仓带
  const allCascadeSorted = [...cascades].sort(
    (a, b) => Math.abs(Number(a.distance_pct ?? 1)) - Math.abs(Number(b.distance_pct ?? 1)),
  );
  const nearest = allCascadeSorted[0];
  if (nearest) {
    const distPct = Number(nearest.distance_pct ?? 0);
    const direction = distPct > 0 ? "上方" : "下方";
    lines.push(
      `**最近爆仓带**：${direction} \`${formatPrice(
        nearest.avg_price as number,
      )}\`（${pctText(distPct)}） · ${nearest.side ?? "—"}。`,
    );
  }

  lines.push(
    `**爆仓带**：上方 ${above(cascades)} 条 / 下方 ${below(cascades)} 条；散户止损：上方 ${above(
      retails,
    )} / 下方 ${below(retails)}。`,
  );
  if (heat.length > 0)
    lines.push(`**爆仓热力**：上方 ${above(heat)} 区 / 下方 ${below(heat)} 区。`);
  if (fuel.length > 0)
    lines.push(`**爆仓燃料**：上方 ${above(fuel)} / 下方 ${below(fuel)}。`);
  if (vacuums.length > 0)
    lines.push(`**真空带**：上方 ${above(vacuums)} / 下方 ${below(vacuums)} — 流动性枯竭区。`);

  const aboveCount = above(cascades) + above(retails);
  const belowCount = below(cascades) + below(retails);
  const tone: BriefingTone =
    aboveCount > belowCount * 1.5
      ? "bad"
      : belowCount > aboveCount * 1.5
        ? "good"
        : "neutral";
  return { tone, headline: "流动性地图", lines };
}

function structureBriefing(snap: SnapAccess): Briefing {
  const choch = snap.get<Record<string, unknown>>("choch_latest");
  const chochs = snap.list("choch_recent");
  const sweepCount = snap.get<number>("sweep_count_recent") ?? 0;
  const sweepLast = snap.get<Record<string, unknown>>("sweep_last");
  const piStreak = snap.get<number>("power_imbalance_streak") ?? 0;
  const piSide = snap.get<string>("power_imbalance_streak_side");
  const exhStreak = snap.get<number>("exhaustion_streak") ?? 0;

  const lines: string[] = [];
  if (choch) {
    const dir =
      choch.direction === "bullish" ? "向上突破" : choch.direction === "bearish" ? "向下破位" : "—";
    const bs = typeof choch.bars_since === "number" ? `${choch.bars_since} 根前` : "近期";
    lines.push(
      `${bs} **${choch.kind ?? "CHoCH/BOS"}** ${dir} @ \`${formatPrice(choch.price as number)}\`（被砸穿前高/前低 \`${formatPrice(choch.level_price as number)}\`）。`,
    );
  } else {
    lines.push(`本周期暂无 CHoCH/BOS 破位事件（最近 ${chochs.length} 根扫描结果）。`);
  }

  if (sweepLast) {
    const dir = (sweepLast.direction as string) === "up" ? "向上" : "向下";
    lines.push(`**流动性扫荡**：近窗 ${sweepCount} 次，最近一次 ${dir}扫损。`);
  } else {
    lines.push(`**流动性扫荡**：近窗 0 次（市场没有显著扫损动作）。`);
  }

  if (piStreak >= 3) {
    lines.push(`**能量失衡**：连续 ${piStreak} 根（${piSide}） — 行情发动信号。`);
  } else {
    lines.push(`**能量失衡**：streak ${piStreak} 根（< 3，未触发发动）。`);
  }

  if (exhStreak >= 3) {
    lines.push(`**趋势衰竭近窗**：连续 ${exhStreak} 根 — 反转风险升高。`);
  }

  const tone: BriefingTone =
    choch || sweepCount > 2 || piStreak >= 3
      ? "warn"
      : exhStreak >= 3
        ? "bad"
        : "neutral";
  return { tone, headline: "结构事件画像", lines };
}

function mainForceBriefing(snap: SnapAccess): Briefing {
  const smart = snap.get<Record<string, unknown>>("smart_money_ongoing");
  const reso = snap.get<number>("resonance_count_recent") ?? 0;
  const resoBuy = snap.get<number>("resonance_buy_count") ?? 0;
  const resoSell = snap.get<number>("resonance_sell_count") ?? 0;
  const whale = snap.get<string>("whale_net_direction");
  const heat = snap.get<Record<string, unknown>>("time_heatmap_view");

  const lines: string[] = [];
  if (smart) {
    const stage = smart.type === "Accumulation" ? "**吸筹**" : "**派发**";
    lines.push(
      `**聪明钱进行中段**：${stage}，建仓均价 \`${formatPrice(
        smart.avg_price as number,
      )}\`${smart.start_time ? `（起始 ${fmtTime(smart.start_time)}）` : ""}。`,
    );
  } else {
    lines.push(`**聪明钱**：当前无进行中段。`);
  }

  if (reso > 0) {
    lines.push(
      `**跨所共振**：近窗 ${reso} 次（买 ${resoBuy} / 卖 ${resoSell}）— 多平台同向异常大单。`,
    );
  } else {
    lines.push(`**跨所共振**：近窗 0 次（无显著多平台共振）。`);
  }

  if (whale && whale !== "neutral") {
    lines.push(
      `**巨鲸方向**：${whale === "buy" ? "**买入主导**" : "**卖出主导**"}。`,
    );
  } else {
    lines.push(`**巨鲸方向**：中性（无明显单边）。`);
  }

  if (heat) {
    const session = heat.is_active_session ? "**活跃时段**（信号有效）" : "**垃圾时段**（信号慎重）";
    const rank = heat.current_rank;
    lines.push(
      `**时段**：UTC ${typeof heat.current_hour === "number" ? heat.current_hour : "—"}:00 · rank #${rank ?? "—"} — ${session}。`,
    );
  }

  const tone: BriefingTone =
    smart?.type === "Accumulation" && (whale === "buy" || resoBuy > resoSell)
      ? "good"
      : smart?.type === "Distribution" && (whale === "sell" || resoSell > resoBuy)
        ? "bad"
        : "neutral";
  return { tone, headline: "主力族画像", lines };
}

function categoryBriefing(kind: CategoryKey, snap: SnapAccess): Briefing {
  switch (kind) {
    case "trend":
      return trendBriefing(snap);
    case "value":
      return valueBriefing(snap);
    case "liquidity":
      return liquidityBriefing(snap);
    case "structure":
      return structureBriefing(snap);
    case "main_force":
      return mainForceBriefing(snap);
  }
}

/** 渲染白话总结面板：左边色条 + headline + 列表，染色随 tone。 */
function BriefingPanel({
  brief,
  variant = "category",
}: {
  brief: Briefing;
  variant?: "market" | "category";
}) {
  const toneClass =
    brief.tone === "good"
      ? "border-emerald-500/40 bg-emerald-500/5"
      : brief.tone === "bad"
        ? "border-rose-500/40 bg-rose-500/5"
        : brief.tone === "warn"
          ? "border-amber-500/40 bg-amber-500/5"
          : "border-border/50 bg-card/40";
  const headTone =
    brief.tone === "good"
      ? "text-emerald-400"
      : brief.tone === "bad"
        ? "text-rose-400"
        : brief.tone === "warn"
          ? "text-amber-400"
          : "text-foreground";
  return (
    <div className={cn("rounded-lg border p-3 sm:p-4", toneClass)}>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-block h-4 w-1 rounded",
            brief.tone === "good" && "bg-emerald-400",
            brief.tone === "bad" && "bg-rose-400",
            brief.tone === "warn" && "bg-amber-400",
            brief.tone === "neutral" && "bg-primary/60",
          )}
        />
        <span
          className={cn(
            "text-xs uppercase tracking-[0.18em]",
            variant === "market" ? "text-muted-foreground" : "text-muted-foreground/80",
          )}
        >
          {variant === "market" ? "白话总览（小白指南）" : "本类指标白话总结"}
        </span>
        <span className={cn("text-sm font-semibold", headTone)}>· {brief.headline}</span>
      </div>
      {brief.lines.length > 0 ? (
        <ul className="mt-2 space-y-1 text-sm leading-relaxed">
          {brief.lines.map((l, i) => (
            <li key={i} className="flex gap-2 text-foreground/90">
              <span className="text-muted-foreground/60">·</span>
              <span dangerouslySetInnerHTML={{ __html: htmlBriefingLine(l) }} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 text-sm text-muted-foreground">
          数据不足，无法给出白话结论。
        </div>
      )}
    </div>
  );
}

/** 把简单 markdown（**bold** 和 反引号 code）渲染成 HTML。
 * 仅在 BriefingPanel 内部受控字符串使用，避免 XSS（输入全部来自 snapshot 数值/枚举）。 */
function htmlBriefingLine(s: string): string {
  const escaped = s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-foreground">$1</strong>')
    .replace(
      /`([^`]+)`/g,
      '<code class="num rounded bg-secondary/40 px-1 py-0.5 text-[12px] text-primary">$1</code>',
    );
}

// ─────────────────────────────────────────────────────
// 页面主体
// ─────────────────────────────────────────────────────

export default function IndicatorsPage() {
  const symbol = useSymbolStore((s) => s.symbol);
  const tf = useSymbolStore((s) => s.tf);
  const [active, setActive] = useState<CategoryKey>("trend");

  const query = useQuery({
    queryKey: ["indicators-panorama", symbol, tf],
    queryFn: () => fetchIndicatorsPanorama(symbol, tf),
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const snap = useMemo(
    () => makeAccess(query.data ?? {}),
    [query.data],
  );

  const last_price = snap.get<number>("last_price");
  const anchor_ts = snap.get<number>("anchor_ts");
  const stale = snap.list<string>("stale_tables");

  const hasData = !query.isLoading && !query.isError && Boolean(query.data);
  const market = useMemo(
    () => (hasData ? marketBriefing(snap) : null),
    [hasData, snap],
  );
  const cat = useMemo(
    () => (hasData ? categoryBriefing(active, snap) : null),
    [hasData, active, snap],
  );

  return (
    <div className="grid gap-4">
      {/* 页头：标题 + 刷新 + meta */}
      <div className="panel-glass flex flex-wrap items-center justify-between gap-3 rounded-lg p-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            指标全景
          </div>
          <div className="mt-1 flex items-baseline gap-3">
            <span className="text-lg font-semibold">
              {symbol} · {tf}
            </span>
            <span className="text-sm text-muted-foreground">
              当前价 <span className="num">{fmtPrice(last_price)}</span>
            </span>
            {anchor_ts && (
              <span className="text-xs text-muted-foreground">
                · 锚点 {fmtTime(anchor_ts)}
              </span>
            )}
            {query.dataUpdatedAt > 0 && (
              <span className="text-xs text-muted-foreground">
                · 已刷新 {new Date(query.dataUpdatedAt).toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {stale.length > 0 && (
            <Badge variant="warning" className="gap-1">
              <AlertTriangle className="h-3.5 w-3.5" />
              {stale.length} 表无数据
            </Badge>
          )}
          <button
            type="button"
            onClick={() => query.refetch()}
            disabled={query.isFetching}
            className="flex items-center gap-1.5 rounded-md border border-border/60 bg-secondary/40 px-3 py-1.5 text-sm text-foreground/90 transition-colors hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {query.isFetching ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            刷新
          </button>
        </div>
      </div>

      {/* 整体白话总览 */}
      {market && <BriefingPanel brief={market} variant="market" />}

      {/* 5 个分类 sub-tab */}
      <div className="panel-glass rounded-lg p-2">
        <div className="flex flex-wrap gap-1">
          {CATEGORIES.map((c) => {
            const Icon = c.icon;
            const isActive = active === c.key;
            return (
              <button
                key={c.key}
                type="button"
                onClick={() => setActive(c.key)}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary/15 text-primary"
                    : "text-muted-foreground hover:bg-secondary/40 hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {c.label}
              </button>
            );
          })}
        </div>
        <div className="mt-2 px-2 text-[11px] text-muted-foreground">
          {CATEGORIES.find((c) => c.key === active)?.hint}
        </div>
      </div>

      {/* 内容区 */}
      {query.isLoading && (
        <div className="panel-glass flex items-center justify-center gap-2 rounded-lg p-12 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          加载指标全景…
        </div>
      )}

      {query.isError && (
        <div className="panel-glass rounded-lg border-rose-500/40 p-6 text-rose-300">
          加载失败：
          {(query.error as Error & { friendly?: string })?.friendly ??
            (query.error as Error).message}
        </div>
      )}

      {!query.isLoading && !query.isError && (
        <>
          {cat && <BriefingPanel brief={cat} variant="category" />}
          {active === "trend" && <TrendTab snap={snap} />}
          {active === "value" && <ValueTab snap={snap} />}
          {active === "liquidity" && <LiquidityTab snap={snap} />}
          {active === "structure" && <StructureTab snap={snap} />}
          {active === "main_force" && <MainForceTab snap={snap} />}
        </>
      )}

      {/* 底部小提示 */}
      <div className="panel-glass rounded-lg p-3 text-center text-[11px] text-muted-foreground">
        指标全景每 30s 自动刷新一次；切换 symbol/tf 时数据立即跟随。所有数据来自
        backend · FeatureSnapshot.{"{trend|value|liquidity|...}"}。
      </div>
    </div>
  );
}
