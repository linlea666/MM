import type { ParticipationGate as Gate } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { participationColor, scoreBarColor } from "@/lib/ui-helpers";
import { cn } from "@/lib/utils";
import { CheckCircle2 } from "lucide-react";

interface Props {
  gate: Gate;
}

export function ParticipationCard({ gate }: Props) {
  const pct = Math.round(gate.confidence * 100);
  return (
    <Card>
      <CardHeader>
        <CardTitle>主力参与确认</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          className={cn(
            "inline-block rounded-md px-3 py-2 text-lg font-semibold",
            participationColor(gate.level),
          )}
        >
          {gate.level}
        </div>

        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">置信度</span>
            <span className="font-mono num text-foreground/80">{pct}%</span>
          </div>
          <Progress
            value={pct}
            indicatorClassName={scoreBarColor(pct)}
          />
        </div>

        {gate.evidence.length > 0 && (
          <ul className="space-y-1.5 text-xs text-muted-foreground">
            {gate.evidence.slice(0, 6).map((e, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-primary/70" />
                <span>{e}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
