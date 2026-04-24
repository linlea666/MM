import type { DashboardSnapshot, TradingPlan } from "@/lib/types";
import { FlashNumber } from "@/components/ui/flash-number";
import { useLivePrice } from "@/hooks/use-live-price";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { Wifi, WifiOff } from "lucide-react";

interface Props {
  snap: DashboardSnapshot;
}

/**
 * 顶部结论带（决策中心入口）
 *
 * 左：symbol / tf / 实时价 / 24h 涨跌幅
 * 中：一句话结论（当前市场 + 持续状态）
 * 右：策略建议（做多 / 做空 触发价）
 */
export function HeroVerdict({ snap }: Props) {
  const { symbol, tf, current_price, phase, plans, levels } = snap;
  const live = useLivePrice(symbol);

  // 实时价优先，snapshot 兜底
  const price = live.price ?? current_price;
  const change24h = live.change24h;

  // 选出最佳做多 / 做空计划（stars 最高）
  const longPlan = pickPlan(plans, ["追多", "回踩做多"]);
  const shortPlan = pickPlan(plans, ["追空", "反弹做空"]);
  const topPlan = plans[0]; // 后端已按 stars 排序

  return (
    <div className="panel-glass rounded-lg">
      <div className="grid grid-cols-12 gap-5 p-5">
        {/* 左：币种 + 实时价 */}
        <div className="col-span-12 md:col-span-4 flex flex-col justify-between">
          <div className="flex items-center gap-2">
            <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              {symbol} / USDT
            </div>
            <span
              className={cn(
                "text-[10px] uppercase tracking-wider",
                live.status === "open"
                  ? "text-neon-lime"
                  : live.status === "connecting"
                  ? "text-neon-amber"
                  : "text-muted-foreground",
              )}
              title={`Binance ${live.status}`}
            >
              {live.status === "open" ? (
                <span className="inline-flex items-center gap-1">
                  <span
                    className="pulse-dot"
                    style={{ background: "hsl(var(--neon-lime))" }}
                  />
                  LIVE
                </span>
              ) : live.status === "connecting" ? (
                <span className="inline-flex items-center gap-1">
                  <Wifi className="h-3 w-3" /> 连接中
                </span>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <WifiOff className="h-3 w-3" /> 快照
                </span>
              )}
            </span>
            <span className="text-[10px] text-muted-foreground">· {tf}</span>
          </div>

          <div className="mt-1 flex items-baseline gap-3">
            <FlashNumber
              value={price}
              format={(v) => formatPrice(v, 2)}
              showArrow={false}
              className="num-hero text-5xl md:text-6xl text-foreground glow-cyan"
            />
            {change24h !== null && (
              <span
                className={cn(
                  "num text-sm font-semibold",
                  change24h >= 0 ? "text-neon-lime" : "text-neon-magenta",
                )}
              >
                {change24h >= 0 ? "+" : ""}
                {formatPct(change24h)}
              </span>
            )}
          </div>

          {(live.high24h !== null || live.low24h !== null) && (
            <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
              {live.high24h !== null && (
                <span>
                  24h 高 <span className="num text-foreground/80">{formatPrice(live.high24h)}</span>
                </span>
              )}
              {live.low24h !== null && (
                <span>
                  24h 低 <span className="num text-foreground/80">{formatPrice(live.low24h)}</span>
                </span>
              )}
            </div>
          )}
        </div>

        {/* 中：一句话结论 */}
        <div className="col-span-12 md:col-span-5 flex flex-col justify-center border-l border-border/30 pl-5">
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            当前市场
          </div>
          <div className="mt-1 text-2xl font-semibold text-foreground">
            {phase.current}
            {phase.unstable && (
              <span className="ml-2 chip chip-amber">不稳定</span>
            )}
          </div>
          <div className="mt-1.5 flex items-center gap-2 text-sm text-muted-foreground">
            <span>
              持续 <span className="num text-foreground/80">{phase.bars_in_phase}</span> 根 K 线
            </span>
            <span className="opacity-40">·</span>
            <span>
              置信度{" "}
              <span
                className={cn(
                  "num font-medium",
                  phase.current_score >= 70
                    ? "text-neon-lime"
                    : phase.current_score >= 50
                    ? "text-foreground/80"
                    : "text-neon-amber",
                )}
              >
                {phase.current_score}
              </span>
              /100
            </span>
            {phase.next_likely && (
              <>
                <span className="opacity-40">·</span>
                <span>
                  下一阶段可能 <span className="text-foreground/80">{phase.next_likely}</span>
                </span>
              </>
            )}
          </div>
        </div>

        {/* 右：策略建议 */}
        <div className="col-span-12 md:col-span-3 flex flex-col justify-center border-l border-border/30 pl-5">
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            策略建议
          </div>
          <div
            className={cn(
              "mt-1 text-base font-semibold",
              verdictColor(topPlan?.action),
            )}
          >
            {topPlan?.action ?? "观望"}
            {topPlan && (
              <span className="ml-2 text-xs text-muted-foreground">
                （{topPlan.label}·{"★".repeat(topPlan.stars)}）
              </span>
            )}
          </div>
          <div className="mt-2 space-y-1 text-xs text-muted-foreground">
            {longPlan && (
              <div>
                <span className="text-neon-lime">▲</span>{" "}
                多：
                <span className="num text-foreground/85">
                  {longPlan.entry
                    ? formatPrice(longPlan.entry[0])
                    : levels.r1
                    ? formatPrice(levels.r1.price)
                    : "—"}
                </span>{" "}
                站稳
              </div>
            )}
            {shortPlan && (
              <div>
                <span className="text-neon-magenta">▼</span>{" "}
                空：
                <span className="num text-foreground/85">
                  {shortPlan.entry
                    ? formatPrice(shortPlan.entry[0])
                    : levels.s1
                    ? formatPrice(levels.s1.price)
                    : "—"}
                </span>{" "}
                跌破
              </div>
            )}
            {!longPlan && !shortPlan && (
              <div className="text-[11px] leading-snug text-muted-foreground">
                无可执行计划，等待结构明朗
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function pickPlan(plans: TradingPlan[], actions: string[]): TradingPlan | null {
  const filtered = plans.filter((p) => actions.includes(p.action));
  if (filtered.length === 0) return null;
  return filtered.sort((a, b) => b.stars - a.stars)[0];
}

function verdictColor(action?: string): string {
  if (!action) return "text-muted-foreground";
  if (action.includes("多")) return "text-neon-lime glow-lime";
  if (action.includes("空")) return "text-neon-magenta glow-magenta";
  if (action === "反手") return "text-neon-amber glow-amber";
  return "text-foreground/70";
}
