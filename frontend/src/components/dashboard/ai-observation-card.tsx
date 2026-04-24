import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Brain,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCcw,
  Sparkles,
  Target,
} from "lucide-react";

import {
  fetchAIObservations,
  fetchAIStatus,
  runAIObservation,
} from "@/lib/api";
import type {
  AIBandKind,
  AIDirection,
  AIDominantSide,
  AIMoneyFlowLayer,
  AIObserverFeedItem,
  AIObserverSummary,
  AISizeHint,
  AIStage,
  AITradePlanLayer,
  AITradePlanLeg,
  AITrendLayer,
} from "@/lib/types";
import { cn, formatPrice } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface Props {
  summary: AIObserverSummary | null | undefined;
  symbol: string;
  tf: string;
}

const DIRECTION_LABEL: Record<AIDirection, string> = {
  bullish: "多头占优",
  bearish: "空头占优",
  neutral: "中性观望",
};

const STAGE_LABEL: Record<AIStage, string> = {
  accumulation: "吸筹",
  breakout: "突破",
  distribution: "派发",
  trend_up: "多头趋势",
  trend_down: "空头趋势",
  reversal: "反转",
  chop: "震荡",
};

const DOMINANT_LABEL: Record<AIDominantSide, string> = {
  smart_buy: "主力吸筹",
  smart_sell: "主力派发",
  retail_chase: "散户抢多",
  retail_flush: "散户洗出",
  neutral: "观望",
};

const BAND_KIND_LABEL: Record<AIBandKind, string> = {
  cascade_long_fuel: "爆仓·多燃",
  cascade_short_fuel: "爆仓·空燃",
  retail_long_fuel: "散户·多燃",
  retail_short_fuel: "散户·空燃",
};

const SIZE_HINT_LABEL: Record<AISizeHint, string> = {
  light: "轻仓",
  half: "半仓",
  full: "满档",
};

const TRIGGER_LABEL: Record<string, string> = {
  manual: "手动",
  scheduled: "自动",
  phase_switch: "换阶",
  urgent_signal: "紧急",
};

const STRENGTH_LABEL: Record<string, string> = {
  strong: "强",
  moderate: "中",
  weak: "弱",
};

export function AIObservationCard({ summary, symbol, tf }: Props) {
  const [expanded, setExpanded] = useState(false);

  // 启停状态：只在未启用时展示引导；已启用不请求列表避免打扰
  const statusQ = useQuery({
    queryKey: ["ai-status"],
    queryFn: fetchAIStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const feedQ = useQuery({
    queryKey: ["ai-feed", symbol, tf],
    queryFn: () => fetchAIObservations(10),
    enabled: expanded && !!statusQ.data?.config.enabled,
    refetchOnMount: "always",
  });

  const runMut = useMutation({
    mutationFn: (force_trade_plan: boolean) =>
      runAIObservation({ symbol, tf, force_trade_plan }),
    onSuccess: () => feedQ.refetch(),
  });

  const enabled = statusQ.data?.config.enabled ?? false;

  // ─── 未启用：引导用户去设置 ──
  if (!enabled) {
    return (
      <div className="panel-glass rounded-lg p-4">
        <SectionHeader />
        <div className="mt-3 text-sm text-foreground/70">
          AI 观察未启用。前往 <span className="font-mono">设置 · AI 观察</span>
          开启并填入 DeepSeek API Key 后，此卡将显示由 AI 总结的趋势判断 +
          资金面解读，满足置信度阈值时自动出交易计划。
        </div>
      </div>
    );
  }

  // ─── 已启用但还无 summary（冷启动 / 刚切币种） ──
  if (!summary) {
    return (
      <div className="panel-glass rounded-lg p-4">
        <SectionHeader />
        <div className="mt-3 text-sm text-foreground/70">
          正在汇集本根 K 线的数据，下一轮采集完成后会自动送 AI。
          也可手动点击"求交易计划"立即触发。
        </div>
        <div className="mt-3">
          <Button
            size="sm"
            variant="outline"
            disabled={runMut.isPending}
            onClick={() => runMut.mutate(true)}
          >
            {runMut.isPending ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="mr-1.5 h-3.5 w-3.5" />
            )}
            求交易计划
          </Button>
        </div>
      </div>
    );
  }

  const trendTone = toneOfDirection(summary.trend_direction);
  const mfTone = toneOfDominant(summary.money_flow_dominant);
  const hasErrors = Object.keys(summary.errors || {}).length > 0;

  return (
    <div
      className={cn(
        "panel-glass rounded-lg p-4",
        summary.has_trade_plan && "accent-stripe-cyan",
      )}
    >
      <SectionHeader
        rightSlot={
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Badge variant="outline" className="font-normal">
              {summary.provider}
            </Badge>
            {statusQ.data?.config && (
              <Badge
                variant="outline"
                className={cn(
                  "font-normal",
                  statusQ.data.config.model_tier === "pro" &&
                    "border-primary/60 text-primary",
                )}
                title={`当前默认模型：${
                  statusQ.data.config.model_tier === "pro"
                    ? statusQ.data.config.pro_model
                    : statusQ.data.config.flash_model
                }${
                  statusQ.data.config.thinking_enabled ? "；思维模式已开启" : ""
                }`}
              >
                {statusQ.data.config.model_tier === "pro" ? "Pro" : "Flash"}
                {statusQ.data.config.thinking_enabled && "·思"}
              </Badge>
            )}
            <Badge variant="outline" className="font-normal">
              {TRIGGER_LABEL[summary.trigger] ?? summary.trigger}
            </Badge>
            {summary.layers_used.length > 0 && (
              <Badge variant="outline" className="font-normal">
                L{summary.layers_used.length}
              </Badge>
            )}
            <span className="font-mono">
              {summary.age_seconds < 60
                ? `${summary.age_seconds}s 前`
                : `${Math.floor(summary.age_seconds / 60)}m 前`}
            </span>
          </div>
        }
      />

      {/* 主体两列：趋势 + 资金 */}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            <Target className="h-3 w-3" />
            趋势判断
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className={cn("text-lg font-semibold", trendTone)}>
              {summary.trend_direction
                ? DIRECTION_LABEL[summary.trend_direction]
                : "—"}
            </span>
            {summary.trend_stage && (
              <span className="text-sm text-foreground/70">
                · {STAGE_LABEL[summary.trend_stage] ?? summary.trend_stage}
              </span>
            )}
            {summary.trend_strength && (
              <Badge variant="outline" className="font-normal text-[10px]">
                {STRENGTH_LABEL[summary.trend_strength] ?? summary.trend_strength}
              </Badge>
            )}
          </div>
          <ConfidenceBar value={summary.trend_confidence} tone="trend" />
          <p className="mt-1 text-xs text-foreground/80 leading-snug">
            {summary.trend_narrative ?? "—"}
          </p>
        </div>

        <div>
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            <Brain className="h-3 w-3" />
            资金面解读
          </div>
          <div className={cn("mt-1 text-lg font-semibold", mfTone)}>
            {summary.money_flow_dominant
              ? DOMINANT_LABEL[summary.money_flow_dominant]
              : "—"}
          </div>
          <ConfidenceBar value={summary.money_flow_confidence} tone="money" />
          <p className="mt-1 text-xs text-foreground/80 leading-snug">
            {summary.money_flow_narrative ?? "—"}
          </p>
        </div>
      </div>

      {/* 磁吸带预览（有才显示） */}
      {summary.key_bands_preview.length > 0 && (
        <div className="mt-3">
          <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            关键磁吸带
          </div>
          <ul className="mt-1 grid gap-1 sm:grid-cols-2 md:grid-cols-3">
            {summary.key_bands_preview.map((b, i) => (
              <li
                key={i}
                className="flex flex-wrap items-center gap-1.5 rounded border border-border/30 bg-background/30 px-2 py-1 text-[11px]"
              >
                <Badge variant="outline" className="font-normal text-[10px]">
                  {BAND_KIND_LABEL[b.kind] ?? b.kind}
                </Badge>
                <span className="num font-medium">{formatPrice(b.avg_price)}</span>
                <span
                  className={cn(
                    "num text-[10px]",
                    b.distance_pct >= 0 ? "text-bearish" : "text-bullish",
                  )}
                >
                  {b.distance_pct >= 0 ? "+" : ""}
                  {b.distance_pct.toFixed(2)}%
                </span>
                <span className="text-foreground/75 truncate" title={b.note}>
                  {b.note}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 交易计划摘要（有才显示） */}
      {summary.has_trade_plan && (
        <>
          <div className="holo-line-muted my-3" />
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                <Sparkles className="h-3 w-3" />
                交易计划（Pro）
              </div>
              <div className="flex items-center gap-2 text-[10px]">
                {summary.trade_plan_legs_count > 0 && (
                  <Badge variant="outline" className="font-normal">
                    {summary.trade_plan_legs_count} 条
                  </Badge>
                )}
                {summary.trade_plan_top_rr != null && (
                  <Badge variant="outline" className="font-normal">
                    R:R {summary.trade_plan_top_rr.toFixed(2)}
                  </Badge>
                )}
              </div>
            </div>
            <ConfidenceBar value={summary.trade_plan_confidence} tone="plan" />
            {summary.trade_plan_narrative && (
              <p className="mt-1 text-sm text-foreground leading-snug">
                {summary.trade_plan_narrative}
              </p>
            )}
            {summary.risk_flags.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {summary.risk_flags.map((f) => (
                  <Badge
                    key={f}
                    variant="outline"
                    className="border-warning/60 text-warning font-normal text-[10px]"
                  >
                    {f}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* 错误提示 */}
      {hasErrors && (
        <div className="mt-3 flex items-start gap-1.5 text-[11px] text-warning">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <div>
            {Object.entries(summary.errors).map(([layer, msg]) => (
              <div key={layer}>
                <span className="font-mono">{layer}</span>：{msg}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 元数据（tokens / latency / layers） */}
      <div className="mt-3 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
        {summary.tokens_total > 0 && (
          <span>tokens {summary.tokens_total}</span>
        )}
        {summary.latency_ms > 0 && (
          <span>延迟 {(summary.latency_ms / 1000).toFixed(2)}s</span>
        )}
        {summary.layers_used.length > 0 && (
          <span>层 {summary.layers_used.join("/")}</span>
        )}
      </div>

      {/* 操作条 */}
      <div className="mt-3 flex items-center justify-between">
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={runMut.isPending}
            onClick={() => runMut.mutate(true)}
            title="用 Pro 模型强制生成一份交易计划"
          >
            {runMut.isPending ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="mr-1.5 h-3.5 w-3.5" />
            )}
            求交易计划
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={runMut.isPending}
            onClick={() => runMut.mutate(false)}
            title="只更新趋势 + 资金面，不出计划"
          >
            <RefreshCcw className="mr-1.5 h-3.5 w-3.5" />
            重新观察
          </Button>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
        >
          历史 feed
          {expanded ? (
            <ChevronUp className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          )}
        </button>
      </div>

      {/* 历史 feed */}
      {expanded && (
        <div className="mt-3 border-t border-border/30 pt-3">
          {feedQ.isLoading ? (
            <div className="text-xs text-muted-foreground">加载中…</div>
          ) : (feedQ.data?.items ?? []).length === 0 ? (
            <div className="text-xs text-muted-foreground">暂无历史记录</div>
          ) : (
            <div className="grid gap-2 max-h-[420px] overflow-y-auto">
              {(feedQ.data?.items ?? []).map((it) => (
                <HistoryRow key={`${it.ts}-${it.anchor_ts}`} item={it} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SectionHeader({
  rightSlot,
}: {
  rightSlot?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <Brain className="h-3.5 w-3.5" />
        AI 观察（V1.1）
      </div>
      {rightSlot}
    </div>
  );
}

function HistoryRow({ item }: { item: AIObserverFeedItem }) {
  const trend = item.trend as AITrendLayer | null | undefined;
  const mf = item.money_flow as AIMoneyFlowLayer | null | undefined;
  const plan = item.trade_plan as AITradePlanLayer | null | undefined;

  const when = new Date(item.ts).toLocaleString("zh-CN", { hour12: false });
  const totalTokens = Object.values(item.cost_tokens ?? {}).reduce(
    (a, b) => a + (Number(b) || 0),
    0,
  );
  const usedPro = Object.values(item.models_used ?? {}).some((m) =>
    m.includes("pro"),
  );

  return (
    <details className="group rounded border border-border/30 bg-background/40 open:border-primary/40">
      <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="font-mono text-muted-foreground">{when}</span>
          <Badge variant="outline" className="font-normal">
            {item.provider}
          </Badge>
          <Badge variant="outline" className="font-normal">
            {TRIGGER_LABEL[item.trigger] ?? item.trigger}
          </Badge>
          {trend?.direction && (
            <span className={toneOfDirection(trend.direction)}>
              {DIRECTION_LABEL[trend.direction]}
            </span>
          )}
          {plan && plan.legs.length > 0 && (
            <Badge variant="default" className="gap-1 font-normal">
              <Sparkles className="h-3 w-3" /> 计划{plan.legs.length}
            </Badge>
          )}
          {usedPro && (
            <Badge variant="outline" className="border-primary/60 text-primary font-normal">
              Pro
            </Badge>
          )}
          <span className="num text-[10px] text-muted-foreground">
            {formatPrice(item.last_price)}
          </span>
        </div>
        <span className="text-muted-foreground group-open:hidden">▼</span>
        <span className="hidden text-muted-foreground group-open:inline">▲</span>
      </summary>
      <div className="border-t border-border/20 p-3 text-xs text-foreground/85">
        {trend && (
          <div className="mb-2">
            <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
              <span>趋势</span>
              <span className={toneOfDirection(trend.direction)}>
                {DIRECTION_LABEL[trend.direction]}
              </span>
              <span>· {STAGE_LABEL[trend.stage] ?? trend.stage}</span>
              <span>· 强度 {STRENGTH_LABEL[trend.strength] ?? trend.strength}</span>
              <span>· 置信 {(trend.confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="mt-0.5">{trend.narrative}</div>
            {trend.evidences?.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-[11px] text-foreground/75">
                {trend.evidences.map((ev, i) => (
                  <li key={i}>{ev}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {mf && (
          <div className="mb-2">
            <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
              <span>资金</span>
              <span className={toneOfDominant(mf.dominant_side)}>
                {DOMINANT_LABEL[mf.dominant_side]}
              </span>
              <span>· 置信 {(mf.confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="mt-0.5">{mf.narrative}</div>
            <div className="mt-1 grid gap-0.5 text-[11px]">
              <div>
                <span className="text-muted-foreground">上方：</span>
                {mf.pressure_above || "—"}
              </div>
              <div>
                <span className="text-muted-foreground">下方：</span>
                {mf.support_below || "—"}
              </div>
            </div>
            {mf.key_bands?.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-[11px]">
                {mf.key_bands.map((b, i) => (
                  <li key={i} className="flex flex-wrap gap-1.5">
                    <Badge variant="outline" className="font-normal">
                      {BAND_KIND_LABEL[b.kind] ?? b.kind}
                    </Badge>
                    <span className="num">{formatPrice(b.avg_price)}</span>
                    <span className="num text-muted-foreground">
                      {b.distance_pct > 0 ? "+" : ""}
                      {b.distance_pct.toFixed(2)}%
                    </span>
                    <span className="text-foreground/75">{b.note}</span>
                  </li>
                ))}
              </ul>
            )}
            {mf.evidences?.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-[11px] text-foreground/75">
                {mf.evidences.map((ev, i) => (
                  <li key={i}>{ev}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {plan && (
          <div>
            <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
              <span>计划</span>
              <span>· 置信 {(plan.confidence * 100).toFixed(0)}%</span>
              {plan.risk_flags.length > 0 && (
                <span className="text-warning">
                  · 风险 {plan.risk_flags.join("/")}
                </span>
              )}
            </div>
            <div className="mt-0.5">{plan.narrative}</div>
            {plan.legs.length > 0 && (
              <ul className="mt-1 space-y-1">
                {plan.legs.map((leg, i) => (
                  <PlanLegRow key={i} idx={i} leg={leg} />
                ))}
              </ul>
            )}
            {plan.conditions.length > 0 && (
              <div className="mt-1 text-[10px] text-muted-foreground">
                先决条件：{plan.conditions.join("；")}
              </div>
            )}
          </div>
        )}
        <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
          <span>tokens {totalTokens}</span>
          <span>延迟 {(item.latency_ms / 1000).toFixed(2)}s</span>
          {item.layers_used.length > 0 && (
            <span>层 {item.layers_used.join("/")}</span>
          )}
        </div>
      </div>
    </details>
  );
}

function PlanLegRow({ idx, leg }: { idx: number; leg: AITradePlanLeg }) {
  const dirTone = leg.direction === "long" ? "text-bullish" : "text-bearish";
  return (
    <li className="rounded border border-border/30 bg-background/30 p-2 text-[11px]">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-muted-foreground">#{idx + 1}</span>
        <span className={cn("font-semibold", dirTone)}>
          {leg.direction === "long" ? "做多" : "做空"}
        </span>
        <Badge variant="outline" className="font-normal">
          {SIZE_HINT_LABEL[leg.size_hint]}
        </Badge>
        <span className="text-muted-foreground">
          R:R {leg.risk_reward.toFixed(2)}
        </span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-3">
        <span>
          <span className="text-muted-foreground">进场 </span>
          <span className="num">
            {formatPrice(leg.entry_zone[0])}–{formatPrice(leg.entry_zone[1])}
          </span>
        </span>
        <span>
          <span className="text-muted-foreground">止损 </span>
          <span className="num text-destructive">{formatPrice(leg.stop_loss)}</span>
        </span>
        <span>
          <span className="text-muted-foreground">T </span>
          <span className="num">
            {leg.take_profits.map((t) => formatPrice(t)).join(" / ")}
          </span>
        </span>
      </div>
      <div className="mt-0.5 text-foreground/75">{leg.rationale}</div>
      {leg.invalidation && (
        <div className="mt-0.5 text-[10px] text-muted-foreground">
          失效：{leg.invalidation}
        </div>
      )}
    </li>
  );
}

function ConfidenceBar({
  value,
  tone,
}: {
  value: number | null | undefined;
  tone: "trend" | "money" | "plan";
}) {
  if (value == null) return null;
  const pct = Math.max(0, Math.min(1, value));
  const color =
    tone === "trend"
      ? "bg-primary"
      : tone === "money"
        ? "bg-neon-cyan"
        : "bg-accent";
  return (
    <div className="mt-1 flex items-center gap-2">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-border/40">
        <div
          className={cn("h-full rounded-full", color)}
          style={{ width: `${(pct * 100).toFixed(0)}%` }}
        />
      </div>
      <span className="num text-[10px] text-muted-foreground">
        {(pct * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function toneOfDirection(d: AIDirection | null | undefined) {
  if (d === "bullish") return "text-bullish";
  if (d === "bearish") return "text-bearish";
  return "text-foreground/80";
}

function toneOfDominant(d: AIDominantSide | null | undefined) {
  if (d === "smart_buy") return "text-neon-cyan";
  if (d === "smart_sell") return "text-neon-amber";
  if (d === "retail_chase") return "text-warning";
  if (d === "retail_flush") return "text-warning";
  return "text-foreground/80";
}
