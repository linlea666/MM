import type { TradingPlan } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StarRating } from "@/components/ui/star-rating";
import { Badge } from "@/components/ui/badge";
import { actionColor } from "@/lib/ui-helpers";
import { cn, formatPrice } from "@/lib/utils";

interface Props {
  plans: TradingPlan[];
}

export function TradePlansCard({ plans }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>交易计划 A / B / C</CardTitle>
      </CardHeader>
      <CardContent>
        {plans.length === 0 ? (
          <div className="py-4 text-center text-sm text-muted-foreground">
            当前无可执行计划
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {plans.map((p) => (
              <PlanCard key={p.label} plan={p} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PlanCard({ plan }: { plan: TradingPlan }) {
  return (
    <div className="space-y-2.5 rounded-md border border-border/40 bg-background/40 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="rounded bg-primary/20 px-1.5 py-0.5 text-xs font-bold text-primary">
            {plan.label}
          </span>
          <span className={cn("text-base font-semibold", actionColor(plan.action))}>
            {plan.action}
          </span>
        </div>
        <StarRating value={plan.stars} size={12} />
      </div>

      {plan.position_size && (
        <Badge variant="secondary" className="font-normal">
          仓位：{plan.position_size}
        </Badge>
      )}

      <dl className="space-y-1 text-xs">
        {plan.entry && (
          <KV
            label="入场"
            value={`${formatPrice(plan.entry[0])} - ${formatPrice(plan.entry[1])}`}
          />
        )}
        {plan.stop !== null && plan.stop !== undefined && (
          <KV label="止损" value={formatPrice(plan.stop)} valueClass="text-bearish" />
        )}
        {plan.take_profit.length > 0 && (
          <KV
            label="止盈"
            value={plan.take_profit.map((v) => formatPrice(v)).join(" / ")}
            valueClass="text-bullish"
          />
        )}
      </dl>

      <div className="space-y-1 border-t border-border/30 pt-2 text-xs">
        <div>
          <span className="text-muted-foreground">前提：</span>
          <span className="text-foreground/90">{plan.premise}</span>
        </div>
        <div>
          <span className="text-muted-foreground">失效：</span>
          <span className="text-foreground/90">{plan.invalidation}</span>
        </div>
      </div>
    </div>
  );
}

function KV({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("font-mono num font-medium", valueClass)}>{value}</dd>
    </div>
  );
}
