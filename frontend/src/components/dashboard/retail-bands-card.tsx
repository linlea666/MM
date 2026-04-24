import type { BandCard } from "@/lib/types";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { Magnet } from "lucide-react";

/**
 * 散户止损带（retail_stop_loss）卡
 *
 * 官方定义：
 *   - 上方绿带（short_fuel）= 散户做空止损（买单），磁吸向上
 *   - 下方红带（long_fuel）= 散户做多止损（卖单），磁吸向下
 *
 * 战法：判断磁吸方向——哪里深色带多，价格就往哪里扫。
 */
interface Props {
  longFuel: BandCard[];
  shortFuel: BandCard[];
}

export function RetailBandsCard({ longFuel, shortFuel }: Props) {
  const empty = longFuel.length === 0 && shortFuel.length === 0;

  // 简单磁吸方向判定：哪侧总 intensity 更高
  const upSum = shortFuel.reduce((a, b) => a + b.intensity, 0);
  const downSum = longFuel.reduce((a, b) => a + b.intensity, 0);
  const magnetHint =
    empty
      ? null
      : upSum > downSum * 1.2
        ? "上方散户密集 → 扫空头做多"
        : downSum > upSum * 1.2
          ? "下方散户密集 → 扫多头做空"
          : "两侧势均力敌 → 警惕插针";

  return (
    <div className="panel-glass rounded-lg p-4">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <Magnet className="h-3.5 w-3.5" />
        散户止损带
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">
        磁吸方向 · 主力扫货目标
      </div>

      {empty ? (
        <div className="mt-3 text-sm text-foreground/60">暂无止损带</div>
      ) : (
        <>
          {magnetHint && (
            <div className="mt-2 rounded border border-foreground/10 bg-white/5 px-2 py-1 text-[11px] text-foreground/80">
              🧲 {magnetHint}
            </div>
          )}
          <div className="mt-2 space-y-3">
            <Section
              title="上方 · 散户空头止损"
              rows={shortFuel}
              tone="lime"
            />
            <Section
              title="下方 · 散户多头止损"
              rows={longFuel}
              tone="magenta"
            />
          </div>
        </>
      )}

      <div className="mt-3 text-[11px] text-foreground/70">
        口诀：带子没断是磁铁，带子一断顺势追。
      </div>
    </div>
  );
}

function Section({
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
      ? "bg-[hsl(var(--neon-lime)/0.06)]"
      : "bg-[hsl(var(--neon-magenta)/0.06)]";

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
      <div className="mt-1.5 space-y-1">
        {rows.map((b) => (
          <div
            key={`${b.start_time}-${b.avg_price}`}
            className={cn(
              "flex items-center justify-between rounded px-2 py-1",
              toneBg,
            )}
          >
            <span className={cn("num text-sm font-semibold", color)}>
              {formatPrice(b.bottom_price)} – {formatPrice(b.top_price)}
            </span>
            <div className="flex items-center gap-2 text-[11px]">
              <span className="text-foreground/60">
                {formatPct(b.distance_pct * 100)}
              </span>
              <span className={cn("font-medium", color)}>
                {b.strength_label}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
