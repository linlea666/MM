import { Crosshair } from "lucide-react";

import type { TargetItemCard, TargetProjectionCard } from "@/lib/types";
import { cn, formatPrice, formatPct } from "@/lib/utils";

/**
 * V1.1 · Step 7 · 目标投影（Card B · TargetProjection）
 *
 * 视觉结构（详见 docs/dashboard-v1/MOMENTUM-PULSE.md）：
 *
 *   ▲ 上方 · 多头磁吸（按距离升序）
 *   T1 +0.9% 🎯 96,500 (📊 0.6) ⏳ 8 根
 *   T2 +2.6% 🎯 99,800 (📊 0.4) ⏳ 24 根
 *   ── 现价 ●
 *   T1 -1.2% 🛡 92,400 (📊 0.7) ⏳ 6 根
 *   T2 -2.4% 💣 91,300 (📊 0.5) ⏳ 12 根
 *   ▼ 下方 · 空头磁吸
 *
 * 铁律：confidence = 透明度；distance 越远越淡；bars_to_arrive 仅参考（⏳ 角标）。
 *      永远附「磁吸地图，不构成预测」的注脚。
 */
interface Props {
  card: TargetProjectionCard | null | undefined;
  /** 当前价（来自 useLivePrice，非空才显示中线价格） */
  livePrice: number | null;
}

export function TargetProjectionCardView({ card, livePrice }: Props) {
  if (!card || (card.above.length === 0 && card.below.length === 0)) {
    return (
      <div className="panel-glass rounded-lg p-4">
        <Header />
        <div className="mt-3 text-sm text-foreground/60">
          目标数据不足，等下一根 K 线
        </div>
        <div className="mt-1 text-[11px] text-muted-foreground">
          需 ROI / Pain / Cascade / Heatmap / Vacuum / 最近 R/S 任一来源
        </div>
      </div>
    );
  }

  // 顶部白话条：取「最近且置信度最高」的上方/下方各一个 item
  // 排序口径：先按 |distance| 升序，再按 confidence 降序，取第一
  const topAbove = pickFirst(card.above);
  const topBelow = pickFirst(card.below);

  return (
    <div className="panel-glass rounded-lg p-4">
      <Header />

      {/* 白话结论条（小白看这一行就够） */}
      <TargetVerdict
        topAbove={topAbove}
        topBelow={topBelow}
        livePrice={livePrice}
      />

      {/* 上方目标（按距离升序：近 → 远） */}
      <Section
        title="▲ 上方 · 多头磁吸（涨能涨到哪）"
        items={card.above}
        side="above"
      />

      {/* 现价中线 */}
      <div className="my-2 flex items-center gap-2 rounded bg-white/5 px-2 py-1.5">
        <div className="h-[2px] flex-1 bg-foreground/35" />
        <span className="num text-xs font-semibold text-foreground">
          {livePrice != null ? formatPrice(livePrice) : "—"}
        </span>
        <span className="text-[10px] text-muted-foreground">现价</span>
        <div className="h-[2px] flex-1 bg-foreground/35" />
      </div>

      {/* 下方目标（按距离升序：近 → 远） */}
      <Section
        title="▼ 下方 · 空头磁吸（跌能跌到哪）"
        items={card.below}
        side="below"
      />

      <div className="mt-3 text-[10px] text-foreground/55" title={card.note}>
        📍 {card.note} · ⏳ 到达 K 线数 = ATR 估算 · ⭐ 越多越可靠
      </div>
    </div>
  );
}

function pickFirst(items: TargetItemCard[]): TargetItemCard | null {
  if (items.length === 0) return null;
  // 按 |distance| 升序 + confidence 降序，取第一名
  const sorted = [...items].sort((a, b) => {
    const da = Math.abs(a.distance_pct);
    const db = Math.abs(b.distance_pct);
    if (da !== db) return da - db;
    return b.confidence - a.confidence;
  });
  return sorted[0];
}

function Header() {
  return (
    <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
      <Crosshair className="h-3.5 w-3.5" />
      目标投影 · 磁吸地图
    </div>
  );
}

// ─── 小白白话总结条（最重要的两行） ─────────────

/**
 * 模板：
 *   🎯 涨到 81,069  +0.5% · 约 6 根 · ⭐⭐⭐⭐
 *   🛡 跌到 75,873  -2.3% · 约 12 根 · ⭐⭐⭐
 *
 * 取规则：上方 / 下方各取「最近 + 最高置信度」的第一名（pickFirst）。
 */
function TargetVerdict({
  topAbove,
  topBelow,
  livePrice,
}: {
  topAbove: TargetItemCard | null;
  topBelow: TargetItemCard | null;
  livePrice: number | null;
}) {
  return (
    <div className="mt-2 space-y-1 rounded border border-foreground/10 bg-white/5 px-3 py-2">
      <VerdictLine
        item={topAbove}
        side="above"
        livePrice={livePrice}
        emptyText="上方暂无明显磁吸目标"
      />
      <VerdictLine
        item={topBelow}
        side="below"
        livePrice={livePrice}
        emptyText="下方暂无明显防线"
      />
    </div>
  );
}

function VerdictLine({
  item,
  side,
  livePrice,
  emptyText,
}: {
  item: TargetItemCard | null;
  side: "above" | "below";
  livePrice: number | null;
  emptyText: string;
}) {
  const tone = side === "above" ? "text-neon-lime" : "text-neon-magenta";
  const arrow = side === "above" ? "🎯 涨到" : "🛡 跌到";

  if (!item || livePrice == null) {
    return (
      <div className="text-[11px] text-foreground/55">
        <span className="opacity-70">{arrow}</span> {emptyText}
      </div>
    );
  }
  const stars = confidenceStars(item.confidence);
  const barsText =
    item.bars_to_arrive == null
      ? ""
      : item.bars_to_arrive >= 50
      ? " · 约 50+ 根"
      : ` · 约 ${item.bars_to_arrive} 根`;

  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12px]">
      <span className="text-foreground/70">{arrow}</span>
      <span className={cn("num text-base font-semibold", tone)}>
        {formatPrice(item.price)}
      </span>
      <span className={cn("num text-[11px]", tone)}>
        {item.distance_pct >= 0 ? "+" : ""}
        {formatPct(item.distance_pct * 100)}
      </span>
      <span className="text-[11px] text-foreground/60">{barsText}</span>
      <span className="text-[11px]" title={`置信度 ${item.confidence.toFixed(2)}`}>
        {stars}
      </span>
    </div>
  );
}

function confidenceStars(conf: number): string {
  // 5 档星星：[0, 0.25) / [0.25, 0.45) / [0.45, 0.65) / [0.65, 0.8) / [0.8, 1]
  if (conf >= 0.8) return "⭐⭐⭐⭐⭐";
  if (conf >= 0.65) return "⭐⭐⭐⭐";
  if (conf >= 0.45) return "⭐⭐⭐";
  if (conf >= 0.25) return "⭐⭐";
  return "⭐";
}

function Section({
  title,
  items,
  side,
}: {
  title: string;
  items: TargetItemCard[];
  side: "above" | "below";
}) {
  if (items.length === 0) {
    return (
      <div className="mt-2">
        <div className="text-[11px] text-muted-foreground">{title}</div>
        <div className="mt-1 text-[11px] text-foreground/55">— 无</div>
      </div>
    );
  }
  return (
    <div className="mt-2">
      <div className="text-[11px] text-muted-foreground">{title}</div>
      <div className="mt-1 space-y-1">
        {items.map((it, i) => (
          <TargetRow key={`${it.kind}-${it.tier}-${i}`} item={it} side={side} />
        ))}
      </div>
    </div>
  );
}

interface KindMeta {
  icon: string;
  label: string;
}

const KIND_META: Record<TargetItemCard["kind"], KindMeta> = {
  roi: { icon: "🎯", label: "ROI" },
  pain: { icon: "🛡", label: "Pain" },
  cascade_band: { icon: "💣", label: "Cascade" },
  heatmap: { icon: "🌡", label: "Heatmap" },
  vacuum: { icon: "💨", label: "Vacuum" },
  nearest_level: { icon: "◯", label: "Nearest" },
};

function TargetRow({
  item,
  side,
}: {
  item: TargetItemCard;
  side: "above" | "below";
}) {
  const meta = KIND_META[item.kind];
  // 颜色：above = 多头绿色调 / below = 空头红色调
  const baseTone = side === "above" ? "text-neon-lime" : "text-neon-magenta";
  const bandBg =
    side === "above"
      ? "bg-[hsl(var(--neon-lime)/0.06)]"
      : "bg-[hsl(var(--neon-magenta)/0.06)]";
  const fillBg =
    side === "above" ? "bg-neon-lime/60" : "bg-neon-magenta/60";

  // confidence 决定透明度（0.35 ~ 1.0 之间，避免完全消失）
  const itemOpacity = Math.max(0.35, item.confidence);
  // 距离条：相对 max_distance（按 8% 算，距离越近条越短）
  const distancePct = Math.abs(item.distance_pct);
  const distanceFill = Math.max(8, Math.min(100, (distancePct / 0.08) * 100));

  return (
    <div
      className={cn("rounded px-2 py-1.5", bandBg)}
      style={{ opacity: itemOpacity }}
      title={item.evidence}
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-center gap-1.5 truncate">
          <span className="text-base leading-none">{meta.icon}</span>
          <span className={cn("text-[10px] font-semibold", baseTone)}>
            {item.tier}
          </span>
          <span className="num text-sm font-semibold text-foreground">
            {formatPrice(item.price)}
          </span>
        </div>
        <div className="flex items-baseline gap-1.5 text-[10px]">
          <span className={cn("num font-medium", baseTone)}>
            {item.distance_pct >= 0 ? "+" : ""}
            {formatPct(item.distance_pct * 100)}
          </span>
          <span className="text-foreground/55" title="confidence">
            📊 {item.confidence.toFixed(2)}
          </span>
        </div>
      </div>

      {/* 距离条（视觉化磁吸距离） */}
      <div className="mt-1 h-1 overflow-hidden rounded bg-foreground/10">
        <div
          className={cn("h-full", fillBg)}
          style={{ width: `${100 - distanceFill}%` }}
        />
      </div>

      <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-foreground/55">
        <span className="truncate" title={item.evidence}>
          {meta.label} · {item.evidence}
        </span>
        <span className="shrink-0">
          ⏳{" "}
          {item.bars_to_arrive == null
            ? "—"
            : item.bars_to_arrive >= 50
            ? "50+ 根"
            : `${item.bars_to_arrive} 根`}
        </span>
      </div>
    </div>
  );
}
