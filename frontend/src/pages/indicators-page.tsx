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
    hint: "趋势纯度 / CVD 累积 / POC 漂移 / 饱和度 / 衰竭",
  },
  {
    key: "value",
    label: "价值带族",
    icon: Layers,
    hint: "HVN 节点 / 绝对区域 / Order Block / Volume Profile / 微观 POC",
  },
  {
    key: "liquidity",
    label: "流动性族",
    icon: Waves,
    hint: "真空带 / 爆仓热力 / 爆仓燃料 / 散户止损 / 连环爆仓",
  },
  {
    key: "structure",
    label: "结构事件",
    icon: AlertTriangle,
    hint: "CHoCH 破位 / 流动性扫荡 / 能量失衡 / 趋势衰竭",
  },
  {
    key: "main_force",
    label: "主力族",
    icon: Crown,
    hint: "聪明钱成本 / 跨所共振 / 巨鲸方向 / 移动 VWAP",
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

const fmtPctSafe = (v: unknown): string => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return formatPct(v);
};

const fmtPrice = (v: unknown): string => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return formatPrice(v);
};

// ─────────────────────────────────────────────────────
// 卡片基类
// ─────────────────────────────────────────────────────

interface IndicatorCardProps {
  title: string;
  hint?: string;
  empty?: boolean;
  emptyText?: string;
  rows?: { label: string; value: React.ReactNode; tone?: "good" | "bad" | "neutral" }[];
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

// ─────────────────────────────────────────────────────
// 五类 Tab 渲染
// ─────────────────────────────────────────────────────

interface SnapAccess {
  raw: Record<string, unknown>;
  get: <T = unknown>(key: string) => T | undefined;
  list: <T = Record<string, unknown>>(key: string) => T[];
}

function makeAccess(raw: Record<string, unknown>): SnapAccess {
  return {
    raw,
    get: <T = unknown,>(key: string) => raw[key] as T | undefined,
    list: <T = Record<string, unknown>,>(key: string) =>
      (Array.isArray(raw[key]) ? (raw[key] as T[]) : []) as T[],
  };
}

// ── 趋势族 ──
function TrendTab({ snap }: { snap: SnapAccess }) {
  const purity = snap.get<Record<string, unknown>>("trend_purity_last");
  const sat = snap.get<Record<string, unknown>>("trend_saturation");
  const cvd_sign = snap.get<string>("cvd_slope_sign");
  const exh_streak = snap.get<number>("exhaustion_streak");
  const exh_type = snap.get<string>("exhaustion_streak_type");
  const exh_last = snap.get<Record<string, unknown>>("trend_exhaustion_last");

  return (
    <div className="grid gap-4 lg:grid-cols-3 xl:grid-cols-4">
      <IndicatorCard
        title="趋势纯度（trend_purity）"
        hint="拐点频率 / 最大回撤"
        empty={!purity}
        emptyText="该周期无趋势纯度段"
        rows={
          purity && [
            { label: "类型", value: fmt(purity.type) },
            { label: "纯度", value: fmtPctSafe(purity.purity) },
            { label: "段内最大回撤", value: fmtPctSafe(purity.max_dd_pct) },
            { label: "持续根数", value: fmt(purity.bars) },
          ]
        }
      />

      <IndicatorCard
        title="趋势饱和度（trend_saturation）"
        hint="离亡线/均线还有几根"
        empty={!sat}
        emptyText="无饱和度数据"
        rows={
          sat && [
            { label: "状态", value: fmt(sat.status) },
            { label: "至均价目标", value: fmt(sat.bars_to_avg) + " 根" },
            { label: "至最大目标", value: fmt(sat.bars_to_max) + " 根" },
            { label: "持续根数", value: fmt(sat.bars_held) },
          ]
        }
      />

      <IndicatorCard
        title="CVD 累积（cvd_slope）"
        hint="lookback 窗内净买盘累积方向"
        rows={[
          {
            label: "斜率方向",
            value: cvd_sign ?? "—",
            tone:
              cvd_sign === "up" ? "good" : cvd_sign === "down" ? "bad" : "neutral",
          },
          {
            label: "斜率值",
            value: fmt(snap.get("cvd_slope")),
          },
          {
            label: "收敛比",
            value: fmtPctSafe(snap.get("cvd_converge_ratio")),
          },
          {
            label: "imbalance 绿/红",
            value: `${fmtPctSafe(snap.get("imbalance_green_ratio"))} / ${fmtPctSafe(snap.get("imbalance_red_ratio"))}`,
          },
        ]}
      />

      <IndicatorCard
        title="POC 漂移（poc_shift）"
        hint="价值中枢方向"
        rows={[
          {
            label: "趋势",
            value: fmt(snap.get("poc_shift_trend")),
            tone:
              snap.get<string>("poc_shift_trend") === "up"
                ? "good"
                : snap.get<string>("poc_shift_trend") === "down"
                  ? "bad"
                  : "neutral",
          },
          {
            label: "百分比变化",
            value: fmtPctSafe(snap.get("poc_shift_delta_pct")),
          },
          {
            label: "VWAP 位置",
            value: fmtPrice(snap.get("vwap_last")),
          },
          {
            label: "对 VWAP 偏离",
            value: fmtPctSafe(snap.get("fair_value_delta_pct")),
          },
        ]}
      />

      <IndicatorCard
        title="趋势衰竭（trend_exhaustion）"
        hint="官方口径：连续 ≥3 根"
        rows={[
          {
            label: "Streak 根数",
            value: fmt(exh_streak),
            tone: (exh_streak ?? 0) >= 3 ? "bad" : "neutral",
          },
          { label: "Streak 类型", value: fmt(exh_type) },
          {
            label: "最近一条 type",
            value: exh_last ? fmt(exh_last.type) : "—",
          },
          {
            label: "最近一条 strength",
            value: exh_last ? fmt(exh_last.exhaustion) : "—",
          },
        ]}
      />

      <IndicatorCard
        title="趋势 ROI 耗尽（roi_segment）"
        hint="目标价 + 死亡线"
        rows={[
          {
            label: "T1 平均目标",
            value: fmtPrice(
              snap.get<Record<string, unknown>>("segment_portrait")
                ?.roi_limit_avg_price,
            ),
          },
          {
            label: "T2 极限目标",
            value: fmtPrice(
              snap.get<Record<string, unknown>>("segment_portrait")
                ?.roi_limit_max_price,
            ),
          },
          {
            label: "至均根数",
            value: fmt(
              snap.get<Record<string, unknown>>("segment_portrait")?.bars_to_avg,
            ),
          },
          {
            label: "至亡线",
            value: fmt(
              snap.get<Record<string, unknown>>("segment_portrait")?.bars_to_max,
            ),
          },
        ]}
      />

      <IndicatorCard
        title="最大回撤容忍（dd_tolerance）"
        hint="护城河 + 击穿次数"
        rows={[
          {
            label: "护城河当前",
            value: fmtPrice(
              snap.get<Record<string, unknown>>("segment_portrait")
                ?.dd_trailing_current,
            ),
          },
          {
            label: "允许回撤",
            value: fmtPctSafe(
              snap.get<Record<string, unknown>>("segment_portrait")?.dd_limit_pct,
            ),
          },
          {
            label: "击穿次数",
            value: fmt(
              snap.get<Record<string, unknown>>("segment_portrait")
                ?.dd_pierce_count,
            ),
          },
        ]}
      />

      <IndicatorCard
        title="时间耗尽窗口（time_exhaustion）"
        hint="绝对时间死亡线"
        rows={[
          {
            label: "至均时间",
            value: fmt(
              snap.get<Record<string, unknown>>("segment_portrait")?.time_avg_ts,
            ),
          },
          {
            label: "至极限",
            value: fmt(
              snap.get<Record<string, unknown>>("segment_portrait")?.time_max_ts,
            ),
          },
          {
            label: "极限洗盘价",
            value: fmtPrice(
              snap.get<Record<string, unknown>>("segment_portrait")
                ?.pain_max_price,
            ),
          },
        ]}
      />
    </div>
  );
}

// ── 价值带族 ──
function ValueTab({ snap }: { snap: SnapAccess }) {
  const hvn = snap.list<Record<string, unknown>>("hvn_nodes");
  const az = snap.list<Record<string, unknown>>("absolute_zones");
  const ob = snap.list<Record<string, unknown>>("order_blocks");
  const micro = snap.list<Record<string, unknown>>("micro_pocs");
  const vp = snap.get<Record<string, unknown>>("volume_profile");

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <IndicatorCard
        title={`HVN 节点（hvn_nodes · ${hvn.length}）`}
        hint="高成交量价位（成本中枢）"
        empty={hvn.length === 0}
      >
        <div className="mt-2 max-h-72 space-y-1 overflow-auto pr-1">
          {hvn.slice(0, 12).map((n, i) => (
            <div key={i} className="flex items-baseline justify-between text-xs">
              <span className="num">{fmtPrice(n.price)}</span>
              <span className="text-muted-foreground">
                vol={fmt(n.volume)} · z={fmt(n.zscore)}
              </span>
            </div>
          ))}
        </div>
      </IndicatorCard>

      <IndicatorCard
        title={`Volume Profile（${vp ? "1" : "0"}）`}
        hint="POC + Value Area + TopN 峰"
        empty={!vp}
      >
        {vp && (
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">POC</span>
              <span className="num font-medium">{fmtPrice(vp.poc_price)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">Value Area High</span>
              <span className="num">{fmtPrice(vp.va_high)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">Value Area Low</span>
              <span className="num">{fmtPrice(vp.va_low)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">VA 占比</span>
              <span className="num">{fmtPctSafe(vp.va_volume_ratio)}</span>
            </div>
            <div className="mt-2 text-[11px] text-muted-foreground">
              Top 峰：
            </div>
            <div className="space-y-0.5">
              {(vp.top_peaks as Record<string, unknown>[] | undefined)
                ?.slice(0, 5)
                .map((p, i) => (
                  <div
                    key={i}
                    className="flex items-baseline justify-between text-xs"
                  >
                    <span className="num">{fmtPrice(p.price)}</span>
                    <span className="text-muted-foreground">
                      vol={fmt(p.volume)}
                    </span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </IndicatorCard>

      <IndicatorCard
        title={`Absolute Zones（${az.length}）`}
        hint="高时间框架强支撑/压力"
        empty={az.length === 0}
      >
        <div className="mt-2 max-h-72 space-y-1 overflow-auto pr-1">
          {az.slice(0, 12).map((z, i) => (
            <div key={i} className="flex items-baseline justify-between text-xs">
              <span className="num">
                {fmtPrice(z.bottom_price)} → {fmtPrice(z.top_price)}
              </span>
              <span className="text-muted-foreground">{fmt(z.type)}</span>
            </div>
          ))}
        </div>
      </IndicatorCard>

      <IndicatorCard
        title={`Order Blocks（${ob.length}）`}
        hint="机构订单块"
        empty={ob.length === 0}
      >
        <div className="mt-2 max-h-72 space-y-1 overflow-auto pr-1">
          {ob.slice(0, 12).map((z, i) => (
            <div key={i} className="flex items-baseline justify-between text-xs">
              <span className="num">
                {fmtPrice(z.bottom_price)} → {fmtPrice(z.top_price)}
              </span>
              <span className="text-muted-foreground">{fmt(z.side)}</span>
            </div>
          ))}
        </div>
      </IndicatorCard>

      <IndicatorCard
        title={`微观 POC（${micro.length}）`}
        hint="本轮 K 线集中成交价"
        empty={micro.length === 0}
      >
        <div className="mt-2 max-h-72 space-y-1 overflow-auto pr-1">
          {micro.slice(0, 12).map((m, i) => (
            <div key={i} className="flex items-baseline justify-between text-xs">
              <span className="num">{fmtPrice(m.poc_price)}</span>
              <span className="text-muted-foreground">
                vol={fmt(m.volume)}
              </span>
            </div>
          ))}
        </div>
      </IndicatorCard>

      <IndicatorCard
        title="移动 VWAP（trailing_vwap）"
        hint="Anchor 后的 VWAP 推移"
        empty={!snap.get("trailing_vwap_last")}
      >
        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">最新 VWAP</span>
            <span className="num font-medium">
              {fmtPrice(
                snap.get<Record<string, unknown>>("trailing_vwap_last")?.vwap,
              )}
            </span>
          </div>
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">价 vs VWAP</span>
            <span className="num">
              {fmtPctSafe(snap.get("fair_value_delta_pct"))}
            </span>
          </div>
        </div>
      </IndicatorCard>
    </div>
  );
}

// ── 流动性族 ──
function LiquidityTab({ snap }: { snap: SnapAccess }) {
  const vacs = snap.list<Record<string, unknown>>("vacuums");
  const heat = snap.list<Record<string, unknown>>("heatmap");
  const fuel = snap.list<Record<string, unknown>>("liquidation_fuel");
  const cascade = snap.list<Record<string, unknown>>("cascade_bands");
  const retail = snap.list<Record<string, unknown>>("retail_stop_bands");

  const renderBands = (bands: Record<string, unknown>[]) => (
    <div className="mt-2 max-h-72 space-y-1 overflow-auto pr-1">
      {bands.slice(0, 12).map((b, i) => (
        <div
          key={i}
          className="flex items-baseline justify-between gap-2 text-xs"
        >
          <span className="num">
            {fmtPrice(b.bottom_price)} → {fmtPrice(b.top_price)}
          </span>
          <span className="text-muted-foreground">
            {fmt(b.side)} · vol={fmt(b.volume)}
          </span>
        </div>
      ))}
    </div>
  );

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <IndicatorCard
        title={`真空带（vacuums · ${vacs.length}）`}
        hint="低成交量 → 价格穿越快"
        empty={vacs.length === 0}
      >
        {renderBands(vacs)}
      </IndicatorCard>

      <IndicatorCard
        title={`爆仓热力（liq_heatmap · ${heat.length}）`}
        hint="清算预测密度"
        empty={heat.length === 0}
      >
        {renderBands(heat)}
      </IndicatorCard>

      <IndicatorCard
        title={`爆仓燃料（liquidation_fuel · ${fuel.length}）`}
        hint="累积清算能量"
        empty={fuel.length === 0}
      >
        {renderBands(fuel)}
      </IndicatorCard>

      <IndicatorCard
        title={`连环爆仓带（cascade · ${cascade.length}）`}
        hint="2/4/8 倍连环触发位"
        empty={cascade.length === 0}
      >
        {renderBands(cascade)}
      </IndicatorCard>

      <IndicatorCard
        title={`散户止损带（retail · ${retail.length}）`}
        hint="磁吸方向（主力扫货目标）"
        empty={retail.length === 0}
        className="lg:col-span-2"
      >
        {renderBands(retail)}
      </IndicatorCard>
    </div>
  );
}

// ── 结构事件族 ──
function StructureTab({ snap }: { snap: SnapAccess }) {
  const choch = snap.list<Record<string, unknown>>("choch_recent");
  const pi_recent = snap.list<Record<string, unknown>>("power_imbalance_recent");
  const exh_recent = snap.list<Record<string, unknown>>("trend_exhaustion_recent");

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <IndicatorCard
        title={`CHoCH 破位 / 突破（${choch.length}）`}
        hint="机构破坏（破）/ 突破（突）"
        empty={choch.length === 0}
      >
        <div className="mt-2 max-h-72 space-y-1 overflow-auto pr-1">
          {choch.slice(0, 12).map((c, i) => (
            <div key={i} className="flex items-baseline justify-between text-xs">
              <span className="num">{fmtPrice(c.level_price)}</span>
              <span className="text-muted-foreground">
                {fmt(c.kind)}_{fmt(c.direction)} · {fmt(c.bars_since)} 根前
              </span>
            </div>
          ))}
        </div>
      </IndicatorCard>

      <IndicatorCard
        title="流动性扫荡（liquidity_sweep）"
        hint="近期次数 + 最新事件"
        rows={[
          {
            label: "近窗扫荡次数",
            value: fmt(snap.get("sweep_count_recent")),
          },
          {
            label: "最新方向",
            value: fmt(
              snap.get<Record<string, unknown>>("sweep_last")?.direction,
            ),
          },
          {
            label: "最新强度",
            value: fmt(
              snap.get<Record<string, unknown>>("sweep_last")?.strength,
            ),
          },
        ]}
      />

      <IndicatorCard
        title={`能量失衡（power_imbalance · 近 ${pi_recent.length}）`}
        hint="官方：连续 ≥3 根 → 行情发动"
        empty={pi_recent.length === 0}
      >
        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-muted-foreground">Streak</span>
            <span className="num font-medium">
              {fmt(snap.get("power_imbalance_streak"))} 根 ·{" "}
              {fmt(snap.get("power_imbalance_streak_side"))}
            </span>
          </div>
          <div className="mt-2 max-h-56 space-y-1 overflow-auto pr-1">
            {pi_recent.slice(0, 12).map((p, i) => (
              <div
                key={i}
                className="flex items-baseline justify-between text-xs"
              >
                <span className="num">{fmt(p.ratio)}</span>
                <span className="text-muted-foreground">
                  {fmt(p.imbalance_side)} · {fmt(p.ts)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </IndicatorCard>

      <IndicatorCard
        title={`趋势衰竭近窗（trend_exhaustion · ${exh_recent.length}）`}
        hint="近窗逐根衰竭值"
        empty={exh_recent.length === 0}
      >
        <div className="mt-2 max-h-56 space-y-1 overflow-auto pr-1">
          {exh_recent.slice(0, 12).map((e, i) => (
            <div key={i} className="flex items-baseline justify-between text-xs">
              <span className="num">{fmt(e.exhaustion)}</span>
              <span className="text-muted-foreground">
                {fmt(e.type)} · {fmt(e.ts)}
              </span>
            </div>
          ))}
        </div>
      </IndicatorCard>
    </div>
  );
}

// ── 主力族 ──
function MainForceTab({ snap }: { snap: SnapAccess }) {
  const sm_ongoing = snap.get<Record<string, unknown>>("smart_money_ongoing");
  const sm_all = snap.list<Record<string, unknown>>("smart_money_all");
  const reso_recent = snap.list<Record<string, unknown>>("resonance_recent");

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <IndicatorCard
        title="聪明钱成本（smart_money）"
        hint="主力建仓段及成本均价"
        empty={!sm_ongoing && sm_all.length === 0}
      >
        {sm_ongoing && (
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">进行中段</span>
              <span className="num font-medium">{fmt(sm_ongoing.type)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">建仓均价</span>
              <span className="num">{fmtPrice(sm_ongoing.avg_price)}</span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">起始 ts</span>
              <span className="num">{fmt(sm_ongoing.start_ts)}</span>
            </div>
          </div>
        )}
        {sm_all.length > 0 && (
          <div className="mt-3 border-t border-border/30 pt-2">
            <div className="text-[11px] text-muted-foreground">
              历史段（共 {sm_all.length}）
            </div>
            <div className="mt-1 max-h-40 space-y-0.5 overflow-auto pr-1">
              {sm_all.slice(0, 8).map((s, i) => (
                <div
                  key={i}
                  className="flex items-baseline justify-between text-xs"
                >
                  <span className="num">{fmtPrice(s.avg_price)}</span>
                  <span className="text-muted-foreground">{fmt(s.type)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </IndicatorCard>

      <IndicatorCard
        title={`跨所共振（resonance · 近 ${reso_recent.length}）`}
        hint="多平台同向异常"
        rows={[
          {
            label: "近窗总次数",
            value: fmt(snap.get("resonance_count_recent")),
          },
          {
            label: "买/卖",
            value: `${fmt(snap.get("resonance_buy_count"))} / ${fmt(snap.get("resonance_sell_count"))}`,
          },
          {
            label: "巨鲸净方向",
            value: fmt(snap.get("whale_net_direction")),
            tone:
              snap.get<string>("whale_net_direction") === "buy"
                ? "good"
                : snap.get<string>("whale_net_direction") === "sell"
                  ? "bad"
                  : "neutral",
          },
        ]}
      >
        {reso_recent.length > 0 && (
          <div className="mt-3 max-h-40 space-y-0.5 overflow-auto pr-1">
            {reso_recent.slice(0, 8).map((r, i) => (
              <div
                key={i}
                className="flex items-baseline justify-between text-xs"
              >
                <span className="num">{fmt(r.side)}</span>
                <span className="text-muted-foreground">
                  strength={fmt(r.strength)} · ts={fmt(r.ts)}
                </span>
              </div>
            ))}
          </div>
        )}
      </IndicatorCard>

      <IndicatorCard
        title="时间热力图（time_heatmap）"
        hint="24h 活跃度 + 当前小时"
        empty={!snap.get("time_heatmap_view")}
        className="lg:col-span-2"
      >
        {Boolean(snap.get("time_heatmap_view")) && (
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">当前小时活跃度</span>
              <span className="num font-medium">
                {fmtPctSafe(snap.get("current_hour_activity"))}
              </span>
            </div>
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-muted-foreground">是否活跃时段</span>
              <span className="num">
                {snap.get<boolean>("active_session") ? "✓ 是" : "✗ 否"}
              </span>
            </div>
            <div className="mt-2">
              <div className="text-[11px] text-muted-foreground">
                Peak 小时：
                {fmt(
                  (snap.get<Record<string, unknown>>("time_heatmap_view")
                    ?.peak_hours as number[] | undefined)?.join(", "),
                )}
              </div>
              <div className="text-[11px] text-muted-foreground">
                Dead 小时：
                {fmt(
                  (snap.get<Record<string, unknown>>("time_heatmap_view")
                    ?.dead_hours as number[] | undefined)?.join(", "),
                )}
              </div>
            </div>
          </div>
        )}
      </IndicatorCard>
    </div>
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
                · 锚点 {new Date(anchor_ts).toLocaleString()}
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
          {active === "trend" && <TrendTab snap={snap} />}
          {active === "value" && <ValueTab snap={snap} />}
          {active === "liquidity" && <LiquidityTab snap={snap} />}
          {active === "structure" && <StructureTab snap={snap} />}
          {active === "main_force" && <MainForceTab snap={snap} />}
        </>
      )}

      {/* 底部小提示 */}
      <div className="text-center text-[11px] text-muted-foreground">
        指标全景每 30s 自动刷新一次。
        <span className="opacity-60">
          所有数据来自 backend · FeatureSnapshot.{`{trend|value|liquidity|...}`}
        </span>
      </div>
    </div>
  );
}
