import type { BehaviorScore } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { behaviorColor, scoreBarColor } from "@/lib/ui-helpers";
import { cn } from "@/lib/utils";

interface Props {
  behavior: BehaviorScore;
}

export function MainForceRadar({ behavior }: Props) {
  const subs = Object.entries(behavior.sub_scores);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>主力行为雷达</CardTitle>
        <div className="text-xs text-muted-foreground">
          主标签得分 {behavior.main_score}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 主标签 */}
        <div
          className={cn(
            "inline-flex items-baseline gap-2 rounded-md px-3 py-1.5",
            behaviorColor(behavior.main),
          )}
        >
          <span className="text-base font-semibold">{behavior.main}</span>
          <span className="text-xs opacity-80 num">
            {behavior.main_score}/100
          </span>
        </div>

        {/* sub scores 网格 */}
        {subs.length === 0 ? (
          <div className="text-xs text-muted-foreground">暂无分项评分</div>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
            {subs.map(([k, v]) => (
              <div key={k} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="font-mono num text-foreground/80">{v}</span>
                </div>
                <Progress
                  value={v}
                  indicatorClassName={scoreBarColor(v)}
                />
              </div>
            ))}
          </div>
        )}

        {/* 行为警报 */}
        {behavior.alerts.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-t border-border/40 pt-3">
            {behavior.alerts.map((a, i) => (
              <Badge
                key={`${a.type}-${i}`}
                variant={a.strength >= 70 ? "destructive" : "warning"}
                className="gap-1 font-normal"
              >
                <span>{a.type}</span>
                <span className="font-mono num text-[10px] opacity-70">
                  {a.strength}
                </span>
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
