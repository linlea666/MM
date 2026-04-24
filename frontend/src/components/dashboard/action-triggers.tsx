import type { DashboardSnapshot, TradingPlan } from "@/lib/types";
import { cn, formatPrice } from "@/lib/utils";

interface Props {
  snap: DashboardSnapshot;
}

/**
 * 触发条件卡
 *
 * 设计要点（GPT 建议）：
 *   🟢 做多条件 + 最近可做多的计划
 *   🔴 做空条件 + 最近可做空的计划
 *   ⚪ 当前状态：基于价格相对区间的位置给出「划算 / 不划算 / 中部」
 *
 * 从 `TradingPlan` 的 entry/stop/premise/invalidation 派生，不改后端。
 */
export function ActionTriggers({ snap }: Props) {
  const { plans, levels } = snap;
  const current = snap.current_price;

  const longPlan = pickPlan(plans, ["追多", "回踩做多"]);
  const shortPlan = pickPlan(plans, ["追空", "反弹做空"]);

  // 当前状态判断
  const r1 = levels.r1?.price;
  const s1 = levels.s1?.price;
  let positionText = "无关键位 · 结构不明";
  let positionVerdict: "favorable_long" | "favorable_short" | "neutral" | "unfavorable" = "neutral";
  if (r1 && s1) {
    const rangeMid = (r1 + s1) / 2;
    const range = r1 - s1;
    const distFromMid = Math.abs(current - rangeMid);
    const distPct = range > 0 ? distFromMid / range : 0;

    if (current >= r1) {
      positionText = `已突破 R1 ${formatPrice(r1)} · 等待站稳或回踩确认`;
      positionVerdict = "neutral";
    } else if (current <= s1) {
      positionText = `已跌破 S1 ${formatPrice(s1)} · 等待止跌或回测确认`;
      positionVerdict = "neutral";
    } else if (distPct < 0.15) {
      positionText = "价格位于区间中部 → 风险收益比不划算";
      positionVerdict = "unfavorable";
    } else if (current < rangeMid) {
      positionText = `靠近下沿 S1 · 偏利于做多布局（距离 ${formatPrice(s1)}）`;
      positionVerdict = "favorable_long";
    } else {
      positionText = `靠近上沿 R1 · 偏利于做空布局（距离 ${formatPrice(r1)}）`;
      positionVerdict = "favorable_short";
    }
  }

  return (
    <div className="panel-glass rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            触发条件
          </div>
          <div className="mt-0.5 text-sm font-semibold">什么时候可以出手</div>
        </div>
      </div>

      <div className="holo-line-muted my-3" />

      <div className="space-y-2.5">
        {/* 做多条件 */}
        <TriggerRow
          kind="long"
          plan={longPlan}
          fallbackTrigger={r1 ? `突破 ${formatPrice(r1)} 站稳` : null}
        />

        {/* 做空条件 */}
        <TriggerRow
          kind="short"
          plan={shortPlan}
          fallbackTrigger={s1 ? `跌破 ${formatPrice(s1)} 确认` : null}
        />

        {/* 当前状态 */}
        <div
          className={cn(
            "rounded-md border px-3 py-2.5",
            positionVerdict === "favorable_long"
              ? "border-neon-lime/30 bg-neon-lime/5"
              : positionVerdict === "favorable_short"
              ? "border-neon-magenta/30 bg-neon-magenta/5"
              : positionVerdict === "unfavorable"
              ? "border-neon-amber/30 bg-neon-amber/5"
              : "border-border/50 bg-background/40",
          )}
        >
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "text-base",
                positionVerdict === "favorable_long"
                  ? "text-neon-lime"
                  : positionVerdict === "favorable_short"
                  ? "text-neon-magenta"
                  : positionVerdict === "unfavorable"
                  ? "text-neon-amber"
                  : "text-muted-foreground",
              )}
            >
              ●
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              当前状态
            </span>
          </div>
          <div className="mt-1 text-sm font-medium text-foreground/90">
            {positionText}
          </div>
        </div>
      </div>
    </div>
  );
}

function TriggerRow({
  kind,
  plan,
  fallbackTrigger,
}: {
  kind: "long" | "short";
  plan: TradingPlan | null;
  fallbackTrigger: string | null;
}) {
  const isLong = kind === "long";
  const color = isLong ? "lime" : "magenta";
  const dot = isLong ? "🟢" : "🔴";
  const title = isLong ? "做多条件" : "做空条件";

  return (
    <div
      className={cn(
        "rounded-md border px-3 py-2.5",
        isLong
          ? "border-neon-lime/25 bg-neon-lime/5"
          : "border-neon-magenta/25 bg-neon-magenta/5",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-base">{dot}</span>
        <span
          className={cn(
            "text-xs font-semibold uppercase tracking-wider",
            isLong ? "text-neon-lime" : "text-neon-magenta",
          )}
        >
          {title}
        </span>
        {plan && (
          <span className={cn("chip", `chip-${color}`)}>
            {plan.label} · {"★".repeat(plan.stars)}
          </span>
        )}
      </div>

      {plan ? (
        <div className="mt-1.5 space-y-1 text-xs">
          <div className="text-foreground/90">
            <span className="text-muted-foreground">触发：</span>
            {plan.premise}
          </div>
          {plan.entry && (
            <div className="text-foreground/80">
              <span className="text-muted-foreground">入场：</span>
              <span className="num">
                {formatPrice(plan.entry[0])} – {formatPrice(plan.entry[1])}
              </span>
            </div>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-foreground/80">
            {plan.stop !== null && plan.stop !== undefined && (
              <span>
                <span className="text-muted-foreground">止损：</span>
                <span className={cn("num", isLong ? "text-neon-magenta" : "text-neon-lime")}>
                  {formatPrice(plan.stop)}
                </span>
              </span>
            )}
            {plan.take_profit.length > 0 && (
              <span>
                <span className="text-muted-foreground">止盈：</span>
                <span className={cn("num", isLong ? "text-neon-lime" : "text-neon-magenta")}>
                  {plan.take_profit.map((v) => formatPrice(v)).join(" / ")}
                </span>
              </span>
            )}
          </div>
          <div className="text-[11px] text-muted-foreground">
            失效：{plan.invalidation}
          </div>
        </div>
      ) : (
        <div className="mt-1.5 text-xs text-muted-foreground">
          {fallbackTrigger
            ? `参考：${fallbackTrigger}`
            : "暂无合适触发点 · 等待结构清晰"}
        </div>
      )}
    </div>
  );
}

function pickPlan(plans: TradingPlan[], actions: string[]): TradingPlan | null {
  const filtered = plans.filter((p) => actions.includes(p.action));
  if (filtered.length === 0) return null;
  return filtered.sort((a, b) => b.stars - a.stars)[0];
}
