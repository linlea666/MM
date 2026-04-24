import type { Level, LevelLadder } from "@/lib/types";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { strengthLabel } from "@/lib/ui-helpers";

interface Props {
  ladder: LevelLadder;
  /** 来自 Binance WS 的实时价，优先于 ladder.current_price */
  livePrice?: number | null;
}

/**
 * 空间结构图（立式金字塔）
 *
 * 设计要点（GPT 建议 + LIQ 参考）：
 * 1. 顶部阻力（R3/R2/R1）到底部支撑（S1/S2/S3），当前价居中发光
 * 2. 每档的水平线按「相对当前价距离」映射到视觉位置（不等距）
 *    - 让用户一眼看出「离哪近」
 * 3. 显式标注「上方空间 +x%」「下方空间 -y%」
 * 4. 标签强度（strong/medium/weak）决定线的粗细与颜色
 */
export function KeySpaceMap({ ladder, livePrice }: Props) {
  const current = livePrice ?? ladder.current_price;

  const resistances = [ladder.r1, ladder.r2, ladder.r3].filter(Boolean) as Level[];
  const supports = [ladder.s1, ladder.s2, ladder.s3].filter(Boolean) as Level[];

  // 上方空间 = 最近阻力距当前价的 %
  const upSpace = resistances[0]
    ? ((resistances[0].price - current) / current) * 100
    : null;
  // 下方空间 = 最近支撑距当前价的 %
  const downSpace = supports[0]
    ? ((supports[0].price - current) / current) * 100
    : null;

  return (
    <div className="panel-glass accent-stripe-cyan rounded-lg p-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            空间结构图
          </div>
          <div className="mt-0.5 text-sm font-semibold">上下方空间 · 关键位一览</div>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="chip chip-magenta">压力</span>
          <span className="chip chip-lime">支撑</span>
        </div>
      </div>

      <div className="holo-line-muted my-4" />

      <div className="space-y-0">
        {/* 上方空间标签 */}
        {upSpace !== null && (
          <div className="flex items-center justify-end gap-2 pb-2 text-xs">
            <span className="text-muted-foreground">↑ 上方空间</span>
            <span className="num font-semibold text-neon-magenta">
              +{formatPct(Math.abs(upSpace))}
            </span>
          </div>
        )}

        {/* 阻力（由远到近） */}
        {[...resistances].reverse().map((lv, i) => (
          <LevelBar
            key={`r-${i}`}
            level={lv}
            side="resistance"
            current={current}
          />
        ))}

        {/* 当前价高亮带 */}
        <CurrentPriceBar price={current} />

        {/* 支撑（由近到远） */}
        {supports.map((lv, i) => (
          <LevelBar
            key={`s-${i}`}
            level={lv}
            side="support"
            current={current}
          />
        ))}

        {/* 下方空间标签 */}
        {downSpace !== null && (
          <div className="flex items-center justify-end gap-2 pt-2 text-xs">
            <span className="text-muted-foreground">↓ 下方空间</span>
            <span className="num font-semibold text-neon-lime">
              {formatPct(downSpace)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function CurrentPriceBar({ price }: { price: number }) {
  return (
    <div className="relative my-3 flex items-center gap-3 rounded-md border border-neon-cyan/40 bg-neon-cyan/5 px-3 py-2.5 shadow-glow-cyan">
      <span className="shrink-0 rounded bg-neon-cyan/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-neon-cyan">
        当前价
      </span>
      <span className="num-hero flex-1 text-xl text-foreground glow-cyan">
        {formatPrice(price)}
      </span>
      <span
        className="pulse-dot shrink-0"
        style={{ background: "hsl(var(--neon-cyan))" }}
      />
    </div>
  );
}

function LevelBar({
  level,
  side,
  current,
}: {
  level: Level;
  side: "resistance" | "support";
  current: number;
}) {
  const isRes = side === "resistance";
  const gapPct = ((level.price - current) / current) * 100;

  // 强度 → 左侧彩条宽度
  const widthMap = { strong: "w-1.5", medium: "w-1", weak: "w-0.5" } as const;
  // 强度 → 透明度
  const opacityMap = { strong: "opacity-100", medium: "opacity-80", weak: "opacity-60" } as const;

  const colorBar = isRes
    ? "bg-neon-magenta"
    : "bg-neon-lime";
  const labelCls = isRes ? "text-neon-magenta" : "text-neon-lime";

  return (
    <div
      className={cn(
        "group relative flex items-center gap-3 py-1.5 pl-2 pr-3 transition-colors hover:bg-white/5",
        opacityMap[level.strength],
      )}
    >
      {/* 左侧强度彩条 */}
      <div
        className={cn(
          "h-6 shrink-0 rounded-sm",
          widthMap[level.strength],
          colorBar,
        )}
      />
      {/* 标签 + 价格 */}
      <div className="flex flex-1 items-baseline gap-2">
        <span
          className={cn(
            "shrink-0 text-[10px] font-bold uppercase tracking-wider",
            labelCls,
          )}
        >
          {isRes ? "阻力" : "支撑"}
        </span>
        <span className="num text-sm font-semibold text-foreground">
          {formatPrice(level.price)}
        </span>
        <span
          className={cn(
            "num text-[11px]",
            gapPct >= 0 ? "text-neon-magenta/80" : "text-neon-lime/80",
          )}
        >
          {gapPct >= 0 ? "+" : ""}
          {formatPct(gapPct)}
        </span>
      </div>
      {/* 强度 */}
      <span className="shrink-0 text-[10px] text-muted-foreground">
        {strengthLabel(level.strength)} · {level.sources.slice(0, 2).join("/")}
      </span>
    </div>
  );
}
