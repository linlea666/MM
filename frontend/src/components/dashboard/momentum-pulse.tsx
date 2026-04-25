import { useMemo, useState } from "react";
import { Activity, Zap, Flame, Hourglass } from "lucide-react";

import type {
  MomentumContribItem,
  MomentumFatigue,
  MomentumPulseCard,
  MomentumOverrideEvent,
  MomentumPulseMultiItem,
  MomentumSide,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { useSymbolStore } from "@/stores/symbol-store";
import { useMomentumPulseMulti } from "@/hooks/use-momentum-pulse-multi";

/**
 * V1.1 · Step 7 · 动能能量柱（Card A · MomentumPulse）
 *
 * 视觉结构（详见 docs/dashboard-v1/MOMENTUM-PULSE.md）：
 *   ┌─ 多 TF 三色灯带 ──────────────────────────┐
 *   │ 30m ●  1h ●  4h ◐                         │
 *   ├─ 主视觉 · 双向能量柱 ────────────────────┤
 *   │ ▲ 多头 ░░░░░▓▓▓▓▓ score_long             │
 *   │   ──── 中线（current） · ⚡ override     │
 *   │ ▼ 空头 ▓▓▓▓▓░░░░░ score_short            │
 *   ├─ 数字层 · streak / fatigue ─────────────┤
 *   │ 连续 3 根多 · ⚠ 中段疲劳                 │
 *   ├─ 证据链（折叠） ─────────────────────────┤
 *   └─────────────────────────────────────────┘
 *
 * 铁律：score 是「当前烧多大」，override 是「刚刚发生的反向事件」，两者并列展示，
 * 不互相覆盖；fatigue 直接乘入 confidence，决定柱体的不透明度。
 */
interface Props {
  card: MomentumPulseCard | null | undefined;
  /** 当前主 dashboard tf（用于多 TF 灯带高亮） */
  tf: string;
}

const TF_LIST = ["30m", "1h", "4h"] as const;

export function MomentumPulseCardView({ card, tf }: Props) {
  const symbol = useSymbolStore((s) => s.symbol);
  const multi = useMomentumPulseMulti(symbol, TF_LIST);
  const [showContribs, setShowContribs] = useState(false);

  if (!card) {
    return (
      <div className="panel-glass rounded-lg p-4">
        <Header tf={tf} multiItems={multi.data?.items} mainCardSide="neutral" />
        <div className="mt-3 text-sm text-foreground/60">动能数据待生成</div>
        <div className="mt-1 text-[11px] text-muted-foreground">
          需 power_imbalance / cvd / imbalance 任一原子有数据
        </div>
      </div>
    );
  }

  const opacity = 1 - card.fatigue_decay;
  const dominant = card.dominant_side;
  const stripe =
    dominant === "long"
      ? "accent-stripe-lime"
      : dominant === "short"
      ? "accent-stripe-magenta"
      : "";

  return (
    <div className={cn("panel-glass rounded-lg p-4", stripe)}>
      <Header tf={tf} multiItems={multi.data?.items} mainCardSide={dominant} />

      {/* 主视觉 · 双向能量柱 */}
      <div className="mt-4">
        <DualBars
          scoreLong={card.score_long}
          scoreShort={card.score_short}
          opacity={opacity}
          override={card.override}
        />
      </div>

      {/* 数字层 */}
      <div className="mt-3 flex items-center justify-between gap-2 text-[11px]">
        <StreakChip streakBars={card.streak_bars} streakSide={card.streak_side} />
        <FatigueChip state={card.fatigue_state} decay={card.fatigue_decay} />
      </div>

      {/* override 详情（命中时才显示） */}
      {card.override && <OverrideStrip override={card.override} />}

      {/* 证据链（默认折叠） */}
      {card.contributions.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setShowContribs((v) => !v)}
            className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-foreground"
          >
            {showContribs ? "▼ 隐藏证据链" : "▶ 展开证据链"}
          </button>
          {showContribs && (
            <div className="mt-2 space-y-1">
              {card.contributions.map((c, i) => (
                <ContribRow key={`${c.label}-${i}`} item={c} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* 警示文案：永远显示，避免被理解成预测 */}
      <div className="mt-3 text-[10px] text-foreground/55">
        ⚠ 能量柱 = 当前烧多大；不预测下一根 K 线方向。
      </div>
    </div>
  );
}

// ─── 头部：标题 + 多 TF 三色灯带 ─────────────

function Header({
  tf,
  multiItems,
  mainCardSide,
}: {
  tf: string;
  multiItems: MomentumPulseMultiItem[] | undefined;
  mainCardSide: MomentumSide;
}) {
  return (
    <div className="flex items-start justify-between gap-2">
      <div>
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          <Activity className="h-3.5 w-3.5" />
          动能能量柱
        </div>
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          多空哪边在烧油 · 还能烧多久
        </div>
      </div>
      <MultiTfStrip
        items={multiItems}
        currentTf={tf}
        fallbackSide={mainCardSide}
      />
    </div>
  );
}

function MultiTfStrip({
  items,
  currentTf,
  fallbackSide,
}: {
  items: MomentumPulseMultiItem[] | undefined;
  currentTf: string;
  fallbackSide: MomentumSide;
}) {
  const map = useMemo(() => {
    const m = new Map<string, MomentumPulseMultiItem>();
    items?.forEach((it) => m.set(it.tf, it));
    return m;
  }, [items]);

  return (
    <div
      className="flex items-center gap-2 rounded border border-foreground/10 bg-white/5 px-2 py-1"
      title="多 TF 三色灯带：绿=偏多 / 红=偏空 / 灰=中性"
    >
      {TF_LIST.map((t) => {
        const item = map.get(t);
        // 主 tf 在多 tf 还没拉到时，用本地 card 的 dominant 兜底
        const fallback = t === currentTf ? fallbackSide : "neutral";
        const side = item?.momentum_pulse?.dominant_side ?? fallback;
        const score = item?.momentum_pulse
          ? Math.max(
              item.momentum_pulse.score_long,
              item.momentum_pulse.score_short,
            )
          : 0;
        const intensity = Math.max(0.25, score / 100);
        const isCurrent = t === currentTf;
        const dotClass =
          side === "long"
            ? "bg-neon-lime"
            : side === "short"
            ? "bg-neon-magenta"
            : "bg-foreground/30";

        return (
          <div
            key={t}
            className={cn(
              "flex items-center gap-1 text-[10px]",
              isCurrent ? "text-foreground" : "text-foreground/65",
            )}
          >
            <span
              className={cn("h-2 w-2 rounded-full", dotClass)}
              style={{ opacity: side === "neutral" ? 0.4 : intensity }}
            />
            <span className={cn(isCurrent && "font-semibold")}>{t}</span>
          </div>
        );
      })}
    </div>
  );
}

// ─── 双向能量柱（核心主视觉） ─────────────────

function DualBars({
  scoreLong,
  scoreShort,
  opacity,
  override,
}: {
  scoreLong: number;
  scoreShort: number;
  opacity: number;
  override: MomentumOverrideEvent | null | undefined;
}) {
  // 双向柱：上半（多头绿）+ 中线 + 下半（空头红）
  // 高度策略：每半 80px；柱长 = score%
  const longH = Math.max(2, Math.round((scoreLong / 100) * 80));
  const shortH = Math.max(2, Math.round((scoreShort / 100) * 80));
  // 柱体不透明度：受 fatigue_decay 影响（疲劳时颜色变淡）
  const visibleOpacity = Math.max(0.35, opacity);

  return (
    <div className="relative">
      {/* 上半：多头绿柱 */}
      <div className="flex h-[80px] items-end justify-center">
        <div
          className="w-12 rounded-t bg-gradient-to-t from-[hsl(var(--neon-lime)/0.5)] to-[hsl(var(--neon-lime))] transition-[height] duration-300"
          style={{ height: `${longH}px`, opacity: visibleOpacity }}
        />
      </div>

      {/* 中线（current price 指示） */}
      <div className="relative my-1 flex items-center">
        <div className="h-[2px] flex-1 bg-foreground/35" />
        {override && (
          <div
            className={cn(
              "absolute left-1/2 -translate-x-1/2 flex items-center gap-1 rounded-full border px-2 py-[2px] text-[10px] font-medium",
              override.direction === "bullish"
                ? "border-neon-lime/60 bg-[hsl(var(--neon-lime)/0.15)] text-neon-lime"
                : "border-neon-magenta/60 bg-[hsl(var(--neon-magenta)/0.15)] text-neon-magenta",
            )}
          >
            <Zap className="h-3 w-3 animate-pulse" />
            {override.kind}
            {override.direction === "bullish" ? "↑" : "↓"}
          </div>
        )}
      </div>

      {/* 下半：空头红柱 */}
      <div className="flex h-[80px] items-start justify-center">
        <div
          className="w-12 rounded-b bg-gradient-to-b from-[hsl(var(--neon-magenta)/0.5)] to-[hsl(var(--neon-magenta))] transition-[height] duration-300"
          style={{ height: `${shortH}px`, opacity: visibleOpacity }}
        />
      </div>

      {/* 数字 overlay */}
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-between py-1">
        <span
          className={cn(
            "num text-xs font-semibold",
            scoreLong >= scoreShort ? "text-neon-lime" : "text-foreground/55",
          )}
        >
          {scoreLong}
        </span>
        <span
          className={cn(
            "num text-xs font-semibold",
            scoreShort > scoreLong ? "text-neon-magenta" : "text-foreground/55",
          )}
        >
          {scoreShort}
        </span>
      </div>
    </div>
  );
}

// ─── 数字层 chips ─────────────────────────────

function StreakChip({
  streakBars,
  streakSide,
}: {
  streakBars: number;
  streakSide: "buy" | "sell" | "none";
}) {
  if (streakBars <= 0 || streakSide === "none") {
    return (
      <span className="text-foreground/55">无连续同向 imbalance</span>
    );
  }
  const tone =
    streakSide === "buy"
      ? "text-neon-lime border-neon-lime/40 bg-[hsl(var(--neon-lime)/0.08)]"
      : "text-neon-magenta border-neon-magenta/40 bg-[hsl(var(--neon-magenta)/0.08)]";
  const sideLabel = streakSide === "buy" ? "多" : "空";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-[2px] font-medium",
        tone,
      )}
    >
      <Flame className="h-3 w-3" />
      连续 {streakBars} 根{sideLabel}
    </span>
  );
}

function FatigueChip({
  state,
  decay,
}: {
  state: MomentumFatigue;
  decay: number;
}) {
  const map: Record<MomentumFatigue, { label: string; tone: string }> = {
    fresh: {
      label: "新鲜",
      tone: "text-foreground/70 border-foreground/15 bg-white/5",
    },
    mid: {
      label: "中段疲劳",
      tone: "text-neon-amber border-neon-amber/40 bg-[hsl(var(--neon-amber)/0.08)]",
    },
    exhausted: {
      label: "趋势衰竭",
      tone: "text-neon-magenta border-neon-magenta/40 bg-[hsl(var(--neon-magenta)/0.08)]",
    },
  };
  const cfg = map[state];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-[2px] font-medium",
        cfg.tone,
      )}
      title={`fatigue_decay = ${decay.toFixed(2)} · 直接乘入 confidence`}
    >
      <Hourglass className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

function OverrideStrip({ override }: { override: MomentumOverrideEvent }) {
  const tone =
    override.direction === "bullish"
      ? "border-neon-lime/40 bg-[hsl(var(--neon-lime)/0.08)] text-neon-lime"
      : "border-neon-magenta/40 bg-[hsl(var(--neon-magenta)/0.08)] text-neon-magenta";
  return (
    <div
      className={cn(
        "mt-2 rounded border px-2 py-1 text-[11px]",
        tone,
      )}
    >
      <div className="flex items-center gap-1.5 font-medium">
        <Zap className="h-3 w-3" />
        {override.detail}
      </div>
      <div className="mt-0.5 text-[10px] text-foreground/65">
        ⚡ 反向事件不翻转 score；仅作翻车警惕
      </div>
    </div>
  );
}

function ContribRow({ item }: { item: MomentumContribItem }) {
  const tone =
    item.delta > 0
      ? "text-neon-lime"
      : item.delta < 0
      ? "text-neon-magenta"
      : "text-foreground/65";
  const sign = item.delta > 0 ? "+" : "";
  return (
    <div className="flex items-center justify-between gap-2 rounded bg-white/5 px-2 py-1 text-[10px]">
      <div className="flex items-center gap-1 truncate">
        <span className="text-foreground/65">{item.label}</span>
        <span className="text-foreground/45">·</span>
        <span className="truncate text-foreground/75">{item.value}</span>
      </div>
      <span className={cn("num font-semibold", tone)}>
        {sign}
        {item.delta}
      </span>
    </div>
  );
}
