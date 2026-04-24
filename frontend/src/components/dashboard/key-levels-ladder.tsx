import type { Level, LevelLadder } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fitColor,
  fitLabel,
  strengthColor,
  strengthLabel,
} from "@/lib/ui-helpers";
import { cn, formatPrice, formatPct } from "@/lib/utils";

interface Props {
  ladder: LevelLadder;
}

type Row =
  | { type: "level"; label: string; level: Level; side: "resistance" | "support" }
  | { type: "current"; price: number };

export function KeyLevelsLadder({ ladder }: Props) {
  const current = ladder.current_price;
  const rows: Row[] = [
    ladder.r3 && { type: "level", label: "R3", level: ladder.r3, side: "resistance" as const },
    ladder.r2 && { type: "level", label: "R2", level: ladder.r2, side: "resistance" as const },
    ladder.r1 && { type: "level", label: "R1", level: ladder.r1, side: "resistance" as const },
    { type: "current" as const, price: current },
    ladder.s1 && { type: "level", label: "S1", level: ladder.s1, side: "support" as const },
    ladder.s2 && { type: "level", label: "S2", level: ladder.s2, side: "support" as const },
    ladder.s3 && { type: "level", label: "S3", level: ladder.s3, side: "support" as const },
  ].filter(Boolean) as Row[];

  return (
    <Card>
      <CardHeader>
        <CardTitle>关键位阶梯</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {rows.length <= 1 ? (
          <div className="py-4 text-center text-sm text-muted-foreground">
            暂无关键位
          </div>
        ) : (
          rows.map((r, i) => {
            if (r.type === "current") {
              return (
                <div
                  key={`cur-${i}`}
                  className="my-1 flex items-center gap-3 rounded-md border-2 border-primary/60 bg-primary/10 px-3 py-2"
                >
                  <span className="shrink-0 rounded bg-primary/30 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                    当前价
                  </span>
                  <span className="flex-1 font-mono text-lg font-semibold num text-primary">
                    {formatPrice(r.price)}
                  </span>
                </div>
              );
            }
            const gapPct = ((r.level.price - current) / current) * 100;
            return (
              <LevelRow
                key={`${r.label}-${i}`}
                label={r.label}
                level={r.level}
                side={r.side}
                gapPct={gapPct}
              />
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

function LevelRow({
  label,
  level,
  side,
  gapPct,
}: {
  label: string;
  level: Level;
  side: "resistance" | "support";
  gapPct: number;
}) {
  const isResistance = side === "resistance";
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-md border border-border/40 px-3 py-2 text-sm",
        "transition-colors hover:bg-accent/30",
        isResistance ? "bg-bearish/5" : "bg-bullish/5",
      )}
    >
      <span
        className={cn(
          "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold",
          isResistance ? "bg-bearish/20 text-bearish" : "bg-bullish/20 text-bullish",
        )}
      >
        {label}
      </span>

      <span className="font-mono num text-base font-medium">
        {formatPrice(level.price)}
      </span>

      <span
        className={cn(
          "font-mono num text-xs",
          gapPct >= 0 ? "text-bearish/80" : "text-bullish/80",
        )}
      >
        {gapPct >= 0 ? "+" : ""}
        {formatPct(gapPct)}
      </span>

      <span
        className={cn(
          "rounded px-1.5 py-0.5 text-[10px] font-medium",
          strengthColor(level.strength),
        )}
      >
        {strengthLabel(level.strength)}
      </span>

      <span className="text-xs text-muted-foreground/80">
        {level.sources.slice(0, 2).join(" / ")}
        {level.test_count > 0 && (
          <span className="ml-1 opacity-70">× {level.test_count}</span>
        )}
      </span>

      <span
        className={cn(
          "ml-auto text-[11px] font-medium whitespace-nowrap",
          fitColor(level.fit),
        )}
      >
        {fitLabel(level.fit)}
      </span>
    </div>
  );
}
