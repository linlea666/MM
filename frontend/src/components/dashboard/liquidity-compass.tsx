import type { LiquidityCompass, LiquidityTarget } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { ArrowDown, ArrowUp, Flame } from "lucide-react";

interface Props {
  liquidity: LiquidityCompass;
}

export function LiquidityCompassCard({ liquidity }: Props) {
  const { above_targets, below_targets, nearest_side, nearest_distance_pct } =
    liquidity;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>流动性磁吸</CardTitle>
        {nearest_side && nearest_distance_pct !== null &&
          nearest_distance_pct !== undefined && (
            <div className="flex items-center gap-1 text-xs">
              <Flame className="h-3 w-3 text-warning" />
              <span className="text-muted-foreground">最近：</span>
              <span
                className={cn(
                  "font-medium",
                  nearest_side === "above" ? "text-bearish" : "text-bullish",
                )}
              >
                {nearest_side === "above" ? "上方" : "下方"}
              </span>
              <span className="font-mono num text-foreground/80">
                {formatPct(nearest_distance_pct)}
              </span>
            </div>
          )}
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3">
        <TargetList
          title="上方目标"
          icon={<ArrowUp className="h-3.5 w-3.5 text-bearish" />}
          targets={above_targets}
          empty="上方暂无流动性目标"
          side="above"
        />
        <TargetList
          title="下方目标"
          icon={<ArrowDown className="h-3.5 w-3.5 text-bullish" />}
          targets={below_targets}
          empty="下方暂无流动性目标"
          side="below"
        />
      </CardContent>
    </Card>
  );
}

function TargetList({
  title,
  icon,
  targets,
  empty,
  side,
}: {
  title: string;
  icon: React.ReactNode;
  targets: LiquidityTarget[];
  empty: string;
  side: "above" | "below";
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        {icon}
        {title}
      </div>
      {targets.length === 0 ? (
        <div className="py-2 text-xs text-muted-foreground/60">{empty}</div>
      ) : (
        <ul className="space-y-1.5">
          {targets.slice(0, 4).map((t, i) => {
            const intensity = Math.round(t.intensity * 100);
            return (
              <li
                key={i}
                className={cn(
                  "space-y-1 rounded-md border border-border/40 px-2 py-1.5",
                  side === "above" ? "bg-bearish/5" : "bg-bullish/5",
                )}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono num font-medium">
                    {formatPrice(t.price)}
                  </span>
                  <span className="font-mono num text-muted-foreground">
                    {formatPct(t.distance_pct)}
                  </span>
                </div>
                <Progress
                  value={intensity}
                  className="h-1"
                  indicatorClassName={side === "above" ? "bg-bearish/80" : "bg-bullish/80"}
                />
                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                  <span>{t.source}</span>
                  <span className="font-mono num">强度 {intensity}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
