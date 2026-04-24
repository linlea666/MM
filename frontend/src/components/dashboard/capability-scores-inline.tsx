import type { CapabilityScore } from "@/lib/types";
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

/**
 * 能力评分（内联版，无 Card 外框）
 * 只在"深度数据"折叠面板中使用，避免与 panel-glass 双层边框冲突。
 */
export function CapabilityScoresInline({ scores }: Props) {
  if (scores.length === 0) {
    return (
      <div className="py-4 text-center text-sm text-muted-foreground">
        暂无能力评分
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
      {scores.map((s) => (
        <div key={s.name} className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-foreground/80">
              {CN_NAMES[s.name] ?? s.name}
            </span>
            <div className="flex items-baseline gap-1">
              <span className="num font-medium">{s.score}</span>
              <span className="num text-[10px] text-muted-foreground">
                / 信心 {(s.confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>
          <Progress value={s.score} indicatorClassName={scoreBarColor(s.score)} />
        </div>
      ))}
    </div>
  );
}
