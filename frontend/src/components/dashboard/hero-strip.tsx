import type { DashboardSnapshot } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { StarRating } from "@/components/ui/star-rating";
import { FlashNumber } from "@/components/ui/flash-number";
import { cn, formatPrice, formatTs } from "@/lib/utils";
import { Activity, Radar, ShieldAlert, Target } from "lucide-react";

interface Col {
  key: "main_behavior" | "market_structure" | "risk_status" | "action_conclusion";
  label: string;
  icon: typeof Activity;
  emphasis?: boolean;
}

const COLS: Col[] = [
  { key: "main_behavior", label: "主力行为", icon: Activity },
  { key: "market_structure", label: "市场结构", icon: Radar },
  { key: "risk_status", label: "风险状态", icon: ShieldAlert },
  { key: "action_conclusion", label: "交易结论", icon: Target, emphasis: true },
];

interface Props {
  snap: DashboardSnapshot;
}

export function HeroStrip({ snap }: Props) {
  const { hero, current_price, timestamp, symbol, tf } = snap;

  return (
    <Card className="overflow-hidden">
      <CardContent className="grid grid-cols-6 gap-4 p-4">
        {/* 左：symbol + price */}
        <div className="flex flex-col justify-between">
          <div className="text-xs text-muted-foreground">
            {symbol} · {tf}
          </div>
          <div className="mt-1 font-mono text-3xl font-semibold num tracking-tight">
            <FlashNumber
              value={current_price}
              format={(v) => formatPrice(v, 2)}
              showArrow
            />
          </div>
          <div className="text-xs text-muted-foreground">
            更新于 {formatTs(timestamp)}
          </div>
        </div>

        {/* 中：4 维度结论 */}
        {COLS.map((c) => (
          <div
            key={c.key}
            className={cn(
              "flex flex-col justify-between rounded-md border border-border/40 bg-background/40 p-3",
              c.emphasis && "border-primary/50 bg-primary/5",
            )}
          >
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <c.icon className="h-3.5 w-3.5" />
              {c.label}
            </div>
            <div
              className={cn(
                "mt-2 text-sm font-medium leading-snug",
                c.emphasis && "text-base text-primary",
              )}
            >
              {hero[c.key]}
            </div>
          </div>
        ))}

        {/* 右：星级 + 失效条件 */}
        <div className="flex flex-col justify-between">
          <div className="text-xs text-muted-foreground">信号强度</div>
          <StarRating value={hero.stars} size={18} />
          <div className="mt-2 text-xs text-muted-foreground">
            <span className="text-foreground/80">失效：</span>
            <span className="line-clamp-2">{hero.invalidation}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
