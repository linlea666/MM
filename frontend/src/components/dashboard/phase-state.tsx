import type { PhaseState as PhaseStateT } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ArrowRight, AlertTriangle } from "lucide-react";
import { phaseColor, scoreBarColor } from "@/lib/ui-helpers";
import { cn } from "@/lib/utils";

interface Props {
  phase: PhaseStateT;
}

export function PhaseStateCard({ phase }: Props) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>趋势阶段</CardTitle>
        {phase.unstable && (
          <div className="flex items-center gap-1 text-xs text-warning">
            <AlertTriangle className="h-3.5 w-3.5" />
            不稳定
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          className={cn(
            "inline-block rounded-md px-3 py-2 text-lg font-semibold",
            phaseColor(phase.current),
          )}
        >
          {phase.current}
        </div>

        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">置信度</span>
            <span className="font-mono num text-foreground/80">
              {phase.current_score}/100
            </span>
          </div>
          <Progress
            value={phase.current_score}
            indicatorClassName={scoreBarColor(phase.current_score)}
          />
        </div>

        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">
            {phase.prev_phase ?? "—"}
          </span>
          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="font-medium text-foreground">{phase.current}</span>
          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">
            {phase.next_likely ?? "?"}
          </span>
        </div>

        <div className="text-xs text-muted-foreground">
          已持续 <span className="font-mono num text-foreground/80">{phase.bars_in_phase}</span> 根 K 线
        </div>
      </CardContent>
    </Card>
  );
}
