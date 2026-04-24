import type { BandCard } from "@/lib/types";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { Bomb } from "lucide-react";

/**
 * 💣 连环爆仓区（cascade_liquidation）卡
 *
 * 官方定义：
 *   - 上方绿带（short_fuel）= 空头燃料，做空资金的连环爆仓区（诱多爆空）
 *   - 下方红带（long_fuel）= 多头燃料，做多资金的连环爆仓区（诱空爆多）
 *
 * 战法：雷区插针极限反转——价格急跌至红带时"做多接针"，急涨至绿带时"做空接针"。
 */
interface Props {
  longFuel: BandCard[];
  shortFuel: BandCard[];
}

export function LiquidationBandsCard({ longFuel, shortFuel }: Props) {
  const empty = longFuel.length === 0 && shortFuel.length === 0;

  return (
    <div className="panel-glass rounded-lg p-4">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <Bomb className="h-3.5 w-3.5" />
        连环爆仓区
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">
        💣 大资金重叠爆仓带（机构诱多/诱空燃料）
      </div>

      {empty ? (
        <div className="mt-3 text-sm text-foreground/60">暂无 💣 爆仓带</div>
      ) : (
        <div className="mt-3 space-y-3">
          <BandSection
            title="上方 · 空头燃料（诱多爆空）"
            rows={shortFuel}
            tone="magenta"
          />
          <BandSection
            title="下方 · 多头燃料（诱空爆多）"
            rows={longFuel}
            tone="lime"
          />
        </div>
      )}

      <div className="mt-3 text-[11px] text-foreground/70">
        口诀：针尖插带果断接，爆仓之后立刻闪。
      </div>
    </div>
  );
}

function BandSection({
  title,
  rows,
  tone,
}: {
  title: string;
  rows: BandCard[];
  tone: "lime" | "magenta";
}) {
  const color = tone === "lime" ? "text-neon-lime" : "text-neon-magenta";
  const toneBg =
    tone === "lime"
      ? "bg-[hsl(var(--neon-lime)/0.08)]"
      : "bg-[hsl(var(--neon-magenta)/0.08)]";

  if (rows.length === 0) {
    return (
      <div>
        <div className="text-[11px] text-muted-foreground">{title}</div>
        <div className="mt-1 text-xs text-foreground/55">—</div>
      </div>
    );
  }

  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{title}</div>
      <div className="mt-1.5 space-y-1.5">
        {rows.map((b) => {
          const width = Math.max(6, Math.round(b.intensity * 100));
          return (
            <div
              key={`${b.start_time}-${b.avg_price}`}
              className={cn("rounded px-2 py-1.5", toneBg)}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className={cn("num text-sm font-semibold", color)}>
                  {formatPrice(b.bottom_price)} – {formatPrice(b.top_price)}
                </span>
                <span className={cn("text-[11px] font-medium", color)}>
                  {b.strength_label}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between text-[10px] text-foreground/65">
                <span>均价 {formatPrice(b.avg_price)}</span>
                <span className="num">{formatPct(b.distance_pct * 100)}</span>
              </div>
              <div className="mt-1 h-1 overflow-hidden rounded bg-foreground/10">
                <div
                  className={cn(
                    "h-full",
                    tone === "lime"
                      ? "bg-neon-lime/70"
                      : "bg-neon-magenta/70",
                  )}
                  style={{ width: `${width}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
