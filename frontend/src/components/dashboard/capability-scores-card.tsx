import type { CapabilityScore } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { scoreBarColor } from "@/lib/ui-helpers";

const CN_NAMES: Record<string, string> = {
  accumulation: "吸筹",
  distribution: "派发",
  breakout: "突破确认",
  reversal: "反转概率",
  key_level_strength: "关键位强度",
  liquidity_magnet: "流动性磁吸",
};

interface Props {
  scores: CapabilityScore[];
}

export function CapabilityScoresCard({ scores }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>六大能力评分</CardTitle>
      </CardHeader>
      <CardContent>
        {scores.length === 0 ? (
          <div className="py-4 text-center text-sm text-muted-foreground">
            暂无能力评分
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-3">
            {scores.map((s) => (
              <div key={s.name} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-foreground/80">
                    {CN_NAMES[s.name] ?? s.name}
                  </span>
                  <div className="flex items-baseline gap-1">
                    <span className="font-mono num font-medium">{s.score}</span>
                    <span className="font-mono num text-[10px] text-muted-foreground">
                      / 信心 {(s.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
                <Progress
                  value={s.score}
                  indicatorClassName={scoreBarColor(s.score)}
                />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
