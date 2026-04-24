import type { ChochCard as ChochCardT } from "@/lib/types";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { Zap } from "lucide-react";

/**
 * ⚡ 机构破坏/突破卡
 *
 * 对应官方 inst_choch：近窗 N 根内出现 CHoCH/BOS 时，用白话显示
 *   - 事件类型（CHoCH / BOS + bullish/bearish）
 *   - 被砸穿的前高/前低价位
 *   - 距今几根 K 线
 *
 * 无事件时显示占位（保持栅格稳定，不抖屏）。
 */
interface Props {
  card: ChochCardT | null | undefined;
}

export function ChochCard({ card }: Props) {
  if (!card) {
    return (
      <div className="panel-glass rounded-lg p-4">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          <Zap className="h-3.5 w-3.5" />
          机构破坏/突破
        </div>
        <div className="mt-3 text-sm text-foreground/60">近窗无 ⚡ 事件</div>
        <div className="mt-1 text-[11px] text-muted-foreground">
          等待机构资金真金白银砸穿前高/前低
        </div>
      </div>
    );
  }

  const bullish = card.direction === "bullish";
  const tone = bullish ? "text-neon-lime" : "text-neon-magenta";
  const stripe = bullish ? "accent-stripe-lime" : "accent-stripe-magenta";
  const arrow = bullish ? "↑" : "↓";
  const kindZh = card.kind === "CHoCH" ? "破坏" : "突破";

  return (
    <div className={cn("panel-glass rounded-lg p-4", stripe)}>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <Zap className="h-3.5 w-3.5" />
        机构破坏/突破
      </div>

      <div className="mt-1 flex items-baseline gap-2">
        <span className={cn("text-lg font-semibold", tone)}>
          ⚡ {card.kind}
        </span>
        <span className="text-xs text-muted-foreground">
          {kindZh} · {bullish ? "看涨" : "看跌"}
        </span>
      </div>

      <div className="mt-3 text-[11px] text-muted-foreground">
        {card.kind === "CHoCH" ? "破掉" : "突破"}前{bullish ? "低" : "高"} {arrow}
      </div>
      <div className="num text-xl font-semibold text-foreground">
        {formatPrice(card.level_price)}
      </div>

      <div className="holo-line-muted my-3" />

      <div className="space-y-1 text-[11px]">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">触发价</span>
          <span className="num text-foreground/85">
            {formatPrice(card.price)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">距当前价</span>
          <span className={cn("num font-medium", tone)}>
            {formatPct(card.distance_pct * 100)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">发生在</span>
          <span className="font-medium text-foreground/85">
            {card.bars_since === 0
              ? "刚刚"
              : `${card.bars_since} 根 K 线前`}
          </span>
        </div>
      </div>

      <div className="mt-3 text-[11px] text-foreground/70">
        口诀：发令枪响切莫追，回踩防线挂单做。
      </div>
    </div>
  );
}
