import type {
  BehaviorScore,
  LiquidityCompass,
  ParticipationGate,
  PhaseState,
} from "@/lib/types";
import { cn, formatPrice, formatPct } from "@/lib/utils";

/**
 * 决策大屏第二行：三张浓缩卡
 * 设计原则（GPT 建议）：把内部模型语言翻译成人话，不再裸露评分。
 */

interface MainForceProps {
  behavior: BehaviorScore;
  participation: ParticipationGate;
}

export function MainForceCompact({ behavior, participation }: MainForceProps) {
  // 行为 → 人话
  const behaviorText = humanizeBehavior(behavior.main, behavior.main_score);
  const colorTone = toneFromBehavior(behavior.main);

  // 主力参与 → 人话
  const participationText = humanizeParticipation(participation);

  return (
    <div className={cn("panel-glass rounded-lg p-4", stripeClass(colorTone))}>
      <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        主力行为
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={cn("text-lg font-semibold", toneTextClass(colorTone))}>
          {behaviorText.main}
        </span>
        <span className="text-xs text-muted-foreground">
          {behaviorText.tone}
        </span>
      </div>
      <div className="mt-2 text-xs text-foreground/75">
        {behaviorText.description}
      </div>

      <div className="holo-line-muted my-3" />

      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">主力参与</span>
        <span className={cn("text-xs font-medium", participationColorClass(participation.level))}>
          {participationText}
        </span>
      </div>

      {behavior.alerts.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {behavior.alerts.slice(0, 3).map((a, i) => (
            <span
              key={`${a.type}-${i}`}
              className={cn(
                "chip",
                a.strength >= 70 ? "chip-magenta" : "chip-amber",
              )}
            >
              {a.type}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

interface PhaseProps {
  phase: PhaseState;
}

export function PhaseCompact({ phase }: PhaseProps) {
  const { phrase, description, tone } = humanizePhase(phase);

  const stabilityText = phase.unstable
    ? "低"
    : phase.bars_in_phase >= 8
    ? "高"
    : phase.bars_in_phase >= 4
    ? "中"
    : "低";
  const stabilityClass =
    stabilityText === "高"
      ? "text-neon-lime"
      : stabilityText === "中"
      ? "text-foreground/80"
      : "text-neon-amber";

  return (
    <div className={cn("panel-glass rounded-lg p-4", stripeClass(tone))}>
      <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        市场阶段
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={cn("text-lg font-semibold", toneTextClass(tone))}>
          {phrase}
        </span>
      </div>
      <div className="mt-2 text-xs text-foreground/75">{description}</div>

      <div className="holo-line-muted my-3" />

      <div className="space-y-1 text-[11px]">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">持续时间</span>
          <span className="num text-foreground/85">
            {phase.bars_in_phase} 根 K 线
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">稳定性</span>
          <span className={cn("font-medium", stabilityClass)}>
            {stabilityText}
          </span>
        </div>
        {phase.next_likely && (
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">下一阶段</span>
            <span className="text-foreground/80">{phase.next_likely}</span>
          </div>
        )}
      </div>
    </div>
  );
}

interface LiquidityProps {
  liquidity: LiquidityCompass;
}

export function LiquidityCompact({ liquidity }: LiquidityProps) {
  const above = liquidity.above_targets.slice(0, 3);
  const below = liquidity.below_targets.slice(0, 3);

  // 总强度（最多 top 3 的平均）
  const aboveStrength = avgStrength(above.map((t) => t.intensity));
  const belowStrength = avgStrength(below.map((t) => t.intensity));

  const nearestDir = liquidity.nearest_side;
  const nearestPct = liquidity.nearest_distance_pct;

  const pullVerdict: string = (() => {
    if (!nearestDir || nearestPct === null || nearestPct === undefined) {
      return "均衡（无明显偏向）";
    }
    const strength = Math.abs(aboveStrength - belowStrength);
    if (strength < 0.2) return "均衡（上下拉力相当）";
    if (aboveStrength > belowStrength) {
      return `偏向上方（${formatPct(nearestPct)} 内）`;
    }
    return `偏向下方（${formatPct(nearestPct)} 内）`;
  })();

  return (
    <div className="panel-glass accent-stripe-cyan rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          流动性吸引
        </div>
        <span className="chip">{pullVerdict}</span>
      </div>

      <div className="mt-3 space-y-2.5">
        {/* 上方 */}
        <SideBlock
          title="↑ 上方吸引力（卖压区）"
          targets={above}
          empty="上方暂无显著流动性"
          color="magenta"
        />
        {/* 下方 */}
        <SideBlock
          title="↓ 下方吸引力（承接区）"
          targets={below}
          empty="下方暂无显著流动性"
          color="lime"
        />
      </div>
    </div>
  );
}

function SideBlock({
  title,
  targets,
  empty,
  color,
}: {
  title: string;
  targets: LiquidityCompass["above_targets"];
  empty: string;
  color: "lime" | "magenta";
}) {
  return (
    <div>
      <div
        className={cn(
          "mb-1 text-[11px] font-medium",
          color === "magenta" ? "text-neon-magenta/85" : "text-neon-lime/85",
        )}
      >
        {title}
      </div>
      {targets.length === 0 ? (
        <div className="text-[11px] text-muted-foreground/70">{empty}</div>
      ) : (
        <div className="space-y-1">
          {targets.map((t, i) => {
            const s = intensityLabel(t.intensity);
            return (
              <div
                key={i}
                className="flex items-center justify-between text-[11px]"
              >
                <span className="num text-foreground/85">
                  {formatPrice(t.price)}
                </span>
                <div className="flex items-center gap-2">
                  <span className="num text-[10px] text-muted-foreground">
                    {formatPct(t.distance_pct)}
                  </span>
                  <span
                    className={cn(
                      "chip",
                      s.strong
                        ? color === "magenta"
                          ? "chip-magenta"
                          : "chip-lime"
                        : s.medium
                        ? "chip-amber"
                        : "chip",
                    )}
                  >
                    {s.label}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── 人话翻译 ─────────────────────────────────────

function humanizeBehavior(main: BehaviorScore["main"], score: number): {
  main: string;
  tone: string;
  description: string;
} {
  switch (main) {
    case "强吸筹":
      return {
        main: "强吸筹",
        tone: `强度 ${score}`,
        description: "主力在低位大量接单，建仓迹象明显",
      };
    case "弱吸筹":
      return {
        main: "轻微吸筹",
        tone: `强度 ${score}`,
        description: "有零散接盘迹象，尚未形成共振",
      };
    case "强派发":
      return {
        main: "强派发",
        tone: `强度 ${score}`,
        description: "主力在高位大量出货，派发迹象明显",
      };
    case "弱派发":
      return {
        main: "轻微派发",
        tone: `强度 ${score}`,
        description: "有零星出货迹象，尚未形成共振",
      };
    case "趋势反转":
      return {
        main: "反转信号",
        tone: `强度 ${score}`,
        description: "行为数据出现反向信号，关注变盘",
      };
    case "横盘震荡":
      return {
        main: "横盘震荡",
        tone: `强度 ${score}`,
        description: "主力无主导动作，多空僵持",
      };
    default:
      return {
        main: "无明显主导",
        tone: "中性",
        description: "当前主力动作不突出，建议观望为主",
      };
  }
}

function humanizeParticipation(p: ParticipationGate): string {
  const conf = Math.round(p.confidence * 100);
  const base = {
    主力真参与: "有主力真参与",
    局部参与: "局部参与（未共振）",
    疑似散户: "疑似散户推动",
    垃圾时间: "垃圾时间（低可信）",
  }[p.level];
  return `${base}（置信度 ${conf}%）`;
}

function participationColorClass(level: ParticipationGate["level"]): string {
  switch (level) {
    case "主力真参与":
      return "text-neon-lime";
    case "局部参与":
      return "text-neon-cyan";
    case "疑似散户":
      return "text-neon-amber";
    case "垃圾时间":
      return "text-muted-foreground";
  }
}

function humanizePhase(p: PhaseState): {
  phrase: string;
  description: string;
  tone: Tone;
} {
  switch (p.current) {
    case "真突破启动":
      return {
        phrase: "真突破（趋势启动）",
        description: "突破有效，趋势方向已确认",
        tone: "lime",
      };
    case "趋势延续":
      return {
        phrase: "趋势延续",
        description: "沿方向运行中，回调即机会",
        tone: "lime",
      };
    case "底部吸筹震荡":
      return {
        phrase: "底部吸筹震荡",
        description: "低位反复整理，主力有建仓动作",
        tone: "cyan",
      };
    case "高位派发震荡":
      return {
        phrase: "高位派发震荡",
        description: "高位反复整理，主力有出货动作",
        tone: "magenta",
      };
    case "假突破猎杀":
      return {
        phrase: "假突破 · 猎杀",
        description: "扫损后反向，注意反手机会",
        tone: "magenta",
      };
    case "趋势耗竭":
      return {
        phrase: "趋势耗竭",
        description: "动能衰竭，警惕反转",
        tone: "amber",
      };
    case "黑洞加速":
      return {
        phrase: "黑洞加速",
        description: "真空区加速运行，注意目标兑现",
        tone: "amber",
      };
    default:
      return {
        phrase: "震荡（无方向）",
        description: "结构尚未明朗，建议观望",
        tone: "neutral",
      };
  }
}

type Tone = "lime" | "cyan" | "magenta" | "amber" | "neutral";

function stripeClass(tone: Tone): string {
  switch (tone) {
    case "lime":
      return "accent-stripe-lime";
    case "magenta":
      return "accent-stripe-magenta";
    case "amber":
      return "accent-stripe-amber";
    case "cyan":
      return "accent-stripe-cyan";
    default:
      return "";
  }
}

function toneTextClass(tone: Tone): string {
  switch (tone) {
    case "lime":
      return "text-neon-lime";
    case "magenta":
      return "text-neon-magenta";
    case "amber":
      return "text-neon-amber";
    case "cyan":
      return "text-neon-cyan";
    default:
      return "text-foreground/85";
  }
}

function toneFromBehavior(main: BehaviorScore["main"]): Tone {
  if (main === "强吸筹" || main === "弱吸筹") return "lime";
  if (main === "强派发" || main === "弱派发") return "magenta";
  if (main === "趋势反转") return "amber";
  return "neutral";
}

function intensityLabel(intensity: number): {
  label: string;
  strong: boolean;
  medium: boolean;
} {
  if (intensity >= 0.7) return { label: "强", strong: true, medium: false };
  if (intensity >= 0.4) return { label: "中", strong: false, medium: true };
  return { label: "弱", strong: false, medium: false };
}

function avgStrength(list: number[]): number {
  if (list.length === 0) return 0;
  return list.reduce((a, b) => a + b, 0) / list.length;
}
