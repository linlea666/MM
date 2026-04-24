import type { SegmentCard } from "@/lib/types";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { Target } from "lucide-react";

/**
 * 波段四维画像卡
 *
 * 对应 4 个指标的 JOIN 结果：
 *   - ROI (trend_roi_exhaustion)   —— 🎯 平均目标 / 极限目标
 *   - Pain (max_pain_drawdown)      —— 💧 洗盘容忍 / 极限防线
 *   - Time (time_exhaustion_window) —— ⏰ 平均寿命 / 死亡线倒计时
 *   - DdTolerance (max_drawdown_tolerance) —— 🛡️ 移动护城河 + 📌 黄色图钉刺穿次数
 *
 * 原则：任一维度缺失时对应行不显示（保持卡片紧凑）。
 */
interface Props {
  card: SegmentCard | null | undefined;
}

export function SegmentPortraitCard({ card }: Props) {
  if (!card) {
    return (
      <div className="panel-glass rounded-lg p-4">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          <Target className="h-3.5 w-3.5" />
          波段四维画像
        </div>
        <div className="mt-3 text-sm text-foreground/60">暂无波段画像</div>
        <div className="mt-1 text-[11px] text-muted-foreground">
          等待 ROI / Pain / Time / DdTolerance 任一维度生效
        </div>
      </div>
    );
  }

  const bullish = card.type === "Accumulation";
  const tone = bullish ? "text-neon-lime" : "text-neon-magenta";
  const stripe = bullish ? "accent-stripe-lime" : "accent-stripe-magenta";

  return (
    <div className={cn("panel-glass rounded-lg p-4", stripe)}>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <Target className="h-3.5 w-3.5" />
        波段四维画像
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={cn("text-lg font-semibold", tone)}>
          {card.type ?? "—"}
        </span>
        <span className="text-xs text-muted-foreground">
          {card.status ?? ""}
        </span>
      </div>

      {/* 维度覆盖度 */}
      {card.sources.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1 text-[10px]">
          {card.sources.map((s) => (
            <span
              key={s}
              className="rounded border border-foreground/15 bg-white/5 px-1.5 py-0.5 text-foreground/75"
            >
              {labelForSource(s)}
            </span>
          ))}
        </div>
      )}

      <div className="holo-line-muted my-3" />

      <div className="space-y-2.5 text-[11px]">
        {/* 🎯 ROI */}
        {(card.roi_limit_avg_price != null || card.roi_limit_max_price != null) && (
          <div>
            <div className="text-muted-foreground">🎯 未来收益目标</div>
            <div className="mt-0.5 grid grid-cols-2 gap-1 text-xs">
              <MiniCell
                label="平均（T1）"
                value={card.roi_limit_avg_price}
              />
              <MiniCell
                label="极限（T2）"
                value={card.roi_limit_max_price}
                strong
              />
            </div>
          </div>
        )}

        {/* 💧 Pain */}
        {(card.pain_avg_price != null || card.pain_max_price != null) && (
          <div>
            <div className="text-muted-foreground">💧 极限洗盘深度</div>
            <div className="mt-0.5 grid grid-cols-2 gap-1 text-xs">
              <MiniCell label="容忍" value={card.pain_avg_price} />
              <MiniCell label="极限防线" value={card.pain_max_price} strong />
            </div>
          </div>
        )}

        {/* 🛡️ DdTolerance */}
        {card.dd_trailing_current != null && (
          <div>
            <div className="text-muted-foreground">🛡️ 移动护城河</div>
            <div className="mt-0.5 flex items-center justify-between text-xs">
              <span className="num font-semibold text-foreground">
                {formatPrice(card.dd_trailing_current)}
              </span>
              <div className="flex items-center gap-2 text-[11px]">
                {card.dd_limit_pct != null && (
                  <span className="text-foreground/60">
                    允许 {formatPct(card.dd_limit_pct * 100)}
                  </span>
                )}
                {card.dd_pierce_count > 0 && (
                  <span className="text-neon-amber font-medium">
                    📌 × {card.dd_pierce_count}
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ⏰ Time */}
        {(card.bars_to_max != null || card.bars_to_avg != null) && (
          <div>
            <div className="text-muted-foreground">⏰ 趋势时间</div>
            <div className="mt-0.5 grid grid-cols-2 gap-1 text-xs">
              <BarsCell label="至平均" bars={card.bars_to_avg ?? null} />
              <BarsCell label="至死亡线" bars={card.bars_to_max ?? null} strong />
            </div>
          </div>
        )}
      </div>

      {card.hint && (
        <div className="mt-3 truncate text-[11px] text-foreground/70" title={card.hint}>
          {card.hint}
        </div>
      )}
    </div>
  );
}

function labelForSource(src: SegmentCard["sources"][number]): string {
  switch (src) {
    case "roi":
      return "ROI";
    case "pain":
      return "Pain";
    case "time":
      return "Time";
    case "dd_tolerance":
      return "Dd";
  }
}

function MiniCell({
  label,
  value,
  strong,
}: {
  label: string;
  value: number | null | undefined;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-1 rounded bg-white/5 px-1.5 py-1">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <span
        className={cn(
          "num",
          strong ? "font-semibold text-foreground" : "text-foreground/80",
        )}
      >
        {value != null ? formatPrice(value) : "—"}
      </span>
    </div>
  );
}

function BarsCell({
  label,
  bars,
  strong,
}: {
  label: string;
  bars: number | null;
  strong?: boolean;
}) {
  let display: string;
  let toneClass: string;

  if (bars == null) {
    display = "—";
    toneClass = "text-foreground/60";
  } else if (bars < 0) {
    display = `已越过 ${Math.abs(bars)} 根`;
    toneClass = "text-neon-magenta font-medium";
  } else if (bars === 0) {
    display = "撞线";
    toneClass = "text-neon-amber font-medium";
  } else {
    display = `${bars} 根`;
    toneClass = strong
      ? "text-foreground font-semibold num"
      : "text-foreground/80 num";
  }

  return (
    <div className="flex items-center justify-between gap-1 rounded bg-white/5 px-1.5 py-1">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <span className={cn(toneClass)}>{display}</span>
    </div>
  );
}
